# Usage: python scripts/gen_survey.py naval_anchorage_camera_survey.xlsx src/data/navalAnchorageSurvey.ts
# Regenerates the typed survey module from the field GPS spreadsheet (stdlib only, no openpyxl).
import zipfile, sys, math, json, datetime, xml.etree.ElementTree as ET
M='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
z=zipfile.ZipFile(sys.argv[1])
ss=[''.join(t.text or '' for t in si.iter(M+'t')) for si in ET.fromstring(z.read('xl/sharedStrings.xml')).findall(M+'si')] if 'xl/sharedStrings.xml' in z.namelist() else []
def rows(n):
    out=[]
    for row in ET.fromstring(z.read(n)).iter(M+'row'):
        r={}
        for c in row.findall(M+'c'):
            col=''.join(ch for ch in c.get('r') if ch.isalpha()); v=c.find(M+'v'); t=c.get('t')
            if t=='s' and v is not None: r[col]=ss[int(v.text)]
            elif t=='inlineStr': r[col]=''.join(x.text or '' for x in c.iter(M+'t'))
            else: r[col]=v.text if v is not None else None
        out.append(r)
    return out
def ts(serial):
    d=datetime.datetime(1899,12,30)+datetime.timedelta(days=float(serial))
    return d.strftime('%Y-%m-%dT%H:%M:%S')+'+05:00'
track=rows('xl/worksheets/sheet1.xml'); wps=rows('xl/worksheets/sheet2.xml')
assert track[0]['C']=='Latitude' and track[0]['D']=='Longitude', track[0]
assert wps[0]['D']=='Latitude' and wps[0]['E']=='Longitude', wps[0]
pts=[(float(r['C']),float(r['D'])) for r in track[1:] if r.get('C') and r.get('D')]
lat0=sum(p[0] for p in pts)/len(pts)
kx=111320*math.cos(math.radians(lat0)); ky=110540
def xy(p): return ((p[1])*kx,(p[0])*ky)
def dist(a,b):
    ax,ay=xy(a); bx,by=xy(b); return math.hypot(ax-bx,ay-by)
# split on GPS gaps >80 m between consecutive fixes
segs=[[pts[0]]]
for a,b in zip(pts,pts[1:]):
    if dist(a,b)>80: segs.append([b])
    else: segs[-1].append(b)
def dp(seg,tol):
    if len(seg)<3: return seg
    ax,ay=xy(seg[0]); bx,by=xy(seg[-1]); L=math.hypot(bx-ax,by-ay)
    best,bi=-1,0
    for i in range(1,len(seg)-1):
        px,py=xy(seg[i])
        d=abs((bx-ax)*(ay-py)-(ax-px)*(by-ay))/L if L>0 else math.hypot(px-ax,py-ay)
        if d>best: best,bi=d,i
    if best>tol: return dp(seg[:bi+1],tol)[:-1]+dp(seg[bi:],tol)
    return [seg[0],seg[-1]]
sys.setrecursionlimit(20000)
simp=[dp(s,1.5) for s in segs if len(s)>1]
W=[]
for r in wps[1:]:
    if not r.get('B'): continue
    W.append(dict(n=int(float(r['A'])),name=r['B'].strip(),lat=float(r['D']),lon=float(r['E']),t=ts(r['C'])))
first=ts(track[1]['B']); last=ts(track[-1]['B'])
o=[]
o.append("/**\n * Naval Anchorage CCTV GPS survey — GENERATED from naval_anchorage_camera_survey.xlsx\n * (sheets 'GPS Waypoints' and 'GPS Track'). Do not hand-edit coordinates;\n * re-run scripts/gen_survey.py if the survey spreadsheet changes.\n *\n * Datum: WGS84 decimal degrees, as logged by the survey GPS receiver.\n * Waypoint coordinates are copied verbatim. The drive track (%d raw fixes) is\n * simplified with Douglas-Peucker at 1.5 m tolerance for rendering only.\n */\n" % len(pts))
o.append("export interface SurveyWaypoint {\n  /** waypoint # in the survey sheet */\n  n: number\n  /** name exactly as recorded in the field */\n  name: string\n  lat: number\n  lon: number\n  /** fix time (PKT) */\n  recordedAt: string\n}\n")
o.append(f"export const SURVEY_META = {{\n  source: 'naval_anchorage_camera_survey.xlsx',\n  datum: 'WGS84',\n  trackStart: '{first}',\n  trackEnd: '{last}',\n  rawTrackPoints: {len(pts)},\n  waypointCount: {len(W)},\n}} as const\n")
o.append("export const SURVEY_WAYPOINTS: SurveyWaypoint[] = [")
for w in W:
    o.append(f"  {{ n: {w['n']}, name: {json.dumps(w['name'])}, lat: {w['lat']!r}, lon: {w['lon']!r}, recordedAt: '{w['t']}' }},")
o.append("]\n")
o.append("/** Surveyed drive track as [lat, lon] polylines (split at GPS gaps > 80 m). */")
o.append("export const SURVEY_TRACK: [number, number][][] = [")
for s in simp:
    o.append("  ["+",".join(f"[{p[0]:.7f},{p[1]:.7f}]" for p in s)+"],")
o.append("]\n")
open(sys.argv[2],'w',encoding='utf-8',newline='\n').write("\n".join(o))
print('waypoints',len(W),'raw',len(pts),'segments',len(simp),'simplified',sum(len(s) for s in simp))
