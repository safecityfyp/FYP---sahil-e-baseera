# %% markdown
# FYP CCTV vehicle detection and tracking baseline
# Private source footage. First experiment: seconds 150–210, processed at full source FPS.
# YOLO11s detects COCO vehicles; ByteTrack associates detections over time.
# Outputs assess feasibility only. There are no labelled boxes, reference speeds, or metric calibration,
# so detection AP, tracking accuracy and km/h cannot be claimed from this run.

# %%
import subprocess
import sys
subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-q',
                       'ultralytics==8.4.175', 'lap>=0.5.12'])

# %%
from pathlib import Path
from collections import Counter
import csv
import importlib.metadata
import json
import time
import cv2
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import torch
from ultralytics import YOLO
from IPython.display import display, Video

OUT = Path('/kaggle/working/baseline')
OUT.mkdir(parents=True, exist_ok=True)
VIDEO_NAME = 'A3_ch14_20260822105146_20260822110347.mp4'
matches = list(Path('/kaggle/input').rglob(VIDEO_NAME))
assert len(matches) == 1, f'Expected exactly one source video; found {len(matches)}'
SOURCE = matches[0]
START_S, DURATION_S = 150.0, 60.0
DEVICE = 0 if torch.cuda.is_available() else 'cpu'
print('Source:', SOURCE)
print('GPU:', torch.cuda.get_device_name(0) if DEVICE == 0 else 'CPU fallback')
print('Experiment interval:', START_S, 'to', START_S + DURATION_S, 'seconds')

capture = cv2.VideoCapture(str(SOURCE))
assert capture.isOpened(), 'Cannot open HEVC source footage'
fps = float(capture.get(cv2.CAP_PROP_FPS))
width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
assert fps > 0 and width > 0 and height > 0
start_frame = round(START_S * fps)
end_frame = min(total_frames, round((START_S + DURATION_S) * fps))
capture.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
assert abs(capture.get(cv2.CAP_PROP_POS_FRAMES) - start_frame) <= 1, 'Frame seek failed'
print({'width': width, 'height': height, 'fps': fps, 'frames': total_frames})

# %% markdown
# Bounding-box bottom centres are saved as provisional ground-contact proxies.
# They can move with detection jitter and are not yet suitable for calibrated speeds.
# Tracker IDs are associations, not verified identities or unique vehicle counts.

# %%
tracker_config = OUT / 'bytetrack_25fps.yaml'
tracker_config.write_text('''tracker_type: bytetrack
track_high_thresh: 0.25
track_low_thresh: 0.10
new_track_thresh: 0.25
track_buffer: 30
match_thresh: 0.8
fuse_score: True
''', encoding='utf-8')
model = YOLO('yolo11s.pt')
# ByteTrack's frame-rate-aware constructor uses 30 FPS by default in Ultralytics.
# Rescale its buffer to retain approximately one second of missed tracks at 25 FPS.
tracker_config.write_text(tracker_config.read_text().replace('track_buffer: 30',
                           f'track_buffer: {round(fps)}'), encoding='utf-8')
preview_size = (1280, round(height * 1280 / width))
raw_preview = OUT / 'tracking_preview.avi'
writer = cv2.VideoWriter(str(raw_preview), cv2.VideoWriter_fourcc(*'MJPG'), fps, preview_size)
assert writer.isOpened(), 'Preview writer failed'
fields = ['frame_index', 'video_time_s', 'time_source', 'track_id', 'class_id',
          'class_name', 'confidence', 'x1', 'y1', 'x2', 'y2', 'contact_x', 'contact_y']
