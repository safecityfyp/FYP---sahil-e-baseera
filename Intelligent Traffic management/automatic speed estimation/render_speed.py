"""Render the offline experimental speed estimates and local mapping diagnostics."""
from pathlib import Path
import csv
import json
import subprocess
import os
from collections import defaultdict
import cv2
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from calibrate_speed import ROOT, OUT, GEOMETRY, project


def draw_grid(frame, calibration, footprints):
    height,width=frame.shape[:2]
    for side,cal in calibration.items():
        if not cal.get('accepted'):continue
        rows=[r for r in footprints if r['side']==side]
        if not rows:continue
        H=np.array(cal['H_image_to_experimental_meters'])
        image_points=np.array([r['quad'] for r in rows]).reshape(-1,2)
        world=project(image_points,H)
        low,high=np.percentile(world,[3,97],axis=0)
        mask=np.zeros((height,width),np.uint8)
        hull=cv2.convexHull(image_points.astype(np.float32)).astype(int)
        cv2.fillConvexPoly(mask,hull,255)
        overlay=np.zeros_like(frame)
        inv=np.linalg.inv(H)
        for axis in [0,1]:
            for value in np.arange(np.floor(low[axis]/5)*5,high[axis]+5,5):
                segment=np.array([[low[0]-5,low[1]-5],[high[0]+5,high[1]+5]])
                segment[:,axis]=value
                points=project(segment,inv)
                if np.isfinite(points).all() and np.max(np.abs(points))<100000:
                    a,b=points.astype(int);cv2.line(overlay,tuple(a),tuple(b),(60,200,255),2)
        selected=(mask>0)&np.any(overlay>0,axis=2)
        frame[selected]=overlay[selected]
        cv2.polylines(frame,[hull],True,(255,200,60),2)
    return frame


