# Wrong-Way Vehicle Detection: Naval Anchorage (118 cameras)

This is a standalone, production-oriented wrong-way detection service. **Each camera learns its own traffic rules from the traffic it sees.** You do not need calibration, lane drawing or vendor-specific setup to start. It works across mixed resolutions, mounting heights, angles and vendors. It handles divided main roads, two-way society streets, roundabouts (clockwise for left-hand traffic), junctions, temporary diversions, reversing, U-turns, camera moves and night/IR switching.

```
RTSP sub-streams ─► reader threads (latest frame only, auto-reconnect)
                   │
                   ├─► motion gate (skip GPU when nothing moves)      ─┐
                   ├─► pre-event clip buffer, view-change guard        │ thread pool
                   ▼                                                   ┘
        batched YOLO (TensorRT FP16, all cameras in one forward pass)
                   ▼
   per camera:  ByteTrack-lite (time-aware Kalman, low-FPS association)
                   ▼
             self-learned FLOW FIELD  (grid × 16-bin direction histograms,
                   │                   slow 3-day / fast 12-min / recent 3-min memories)
                   ▼
             EVIDENCE JUDGE  (body-size-normalised wrong path, time, cells, ratio)
                   ▼
   events ─► JSONL + annotated snapshot + mp4 clip + webhook  ─► Naval Anchorage AI System
   HTTP API ─► status, live flow-map overlay, overrides, relearn
```

## Quick start

```bash
pip install -r requirements.txt          # install torch for your CUDA first
python -m wrongway export-model --model yolo11s.pt --imgsz 640 --batch 16   # -> yolo11s.engine
python -m wrongway check -c configs/system.yaml
python -m wrongway run   -c configs/system.yaml
# commissioning on a recording: learn on pass 1, report on pass 2, writes annotated.mp4 + flowmap.jpg
python -m wrongway offline recording.mp4 --profile main_road -o out_cam001
python -m wrongway simulate              # synthetic end-to-end validation (no GPU needed)
python scripts/run_tests.py              # or: pytest -q tests
```

You configure a camera with an id and a URL. Everything else is optional (`configs/cameras/*.yaml`):

```yaml
id: cam_001
url: rtsp://user:pass@10.10.1.11:554/Streaming/Channels/102    # use the SUB-stream
road_profile: main_road        # auto | main_road | street | roundabout
zones: [...]                   # optional: one_way / two_way / ignore / roundabout polygons
overrides: [...]               # optional: scheduled or dated suppressions (Friday prayers, events, road works)
```

## How it decides (and why it does not cry wolf)

**1. Learning the road (per camera, automatic).** The image is split into a grid of about 48×27 cells. For every vehicle that passes through, each cell gets **one vote per vehicle** for its direction of travel. Votes go into a 16-bin circular histogram. A busy hour therefore cannot outvote a whole day. Each cell is then classified:

| class | rule | judged? |
|---|---|---|
| `one_way` | ≥ 80 % of vehicles within ±45° of one heading, and no material opposite flow within ~1.5 vehicle widths | **yes** |
| `two_way` | opposite flow exists in the lateral neighbourhood | never |
| `multi` | junction or turning area | never |
| `unknown` | fewer than 8 distinct vehicles, or no own traffic | never |

The neighbourhood radius is measured in **learned vehicle sizes**, not pixels, so the same settings work near and far, at 4 m or 25 m mounting height, and on 2 MP or 8 MP cameras. This is how one set of parameters copes with very different camera geometries:

* **Divided main roads**: the median separates the carriageways, so each one becomes `one_way`.
* **Society streets**: opposite traffic is within a lane or two, so the street becomes `two_way` and you get no alerts. Kerb-hugging and overtaking are tolerated (the `street` profile pools across ~3.5 vehicle widths).
* **Roundabouts**: each cell of the ring learns its local tangential direction. A vehicle circulating the wrong way is therefore opposite to the flow of every ring cell it passes. Entry and exit cells come out `multi` or `two_way` and are not judged. Circular flow is also **auto-discovered** and its rotation is reported (`roundabout_detected`, expected `cw` for left-hand traffic). That gives you a commissioning sanity check. If you draw a roundabout zone, its rotation can be `auto`.

