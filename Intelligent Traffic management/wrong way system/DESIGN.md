# Design rationale

## 1. Approaches considered

| approach | how it works | why not (alone) |
|---|---|---|
| Vendor VCA "direction tripwire" (built into most Hikvision/Dahua/Uniview cameras) | draw a line and an allowed direction on each camera | 118 hand-drawn rules, vendor-specific, no awareness of two-way streets, roundabouts or diversions; each vendor has its own false-alarm behaviour |
| Dense or sparse optical flow without detection | compare pixel motion with a reference flow | sensitive to shadows, headlights, rain, IR switching and camera shake; can't tell a vehicle from a pedestrian; no per-vehicle evidence |
| Detector + tracker + **hand-drawn** lane polygons with directions | the classic "safe city" implementation | accurate where drawn, but needs a lot of commissioning, breaks when a camera moves, and is blind to temporary diversions. This is the main source of false alerts in existing deployments |
| Learned trajectory / scene-activity models (trajectory clustering, motion-pattern learning; cf. Morris & Trivedi's survey on trajectory learning for surveillance) | learn normal motion patterns, flag anomalies | full trajectory clustering is heavy and generic ("anomalous" ≠ "wrong way") |
| **Chosen: detector + low-FPS tracker + learned *directional* flow field + evidence judge, with optional zones** | learn, per cell, *which directions are legal* from distinct vehicles; judge each track with accumulated evidence | combines zero-config learning with the per-vehicle precision of tracking; cheap (histogram updates); explainable (you can draw the map); optional zones give certainty where it matters |

Component choices:

* **Detector**: Ultralytics YOLO (YOLO11s by default; YOLO11n for lower compute; any newer Ultralytics detector is a drop-in), COCO vehicle classes, exported to TensorRT FP16 with dynamic batch. COCO already covers car/motorcycle/bus/truck well. Fine-tune on local footage (rickshaws, Suzuki pick-ups, IR night frames) only if the pilot shows misses.
* **Tracker**: ByteTrack (Zhang et al., ECCV 2022) association logic, because low-score boxes keep tracks alive through occlusion and at night. It is extended with a time-aware Kalman filter and a centre-distance stage, because at 5–6 FPS fast vehicles near the camera often have **zero IoU** between processed frames (this failure was found and fixed during simulation). Appearance re-ID (BoT-SORT / DeepOCSORT) was rejected: costly for 118 cameras, and wrong-way logic only needs short-term identity.
* **Ground point**: the bottom-centre of the box, which approximates where the tyres touch the road. Direction is computed in pixel space, so it is unaffected by the image aspect ratio.
* **Scale normalisation**: every distance and speed is in *body sizes* √(w·h). This makes thresholds valid across perspective depth, mounting height, focal length and resolution with no calibration.

## 2. Scenario catalogue (housing society) → how it is handled

| # | scenario | handling |
|---|---|---|
| 1 | Genuine wrong-way on a divided main road (car, motorbike, rickshaw) | carriageway cells `one_way` → evidence → alert with snapshot and clip |
| 2 | Two-way society street, opposing traffic | lateral pooling → `two_way` → never judged |
| 3 | Overtaking or passing parked cars on the "wrong" half of a street | `street` profile pools ~3.5 widths → whole cross-section two-way |
| 4 | Roundabout, clockwise (left-hand traffic) | ring cells learn tangential direction; anticlockwise circulation → alert; auto-discovery reports rotation |
| 5 | Roundabout entries/exits, turning traffic at junctions | cells become `multi`/`two_way` → not judged |
| 6 | Legal U-turn through a median gap | median cells unknown/multi; ratio rule clears evidence once the vehicle joins the other carriageway |
| 7 | Reversing out of a driveway or parking bay | slow relative to the learned typical speed → ignored; short distance < 5 bodies |
| 8 | Brief swerve or drift then correction | ≥ 3 cells, ≥ 1.2 s and ≥ 75 % wrong ratio; correct motion erases evidence 2× faster |
| 9 | Temporary diversion / road works / intentional contraflow (cones, one carriageway closed) | ≥ 3 distinct vehicles at one spot in 10 min **or** ≥ 25 % recent opposite share → contraflow latch → suppressed + operator notified; releases automatically; long-term map protected |
| 10 | Recurring planned contraflow (Friday prayers, school times, events, VIP movement) | scheduled `overrides`, or runtime override via API |
| 11 | Gates, barriers, fuel stations, parking aprons, service lanes | `ignore` zones; otherwise learned as multi/two-way |
| 12 | Camera bumped, re-aimed, PTZ preset change, unit replaced | view guard → archive map → relearn → `camera_view_changed` |
| 13 | Day ↔ night IR switch, headlight glare, rain | edge-based guard with multiple references; detector confidence + ByteTrack low-score association |
| 14 | Different resolutions, vendors, heights, angles | body-size normalisation; per-camera learned vehicle size; resolution-normalised zones |
| 15 | Stream resolution changes after a firmware update | inputs rescaled to the learned map resolution |
| 16 | Tracker ID switch between two crossing vehicles | jump > 3 bodies → evidence reset (learning kept) |
| 17 | Vehicles cut off at the image border | truncated boxes ignored (ground point unreliable) |
| 18 | Parked vehicles, static false detections | no motion → no votes, no evidence |
| 19 | Low-traffic cameras, night time | `min_tracks` per cell before judging; idle 2 FPS + motion gate saves GPU |
| 20 | Permanent rule change (road made two-way or one-way) | `flow_change_persistent` after 24 h → operator relearn (`POST /relearn`) |
| 21 | Learning poisoned by violators | one vote per vehicle; alerted vehicles teach at 0.3 weight; diversion traffic doesn't teach the long-term map |
| 22 | Service restart | maps and view references persisted every 5 min and restored |

## 3. Key parameters (defaults)

| parameter | default | meaning |
|---|---|---|
| `flow.grid_cols` | 48 | grid resolution (rows from aspect ratio) |
| `flow.min_tracks` | 8 | distinct vehicles before a cell is trusted |
| `flow.one_way_frac` | 0.80 | purity for one-way |
| `flow.two_way_min_frac` | 0.06 (main_road 0.15, street 0.03) | opposite share that makes a cell two-way |
| `flow.pool_body_sizes` | 1.5 (main_road 1.2, street 3.5) | lateral tolerance in vehicle widths |
| `flow.min_learning_s` | 1800 | warm-up before learned cells alert |
| `flow.contraflow_*` | 3 vehicles / 25 % / 10 min | diversion recognition |
| `judge.wrong_angle_deg` | 130 | against-flow threshold |
| `judge.min_wrong_path_bodies` | 5 | wrong-way distance |
| `judge.min_wrong_time_s` | 1.2 | wrong-way duration |
| `judge.reverse_speed_ratio` | 0.3 | below this × typical speed = manoeuvre |
| `runtime.process_fps` / `idle_fps` | 6 / 2 | processing rate |

## 4. Code map

```
wrongway/
  config.py       dataclasses, road profiles, YAML loading
  tracker.py      ByteTrack-lite (time-aware Kalman, distance fallback)
  flowmap.py      learned flow field: memories, pooling, classification, contraflow latch
  engine.py       per-camera engine: evidence judge, learning commits, events, overrides
  zones.py        operator zones + scheduled/dated overrides
  roundabout.py   circulation estimate + roundabout discovery
  detector.py     batched Ultralytics/TensorRT backend, export helper
  camera.py       stream readers, motion gate, clip buffer
  scene_guard.py  camera view-change detection
  alerts.py       JSONL, snapshots, clips, webhook (async)
  runner.py       multi-camera loop, HTTP API, offline video processing
  viz.py          flow-map and alert overlays
  sim.py          synthetic perspective scenarios for validation
  cli.py          run | check | offline | simulate | viz | export-model
```