rows = []
sample_images = []
candidate_crops = {}
frame_count = 0
previous_pts = -1.0
start_wall = time.monotonic()
try:
    for frame_index in range(start_frame, end_frame):
        ok, frame = capture.read()
        if not ok:
            raise RuntimeError(f'Decode stopped unexpectedly at frame {frame_index}')
        pts = float(capture.get(cv2.CAP_PROP_POS_MSEC)) / 1000.0
        expected_time = frame_index / fps
        use_pts = np.isfinite(pts) and pts > previous_pts and abs(pts - expected_time) < 1.0
        timestamp = pts if use_pts else expected_time
        time_source = 'decoder_pts' if use_pts else 'frame_index_over_fps'
        previous_pts = pts
        result = model.track(frame, persist=True, tracker=str(tracker_config),
                             classes=[2, 3, 5, 7], conf=0.10, iou=0.7,
                             imgsz=1280, device=DEVICE, verbose=False)[0]
        boxes = result.boxes
        coords = boxes.xyxy.cpu().numpy()
        classes = boxes.cls.cpu().numpy().astype(int)
        confidences = boxes.conf.cpu().numpy()
        ids = boxes.id.cpu().numpy().astype(int) if boxes.id is not None else [None] * len(coords)
        for box, cls, confidence, tid in zip(coords, classes, confidences, ids):
            x1, y1, x2, y2 = [float(v) for v in box]
            row = dict(zip(fields, [frame_index, timestamp, time_source,
                       int(tid) if tid is not None else None, int(cls), model.names[int(cls)],
                       float(confidence), x1, y1, x2, y2, (x1+x2)/2, y2]))
            rows.append(row)
            if tid is not None and cls == 2 and confidence >= 0.65:
                area = max(0, x2-x1) * max(0, y2-y1)
                if area > candidate_crops.get(int(tid), (0, None, None))[0] and area > 10000:
                    crop = frame[max(0,int(y1)):min(height,int(y2)), max(0,int(x1)):min(width,int(x2))]
                    if crop.size: candidate_crops[int(tid)] = (area, crop.copy(), row.copy())
        annotated = result.plot()
        cv2.putText(annotated, f't={timestamp:.2f}s | Detection/tracking only | No metric calibration',
                    (25, height-30), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0,255,255), 2)
        writer.write(cv2.resize(annotated, preview_size))
        if frame_count % round(5*fps) == 0:
            image_path = OUT / f'frame_{frame_index:06d}.jpg'
            cv2.imwrite(str(image_path), annotated)
            sample_images.append((timestamp, cv2.resize(annotated, preview_size)))
        frame_count += 1
        if frame_count % round(10*fps) == 0:
            print(f'Processed {frame_count}/{end_frame-start_frame} frames; {len(rows)} observations', flush=True)
finally:
    capture.release()
    writer.release()
elapsed_s = time.monotonic() - start_wall
with (OUT / 'tracks.csv').open('w', newline='', encoding='utf-8') as handle:
    csv_writer = csv.DictWriter(handle, fieldnames=fields)
    csv_writer.writeheader()
    csv_writer.writerows(rows)
assert frame_count == end_frame-start_frame, 'Incomplete processing'
print('Completed frames:', frame_count, 'Runtime seconds:', round(elapsed_s, 1))

# %%
df = pd.DataFrame(rows, columns=fields)
tracked = df.dropna(subset=['track_id']).copy()
track_summaries = []
for tid, group in tracked.groupby('track_id', sort=True):
    group = group.sort_values('frame_index')
    first, last = group.iloc[0], group.iloc[-1]
    duration = float(last.video_time_s-first.video_time_s)
    displacement = float(np.hypot(last.contact_x-first.contact_x, last.contact_y-first.contact_y))
    track_summaries.append({'track_id': int(tid), 'class_name': group.class_name.mode().iloc[0],
       'observed_frames': len(group), 'first_video_time_s': float(first.video_time_s),
       'last_video_time_s': float(last.video_time_s), 'span_s': duration,
       'coverage_fraction': len(group)/(int(last.frame_index-first.frame_index)+1),
       'mean_detection_confidence': float(group.confidence.mean()),
       'endpoint_displacement_pixels': displacement,
       'max_gap_frames': int(group.frame_index.diff().max()) if len(group)>1 else 0})
summary_fields = ['track_id','class_name','observed_frames','first_video_time_s',
                  'last_video_time_s','span_s','coverage_fraction','mean_detection_confidence',
                  'endpoint_displacement_pixels','max_gap_frames']
summary = pd.DataFrame(track_summaries, columns=summary_fields)
summary.to_csv(OUT/'track_summary.csv', index=False)
display(summary.sort_values('observed_frames', ascending=False).head(20))

