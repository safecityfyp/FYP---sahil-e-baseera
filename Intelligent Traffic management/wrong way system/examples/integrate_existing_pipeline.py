"""Plug the wrong-way engine into an EXISTING detection/tracking pipeline
(e.g. the Naval Anchorage AI System already runs YOLO + a tracker per camera).
No second detector => near-zero extra GPU cost.
"""
import time

from wrongway import SystemConfig, CameraConfig, WrongWayEngine

cfg = SystemConfig()                                  # or load_system_config("configs/system.yaml")
engines = {}                                          # camera_id -> engine


def on_tracks(camera_id: str, frame_w: int, frame_h: int, tracks, ts: float | None = None):
    """Call once per processed frame. tracks: iterable of (track_id, (x1,y1,x2,y2), coco_cls, score)."""
    eng = engines.get(camera_id)
    if eng is None:
        cam = next((c for c in cfg.cameras if c.id == camera_id), CameraConfig(id=camera_id))
        eng = engines[camera_id] = WrongWayEngine(camera_id, cfg, cam)
    for ev in eng.update_tracks(ts or time.time(), tracks, (frame_w, frame_h)):
        if ev["type"] == "wrong_way" and ev["severity"] == "alert":
            print("WRONG WAY", ev["camera_id"], ev["class"], ev["track_id"], ev["time"])
        # forward every event (incl. suppressed / contraflow / view-changed) to your event bus


def on_detections(camera_id, frame_w, frame_h, dets_xyxy_score_cls, ts=None):
    """Alternative: raw detections (N,6); the engine runs its own ByteTrack."""
    eng = engines.setdefault(camera_id, WrongWayEngine(camera_id, cfg, CameraConfig(id=camera_id)))
    return eng.update(ts or time.time(), dets_xyxy_score_cls, (frame_w, frame_h))
