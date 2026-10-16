"""Sequential, speed-blind measurements for long static CCTV recordings.

Every source frame is decoded; detection and cuboids are sampled independently.
Only cars with recent image movement contribute cuboids. No reference speeds,
Mercedes/Kia learned scales, or expected-speed clipping are used.
"""
import argparse
from collections import defaultdict, deque
import gzip
import hashlib
import json
from pathlib import Path
import time
import urllib.request

import cv2
import numpy as np
from scipy.optimize import linear_sum_assignment
from ultralytics import YOLO

from validation_inference import MODEL_REPO, MODEL_REVISION, MODEL_FILE, MODEL_SHA, overlaps


def region_for(point, profile, width, height):
    for name, polygon in profile['regions'].items():
        contour = np.asarray(polygon, np.float32) * [width, height]
        if cv2.pointPolygonTest(contour.astype(np.float32), tuple(map(float, point)), False) >= 0:
            return name
    return None


def inference(video, output, camera, duration=None, resume_s=0, device='0'):
    config = json.loads((Path(__file__).parent/'cctv_camera_profiles.json').read_text())
    profile = config['cameras'][camera]
    geometry_hz=profile.get('geometry_hz',config['geometry_hz'])
    motion_minimum_span=profile.get('motion_history_minimum_span_s',.4)
    video = Path(video); output = Path(output); output.mkdir(parents=True, exist_ok=True)
    with video.open('rb') as stream:
        source_sha = hashlib.file_digest(stream, 'sha256').hexdigest()
    assert source_sha == profile['sha256'], 'Unexpected source recording'
    cap = cv2.VideoCapture(str(video)); assert cap.isOpened()
    width, height = [int(cap.get(key)) for key in [cv2.CAP_PROP_FRAME_WIDTH, cv2.CAP_PROP_FRAME_HEIGHT]]
    fps = float(cap.get(cv2.CAP_PROP_FPS)); total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    stop_frame = total if duration is None else min(total, int(round(duration*fps)))
    resume_frame = int(round(resume_s*fps))
    models = output.parent/'models'; models.mkdir(exist_ok=True)
    weights = models/'urban_geometry.pt'
    if not weights.exists():
        urllib.request.urlretrieve(f'https://huggingface.co/{MODEL_REPO}/resolve/{MODEL_REVISION}/{MODEL_FILE}', weights)
    with weights.open('rb') as stream:
        assert hashlib.file_digest(stream, 'sha256').hexdigest() == MODEL_SHA
    tracker = YOLO(str(models/'yolo11s.pt'))
    geometry = YOLO(str(weights))
    tracker_config = output/'bytetrack_10fps.yaml'
    tracker_config.write_text('tracker_type: bytetrack\ntrack_high_thresh: 0.25\ntrack_low_thresh: 0.10\nnew_track_thresh: 0.25\ntrack_buffer: 10\nmatch_thresh: 0.80\nfuse_score: True\n')
    track_file = gzip.open(output/'tracks.jsonl.gz', 'wt', encoding='utf-8')
    geom_file = gzip.open(output/'observations.jsonl.gz', 'wt', encoding='utf-8')
    histories = defaultdict(deque)
    counts = defaultdict(int)
    next_detection, next_geometry = resume_frame, resume_s
    start = time.monotonic(); index = 0; previous_pts = -1; timestamp_fallbacks = 0
    checkpoints = [];ground_votes=defaultdict(list)
    try:
        while index < stop_frame:
            ok = cap.grab()
            if not ok:
                break
            pts = float(cap.get(cv2.CAP_PROP_POS_MSEC))/1000
            expected = index/fps
            timestamp = pts if np.isfinite(pts) and pts > previous_pts and abs(pts-expected) < .15 else expected
            timestamp_fallbacks += int(timestamp != pts)
            previous_pts = timestamp
            if index < resume_frame or index + 1e-6 < next_detection:
                index += 1; continue
            ok, frame = cap.retrieve(); assert ok, f'Cannot retrieve frame {index}'
            while next_detection <= index + 1e-6:
                next_detection += fps/config['detection_hz']
            if counts['detection_frames'] == 0:
                cv2.imwrite(str(output/'reference.jpg'), frame)
            detected = tracker.track(frame, persist=True, tracker=str(tracker_config), device=device,
                                     imgsz=1280, classes=[2,3,5,7], conf=.10, half=True, verbose=False)[0]
            boxes = detected.boxes.xyxy.cpu().numpy()
            ids = detected.boxes.id.cpu().numpy().astype(int) if detected.boxes.id is not None else np.full(len(boxes), -1)
            scores = detected.boxes.conf.cpu().numpy(); classes = detected.boxes.cls.cpu().numpy().astype(int)
            # A reset at the resume boundary cannot silently join unrelated track IDs.
            ids = np.where(ids >= 0, ids + (1000000 if resume_frame else 0), -1)
            eligible = []
            for k, (box, tid, score, cls) in enumerate(zip(boxes, ids, scores, classes)):
                if tid < 0:
                    continue
                center = (box[:2] + box[2:])/2
                region = region_for((center[0], box[3]), profile, width, height)
                history = histories[int(tid)]
                history.append((timestamp, center))
                while history and timestamp-history[0][0] > 2.5:
                    history.popleft()
                displacement = float(np.linalg.norm(center-history[0][1]))
                moving = timestamp-history[0][0] >= motion_minimum_span-.001 and displacement >= max(8, .10*(box[3]-box[1]))
                row = dict(frame_index=index, time_s=timestamp, track_id=int(tid), class_id=int(cls),
                           box=box.tolist(), confidence=float(score), region=region, moving=bool(moving))
                track_file.write(json.dumps(row, separators=(',', ':'))+'\n'); counts['track_rows'] += 1
                if cls == 2 and moving and region and box[3]-box[1] >= 40:
                    eligible.append(k)
            counts['detection_frames'] += 1
            if timestamp >= next_geometry:
                next_geometry = timestamp+1/geometry_hz-.01
                if eligible:
                    result = geometry.predict(frame, device=device, imgsz=1920, classes=[0], conf=.15,
                                              half=True, verbose=False)[0]
                    counts['geometry_frames'] += 1
                    if result.keypoints is not None and len(result.boxes):
                        gb = result.boxes.xyxy.cpu().numpy(); gs = result.boxes.conf.cpu().numpy()
                        kp = result.keypoints.data.cpu().numpy()
                        overlap = overlaps(boxes[eligible], gb); ii, jj = linear_sum_assignment(1-overlap)
                        for i,j in zip(ii,jj):
                            if overlap[i,j] < .35:
                                continue
                            k = eligible[i]
                            row = dict(frame_index=index, time_s=timestamp, track_id=int(ids[k]),
                                       baseline_confidence=float(scores[k]), geometry_confidence=float(gs[j]),
                                       association_iou=float(overlap[i,j]), baseline_box=boxes[k].tolist(),
                                       geometry_box=gb[j].tolist(), keypoints=kp[j].tolist())
                            geom_file.write(json.dumps(row, separators=(',', ':'))+'\n'); counts['observations'] += 1
                            ground_votes[int(ids[k])].append(bool(kp[j,:4,1].mean()>kp[j,4:,1].mean()))
                        if len(checkpoints) < 16 and timestamp >= resume_s+len(checkpoints)*60:
                            cv2.imwrite(str(output/f'geometry_{index:06d}.jpg'), result.plot())
                            checkpoints.append(timestamp)
            if counts['detection_frames'] % 600 == 0:
                track_file.flush(); geom_file.flush()
                print(camera, f'{timestamp:.1f}s / {stop_frame/fps:.1f}s', dict(counts),
                      'runtime', round(time.monotonic()-start,1), flush=True)
                # Histories only hold active/recent tracks, rather than an hour of parked IDs.
                stale = [tid for tid,h in histories.items() if h and timestamp-h[-1][0] > 10]
                for tid in stale:
                    del histories[tid]
            if index % int(fps*300) < fps/config['detection_hz']:
                cv2.imwrite(str(output/f'view_{int(timestamp):05d}.jpg'), frame)
            index += 1
    finally:
        cap.release(); track_file.close(); geom_file.close()
    ground_fraction=float(np.mean([np.mean(v)>=.5 for v in ground_votes.values()])) if ground_votes else .5
    ground_indices=list(range(4)) if ground_fraction>=.5 else list(range(4,8))
    report = dict(camera_id=camera, source_video=video.name, source_sha256=source_sha,
                  width=width, height=height, fps=fps, frames_reported=total,
                  frames_decoded=index, expected_decoded_frames=stop_frame,
                  decode_complete=index==stop_frame, start_s=resume_s, stop_s=stop_frame/fps,
                  timestamps='Monotonic container PTS checked against frame/FPS; fallback when inconsistent',
                  timestamp_fallback_frames=timestamp_fallbacks, detection_hz=config['detection_hz'],
                  geometry_hz=geometry_hz, ground_indices=ground_indices,
                  ground_order_vote_agreement=max(ground_fraction,1-ground_fraction),
                  model_sha256=MODEL_SHA, model_revision=MODEL_REVISION, model_file=MODEL_FILE,
                  counts=dict(counts), runtime_s=time.monotonic()-start,
                  known_speeds_used=False, benchmark_vehicle_scales_used=False,
                  id_reset_at_resume_s=resume_s if resume_s else None)
    (output/'inference_report.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    assert report['decode_complete'], f'Source decode ended early: {index}/{stop_frame}'
    print('COMPLETE', camera, dict(counts), round(report['runtime_s'],1), flush=True)


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--video',required=True);p.add_argument('--output',required=True)
    p.add_argument('--camera',required=True);p.add_argument('--duration',type=float)
    p.add_argument('--resume-s',type=float,default=0);p.add_argument('--device',default='0')
    a=p.parse_args();inference(a.video,a.output,a.camera,a.duration,a.resume_s,a.device)