def main():
    calibration=json.loads((OUT/'calibration.json').read_text())
    footprints=json.loads((OUT/'filtered_ground_footprints.json').read_text())
    csv_path=OUT/'experimental_speeds.csv'
    speeds=list(csv.DictReader(csv_path.open(encoding='utf-8'))) if csv_path.exists() else []
    accepted={int(r['track_id']):r for r in speeds if r['quality_passed']=='True'}
    baseline=defaultdict(list)
    downloaded_tracks = ROOT / 'outputs' / 'baseline' / 'tracks.csv'
    default_tracks = downloaded_tracks if downloaded_tracks.exists() else ROOT / 'output' / 'inputs' / 'tracking' / 'tracks.csv'
    with Path(os.environ.get('FYP_BASELINE_TRACKS', str(default_tracks))).open(encoding='utf-8') as f:
        for row in csv.DictReader(f):baseline[int(row['frame_index'])].append(row)
    source_value = os.environ.get('FYP_SPEED_SOURCE')
    if not source_value:
        raise SystemExit('Set FYP_SPEED_SOURCE to the original CCTV video path. See README.md.')
    source = Path(source_value)
    capture=cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise SystemExit(f'Cannot open source video: {source}')
    fps=capture.get(cv2.CAP_PROP_FPS)
    width=int(capture.get(cv2.CAP_PROP_FRAME_WIDTH));height=int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    capture.set(cv2.CAP_PROP_POS_FRAMES,round(177*fps));ok,reference=capture.read();assert ok
    draw_grid(reference,calibration,footprints)
    cv2.putText(reference,'EXPERIMENTAL local mapping | 5 m grid under assumed car dimensions',
                (35,55),cv2.FONT_HERSHEY_SIMPLEX,1.05,(0,255,255),2)
    cv2.imwrite(str(OUT/'road_mapping.jpg'),reference)
    start,end=round(150*fps),round(210*fps)
    capture.set(cv2.CAP_PROP_POS_FRAMES,start)
    raw=OUT/'experimental_speed_preview.avi'
    writer=cv2.VideoWriter(str(raw),cv2.VideoWriter_fourcc(*'MJPG'),fps,(1280,720));assert writer.isOpened()
    labelled_frames=0
    example_saved=False
    try:
        for index in range(start,end):
            ok,frame=capture.read();assert ok,index
            frame=cv2.resize(frame,(1280,720));sx,sy=1280/width,720/height
            cv2.rectangle(frame,(0,0),(1280,66),(20,20,20),-1)
            cv2.putText(frame,'EXPERIMENTAL SPEED | approximate vehicle dimensions | accuracy unvalidated',
                        (15,25),cv2.FONT_HERSHEY_SIMPLEX,.62,(0,220,255),2)
            cv2.putText(frame,'Ranges show sensitivity to car size and calibration tracks; they are not confidence intervals.',
                        (15,51),cv2.FONT_HERSHEY_SIMPLEX,.52,(220,220,220),1)
            has_label=False
            for row in baseline.get(index,[]):
                if not row['track_id']:continue
                tid=int(float(row['track_id']));time_s=float(row['video_time_s'])
                speed=accepted.get(tid)
                active=speed is not None and float(speed['time_start_s'])<=time_s<=float(speed['time_end_s'])
                x1,y1,x2,y2=[int(float(row[k])*(sx if k.startswith('x') else sy)) for k in ['x1','y1','x2','y2']]
                if active:
                    label=(f'ID {tid}: EXP {float(speed["experimental_kmh"]):.0f} '
                           f'[{float(speed["dimension_and_fit_sensitivity_low_kmh"]):.0f}-'
                           f'{float(speed["dimension_and_fit_sensitivity_high_kmh"]):.0f}] km/h')
                    color=(0,220,255);has_label=True
                else:label='';color=(170,170,170)
                cv2.rectangle(frame,(x1,y1),(x2,y2),color,2)
                if not label:continue
                tx=max(5,min(x1,1280-cv2.getTextSize(label,cv2.FONT_HERSHEY_SIMPLEX,.55,1)[0][0]-5))
                ty=max(83,y1-8)
                cv2.putText(frame,label,(tx,ty),cv2.FONT_HERSHEY_SIMPLEX,.55,(0,0,0),3)
                cv2.putText(frame,label,(tx,ty),cv2.FONT_HERSHEY_SIMPLEX,.55,color,1)
            cv2.putText(frame,f't={index/fps:.2f}s | Gray boxes: speed unavailable | Speeds average the qualifying span',
                        (15,701),cv2.FONT_HERSHEY_SIMPLEX,.55,(0,220,255),1)
            if has_label:labelled_frames+=1
            if has_label and not example_saved:
                cv2.imwrite(str(OUT/'speed_example.jpg'),frame);example_saved=True
            writer.write(frame)
    finally:capture.release();writer.release()
    preview=OUT/'experimental_speed_preview.mp4'
    subprocess.run(['ffmpeg','-y','-loglevel','error','-i',str(raw),'-c:v','libx264','-crf','24',
                    '-pix_fmt','yuv420p','-movflags','+faststart',str(preview)],check=True)
    raw.unlink()

    fig,axes=plt.subplots(1,2,figsize=(14,7))
    for axis,side in zip(axes,['left','right']):
        cal=calibration.get(side,{})
        if cal.get('accepted'):
            H=np.array(cal['H_image_to_experimental_meters'])
            for tid in sorted(set(r['track_id'] for r in footprints if r['side']==side)):
                group=sorted([r for r in footprints if r['side']==side and r['track_id']==tid],key=lambda r:r['time_s'])
                centers=project(np.array([r['quad'] for r in group]),H).mean(axis=1)
                axis.plot(centers[:,0],centers[:,1],'.-',label=f'ID {tid}')
            axis.legend(fontsize=8);axis.set_aspect('equal',adjustable='datalim')
        else:axis.text(.5,.5,'Insufficient consistent geometry',ha='center',va='center',transform=axis.transAxes)
        axis.set_title(side.capitalize()+' carriageway: approximate local plane')
        axis.set_xlabel('Assumption-based metres');axis.set_ylabel('Assumption-based metres');axis.grid(alpha=.2)
    fig.suptitle('Experimental road mapping — arbitrary local origins; no independent distance validation')
    fig.tight_layout();fig.savefig(OUT/'birdseye_trajectories.jpg',dpi=150);plt.close(fig)
    if accepted:
        rows=list(accepted.values());nominal=np.array([float(r['experimental_kmh']) for r in rows])
        low=np.array([float(r['dimension_and_fit_sensitivity_low_kmh']) for r in rows])
        high=np.array([float(r['dimension_and_fit_sensitivity_high_kmh']) for r in rows])
        fig,axis=plt.subplots(figsize=(10,6))
        axis.errorbar(nominal,np.arange(len(rows)),xerr=np.stack([nominal-low,high-nominal]),fmt='o',capsize=5)
        axis.set_yticks(np.arange(len(rows)),[f'Track {r["track_id"]} ({r["side"]})' for r in rows])
        axis.set_xlabel('Experimental km/h under assumed dimensions')
        axis.set_title('Dimension and calibration-subset sensitivity envelopes\nNot confidence intervals; speed accuracy remains unvalidated')
        axis.grid(axis='x',alpha=.2);fig.tight_layout();fig.savefig(OUT/'speed_sensitivity.jpg',dpi=150);plt.close(fig)
    rendering={'preview_file':preview.name,'frames':end-start,'fps':fps,'duration_s':(end-start)/fps,
               'frames_with_experimental_speed_labels':labelled_frames,'accepted_track_ids':list(accepted)}
    (OUT/'render_report.json').write_text(json.dumps(rendering,indent=2),encoding='utf-8')
    print(json.dumps(rendering,indent=2))


if __name__=='__main__':main()