**2. Judging a vehicle (evidence, not a single frame).** The engine follows the ground-contact point (bottom-centre of the box) over ~0.8 s. Every distance is in *body sizes* (√(w·h) of the box). An alert needs **all** of the following:

* travel ≥ 130° against the legal heading,
* ≥ 5 body sizes of wrong-way path, ≥ 1.2 s, across ≥ 3 different cells,
* ≥ 75 % of the recent path in the wrong direction (so a completed U-turn or a quick swerve clears),
* track age ≥ 1.5 s and speed ≥ 0.35 body/s.

Separately, the vehicle must **not be much slower than normal traffic at that spot**: below 30 % of the learned typical speed reads as reversing, parking or a manoeuvre.

Moving with the flow erases evidence twice as fast as wrong-way motion builds it. Truncated boxes at the frame edge are ignored. A sudden jump of more than 3 body sizes between updates is treated as a tracker ID switch: the evidence is reset and the learning is kept.

**3. Adapting to local conditions.**

* **Temporary diversions or intentional contraflow**: if ≥ 3 *different* vehicles are flagged at the same spot within 10 minutes, the area is latched as `contraflow`. The same happens if recent opposite traffic is ≥ 25 % of the flow there. Further vehicles in the area are logged as `suppressed`, not alerted. The operator gets a `contraflow_suspected` event listing the earlier alerts that were probably part of the diversion. When the opposite flow stops, the latch releases (`contraflow_cleared`) and normal alerting resumes automatically. Diversion traffic is **not** written into the long-term map, so the road's real rule is not overwritten. If the opposite flow persists for 24 h, you get a `flow_change_persistent` event that suggests a relearn.
* **Known or recurring exceptions**: use `overrides` with a schedule (e.g. Fri 12:45–14:15) or an `until` date. You can also add one at runtime with `POST /cameras/<id>/override {"minutes":90,"reason":"VIP movement"}`.
* **Camera moved, re-aimed or replaced**: an edge-based phase-correlation guard runs once a minute against day/night reference images. On a confirmed move it **archives the old map and relearns**, and emits `camera_view_changed`. IR switching and headlights do not trigger it.
* **Warm-up**: learned cells cannot alert until 30 minutes of traffic has been observed (`min_learning_s`). Operator `one_way` / `roundabout` zones alert from the first minute. Maps persist across restarts (`state_dir/<cam>.npz`, saved every 5 minutes).

Nothing is dropped silently. Suppressed detections are logged with their reason, so the false-positive and violation picture stays auditable.

## Synthetic validation (included, reproducible)

`python -m wrongway simulate` projects ground-plane traffic through pinhole cameras with different heights, focal lengths and resolutions. It adds detector noise (3 % box jitter, 7 % missed detections, ghost boxes) and runs the full tracker + learning + judge pipeline at 6 FPS:

| scenario | content | result |
|---|---|---|
| `divided_road` | 4 lanes, ~860 vehicles, lane changes; wrong-way car + motorbike; reversing car; legal U-turn via median gap; drift-and-correct | 2/2 detected, 0 false alerts |
| `divided_road_low_cam` | same scene, 4.5 m pole, 720p | 2/2, 0 false |
| `two_way_street` | 7 m street, 70/30 traffic, parked cars forcing the other side, overtaking, kerb swap | 0 false |
| `roundabout` | 4-arm clockwise roundabout, 25 m view; 2 vehicles circulating anticlockwise | 2/2, 0 false, auto-discovered `cw` |
| `diversion` | carriageway closed for 20 min, ~120 vehicles run contraflow; real wrong-way car afterwards | 2 alerts before adaptation, then suppressed; real violator detected after |

Learned flow maps (green = one-way, yellow = two-way, red = alert path, magenta = ground truth wrong-way):
`docs/img/divided_road.png`, `docs/img/two_way_street.png`, `docs/img/roundabout.png`.

