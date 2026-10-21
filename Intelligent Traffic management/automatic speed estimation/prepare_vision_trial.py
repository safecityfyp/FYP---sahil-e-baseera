"""Extract speed-label-free image sheets from saved detection tracks (no inference)."""
from pathlib import Path
import json
import hashlib
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
CASES = [
    ('M01', 'MercedesAMG550', '30'), ('M02', 'MercedesAMG550', '60'),
    ('M03', 'MercedesAMG550', '100'), ('K01', 'KiaSportage', '31'),
    ('K02', 'KiaSportage', '65'), ('K03', 'KiaSportage', '105'),
]


def prepare(source_root, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    private = []
    for case_id, vehicle, suffix in CASES:
        stem = f'{vehicle}_{suffix}'
        saved = (ROOT/'output/mercedes_validation/inference'/stem if vehicle.startswith('Mercedes')
                 else ROOT/'output/kia_validation/measurements/development/inference'/stem)
        tracks = json.loads((saved/'tracks.json').read_text())
        report = json.loads((saved/'geometry_run_report.json').read_text())
        groups = {}
        for row in tracks:
            x1, y1, x2, y2 = row['box']
            if x1 > 25 and x2 < report['width']-25 and y2 < report['height']-25:
                groups.setdefault(row['track_id'], []).append(row)
        rows = max(groups.values(), key=lambda rr: max(r['box'][3]-r['box'][1] for r in rr))
        selected = [min(rows, key=lambda r: abs(r['box'][3]-r['box'][1]-h))
                    for h in [180, 230, 280, 330, 380]]
        selected = sorted({r['frame_index']: r for r in selected}.values(), key=lambda r:r['frame_index'])
        cap = cv2.VideoCapture(str(Path(source_root)/vehicle/(stem+'.MP4')))
        folder = output/case_id
        folder.mkdir(exist_ok=True)
        panels, metadata = [], []
        for i, row in enumerate(selected):
            cap.set(cv2.CAP_PROP_POS_FRAMES, row['frame_index'])
            ok, frame = cap.read()
            if not ok:
                raise RuntimeError(f'Cannot decode {case_id} frame {row["frame_index"]}')
            cv2.imwrite(str(folder/f'frame_{i}.jpg'), frame)
            x1, y1, x2, y2 = row['box']
            x0, y0 = max(0, int(x1)-40), max(0, int(y1)-30)
            xx, yy = min(frame.shape[1], int(x2)+40), min(frame.shape[0], int(y2)+45)
            # One image pixel per panel pixel; offsets printed for exact annotation.
            crop = frame[y0:yy, x0:xx].copy()
            for x in range((x0//50+1)*50, xx, 50):
                cv2.line(crop, (x-x0,0), (x-x0,yy-y0), (75,75,75), 1)
                cv2.putText(crop,str(x),(x-x0+1,13),0,.35,(0,255,255),1)
            for y in range((y0//25+1)*25, yy, 25):
                cv2.line(crop,(0,y-y0),(xx-x0,y-y0),(75,75,75),1)
                cv2.putText(crop,str(y),(2,y-y0-2),0,.35,(0,255,255),1)
            panel = np.full((520,1150,3), 245, np.uint8)
            label = f'{case_id} frame_{i} | source frame {row["frame_index"]} | x0={x0}, y0={y0}'
            cv2.putText(panel,label,(12,25),0,.65,(20,20,20),2)
            if crop.shape[1] > 1130 or crop.shape[0] > 470:
                raise RuntimeError('Panel too small; keep original pixel coordinates')
            panel[40:40+crop.shape[0],10:10+crop.shape[1]] = crop
            panels.append(panel)
            metadata.append(dict(frame_index=row['frame_index'], time_s=row['time_s'],
                                 box=row['box'], image=f'frame_{i}.jpg', crop_origin=[x0,y0]))
        cap.release()
        sheet = np.vstack(panels)
        cv2.imwrite(str(folder/'contact_sheet.jpg'),sheet)
        public = dict(case_id=case_id, width=report['width'], height=report['height'], fps=report['fps'],
                      target_track_id=selected[0]['track_id'], frames=metadata,
                      selection='Nearest untruncated detection heights 180,230,280,330,380 px; no speed input.',
                      analyst='Current assistant visual analysis; no external model API called.')
        (folder/'frames.json').write_text(json.dumps(public,indent=2)+'\n')
        private.append(dict(case_id=case_id, source_video=stem+'.MP4', vehicle=vehicle,
                            measurement_directory=str(saved.relative_to(ROOT))))
    # These labels are intentionally separate from the annotation/calibration inputs.
    (output/'evaluation_sources.json').write_text(json.dumps(private,indent=2)+'\n')


if __name__ == '__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-root', required=True)
    p.add_argument('--output', default=str(ROOT/'output/vision_assisted_trial'))
    a=p.parse_args()
    prepare(a.source_root,a.output)