fig, axes = plt.subplots(3, 4, figsize=(20, 10))
for axis, sample in zip(axes.flat, sample_images):
    timestamp, sample_image = sample
    axis.imshow(cv2.cvtColor(sample_image, cv2.COLOR_BGR2RGB))
    axis.set_title(f'Video t={timestamp:.1f}s')
for axis in axes.flat: axis.axis('off')
fig.tight_layout()
fig.savefig(OUT/'detection_contact_sheet.jpg', dpi=150)
plt.show()

if sample_images:
    fig, axis = plt.subplots(figsize=(16, 9))
    axis.imshow(cv2.cvtColor(sample_images[0][1], cv2.COLOR_BGR2RGB), extent=(0,width,height,0))
    for tid, group in tracked.groupby('track_id'):
        if len(group) >= 10:
            axis.plot(group.contact_x, group.contact_y, linewidth=1.5)
    axis.set_title('Provisional bounding-box contact trajectories — image coordinates only')
    axis.set_xlim(0,width); axis.set_ylim(height,0)
    fig.tight_layout(); fig.savefig(OUT/'trajectories.jpg', dpi=150)
    plt.show()

crop_metadata = []
for tid, (area, crop, row) in sorted(candidate_crops.items(), key=lambda item: -item[1][0])[:12]:
    crop_name = f'car_candidate_id_{tid}.jpg'
    cv2.imwrite(str(OUT/crop_name), crop)
    crop_metadata.append({'file': crop_name, 'box_area_pixels': area, **row})
(OUT/'vehicle_crop_metadata.json').write_text(json.dumps(crop_metadata, indent=2), encoding='utf-8')

# %%
preview = OUT/'tracking_preview.mp4'
conversion = subprocess.run(['ffmpeg','-y','-loglevel','error','-i',str(raw_preview),
             '-c:v','libx264','-crf','24','-pix_fmt','yuv420p','-movflags','+faststart',str(preview)],
             capture_output=True, text=True)
if conversion.returncode == 0:
    raw_preview.unlink()
else:
    print('H.264 conversion failed; retained AVI:', conversion.stderr[-1000:])
    preview = raw_preview
report = {'stage':'vehicle_detection_and_tracking_baseline', 'metric_speed_available':False,
 'source_video':VIDEO_NAME, 'source_width':width, 'source_height':height, 'source_fps':fps,
 'source_frames':total_frames, 'start_s':START_S, 'duration_s':DURATION_S,
 'processed_frames':frame_count, 'detection_observations':len(df),
 'tracked_observations':len(tracked), 'tracker_ids':len(summary),
 'track_ids_with_at_least_25_observations':int((summary.observed_frames>=25).sum()),
 'observations_by_class':dict(Counter(df.class_name)),
 'timestamp_sources':dict(Counter(df.time_source)),
 'inference_wall_seconds':elapsed_s, 'model':'yolo11s.pt', 'tracker':'ByteTrack',
 'imgsz':1280, 'confidence_threshold':0.10, 'device':str(DEVICE),
 'gpu':torch.cuda.get_device_name(0) if DEVICE==0 else None,
 'versions':{p:importlib.metadata.version(p) for p in ['ultralytics','torch','lap','opencv-python']},
 'preview_file':preview.name,
 'limitations':['No ground-truth annotations: no AP, IDF1 or speed accuracy measured.',
 'Tracker IDs are not verified unique vehicles.',
 'Box bottom centres are provisional contact proxies.',
 'No metric scale or road-plane calibration has been estimated.',
 'Road grade and crest may require separate local planes or a 3D road model.']}
(OUT/'run_report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps(report, indent=2))
if preview.suffix=='.mp4': display(Video(str(preview), embed=True, width=960))

# %% markdown
# Next: inspect tracking continuity and car crops, choose local road regions, then estimate
# camera orientation and metric scale using vehicle geometry. The cited Sochor et al. method
# matches detected boxes to rendered 3D vehicle models; this notebook does not implement that yet.
# https://arxiv.org/abs/1702.06451