> Synthetic results show the logic works end-to-end. They do **not** replace a field pilot (see Commissioning).

## Compute sizing (118 cameras)

* **GPU**: YOLO11s (or YOLO11n / YOLO26 for less compute), 640 px, FP16 TensorRT, batch 16. 118 cams × 6 FPS ≈ 700 img/s at peak. Motion gating and 2 FPS idle mode typically remove 40–80 % of that on quiet society roads and at night. This is feasible on a single RTX 4070/4080/A4000-class GPU. Benchmark your card with `wrongway offline` and the `/status` → `detector.infer_ms` field.
* **CPU**: the engine costs ~0.8 ms per camera-frame (measured). Per-frame pre-processing (motion gate, clip JPEG) runs in a thread pool. **Decoding is the main CPU cost: always use camera sub-streams** (D1/720p). If you want hardware decode, point readers at a GStreamer/NVDEC pipeline. For more headroom, run shards: `--shard 0/2`, `--shard 1/2`.
* **Already running detection + tracking in the Naval Anchorage AI System?** Skip the second detector entirely: set `detector.backend: none` and feed tracks with `engine.update_tracks(...)` (see `examples/integrate_existing_pipeline.py`). The added cost is then ~1 ms per frame on the CPU.

## HTTP API (default :8088)

| method | path | purpose |
|---|---|---|
| GET | `/health`, `/status` | liveness; per-camera online/fps/learning %/contraflow/overrides; detector latency |
| GET | `/cameras/<id>` | engine status incl. learned map summary and discovered roundabout |
| GET | `/cameras/<id>/flowmap.jpg` | live overlay of the learned rules on the current frame (commissioning) |
| GET | `/events` | last 100 events |
| POST | `/cameras/<id>/override` | `{"mode":"suppress","minutes":60,"zone":null,"reason":"..."}` |
| POST | `/cameras/<id>/clear_overrides`, `/relearn`, `/save` | operations |

Event JSON (webhook body) includes `event_id, type, severity (alert|suppressed|info|warning), suppress_reason, camera_id, track_id, time, class, rule (learned|zone:<name>), allowed_deg, travel_deg, angle_diff_deg, wrong_path_bodies, wrong_time_s, speed_bps, bbox, trajectory, snapshot, clip`.

## Commissioning procedure (recommended)

1. Put all 118 cameras on **sub-streams**. Set `road_profile` per camera: `main_road` (divided), `street`, `roundabout`, or leave `auto`.
2. Run live for 1–2 days. Alerts from learned cells start after 30 minutes, but treat day 1 as shadow mode: point the webhook at a test endpoint.
3. For each camera, open `GET /cameras/<id>/flowmap.jpg`. Check that the arrows match the real rule, that two-way streets are yellow, and that roundabouts report `cw`. Fix anything odd with a zone (`ignore` for fuel stations, parking, gates or service lanes; `one_way` for critical stretches).
4. Review `events.jsonl` (alerts **and** suppressed). Tune per camera only if needed: raise `min_wrong_path_bodies` on noisy cameras; lower `two_way_min_frac` on streets with lopsided traffic.
5. Go live. Re-check after any camera maintenance (the view guard relearns automatically and emits an event).

## Known limits / honest notes

* A one-way road where violations are habitually very frequent (more than ~6 %, or 15 % with `main_road`) can be learned as two-way. Draw a `one_way` zone there. Likewise, three violators at one spot within 10 minutes are treated as a diversion and suppressed, though the operator still gets a `contraflow_suspected` event. Set `contraflow_adapt: false` on cameras where you never want that.
* Reversing at normal speed for a long distance looks like wrong-way driving. That is usually correct, but emergency vehicles are not distinguished. Route alerts through operator confirmation.
* Validation here is synthetic (no GPU or recordings were available in the build environment). The detector path follows the documented Ultralytics API but must be smoke-tested on the GPU server. Run `wrongway offline` on recordings from each camera type before go-live.

See `DESIGN.md` for the research rationale and the full catalogue of scenarios.
