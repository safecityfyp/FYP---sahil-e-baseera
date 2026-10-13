"""Multi-camera runtime: readers -> motion gate -> batched GPU detection -> per-camera engines -> alerts.

One process handles a shard of cameras (e.g. 118 cameras on one GPU at 6 FPS
= ~700 detector images/s, well within YOLO11s-FP16-TensorRT on an RTX-class
GPU; motion gating typically removes 40-80% of that at night). For more
cameras/GPUs, start one process per shard: `wrongway run --shard 0/2`.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import cv2
import numpy as np

from .alerts import AlertDispatcher
from .camera import ClipBuffer, MotionGate, StreamReader
from .config import CameraConfig, SystemConfig
from .detector import build_detector
from .engine import WrongWayEngine
from .scene_guard import SceneGuard
from .viz import draw_alert, draw_flow

log = logging.getLogger(__name__)


class CameraContext:
    def __init__(self, cfg: CameraConfig, sys_cfg: SystemConfig, reader=None):
        rt = sys_cfg.runtime
        self.cfg = cfg
        self.rt = rt
        self.engine = WrongWayEngine(cfg.id, sys_cfg, cfg)
        self.reader = reader if reader is not None else StreamReader(cfg.id, cfg.url)
        self.gate = MotionGate(rt.motion_thresh) if rt.motion_gate else None
        self.guard = SceneGuard()
        self.clips = ClipBuffer(rt.clip_pre_s + rt.clip_post_s + 2, rt.clip_width) if rt.clip_buffer else None
        self.last_seq = -1
        self.next_due = 0.0
        self.last_detect = 0.0
        self.last_scene = 0.0
        self.last_save = time.time()
        self.last_frame = None
        self.state_path = os.path.join(rt.state_dir, f"{cfg.id}.npz")
        self.loaded = False
        self.paused_until = 0.0
        self.processed = 0
        self.detected = 0

    def try_load(self, frame_size):
        if self.loaded:
            return
        self.loaded = True
        if os.path.exists(self.state_path):
            try:
                extra = self.engine.load(self.state_path, frame_size)
                self.guard.load_state(extra)
                log.info("[%s] restored flow map (%.0f s learned)", self.cfg.id, self.engine.fm.learned_s)
            except Exception as e:
                log.warning("[%s] could not restore state (%s); learning from scratch", self.cfg.id, e)

    def save(self):
        if self.engine.fm is None:
            return
        os.makedirs(self.rt.state_dir, exist_ok=True)
        self.engine.save(self.state_path, extra=self.guard.state())
        self.last_save = time.time()

    def archive_and_relearn(self, reason: str):
        if os.path.exists(self.state_path):
            shutil.move(self.state_path, self.state_path.replace(".npz", f".{int(time.time())}.{reason}.npz"))
        self.engine.relearn()


class Runner:
    def __init__(self, sys_cfg: SystemConfig, shard: tuple[int, int] = (0, 1), detector=None):
        self.cfg = sys_cfg
        rt = sys_cfg.runtime
        cams = [c for c in sys_cfg.cameras if c.enabled]
        cams = [c for i, c in enumerate(cams) if i % shard[1] == shard[0]]
        self.cams = {c.id: CameraContext(c, sys_cfg) for c in cams}
        self.detector = detector or build_detector(sys_cfg.detector)
        self.alerts = AlertDispatcher(rt.events_dir, rt.webhook_url, rt.webhook_timeout_s)
        self._stop = threading.Event()
        self.t_start = time.time()
        self.loop_stats = {"batches": 0, "images": 0, "infer_ms": 0.0}
        self.pool = ThreadPoolExecutor(max_workers=min(16, (os.cpu_count() or 4)), thread_name_prefix="prep")

    # ------------------------------------------------------------------ loop
    def run(self):
        self.alerts.start()
        for c in self.cams.values():
            c.reader.start()
        api = start_api(self) if self.cfg.runtime.api_port else None
        log.info("running %d cameras", len(self.cams))
        try:
            while not self._stop.is_set():
                if not self.step():
                    time.sleep(0.005)
        finally:
            for c in self.cams.values():
                c.save()
                c.reader.stop()
            if api:
                api.shutdown()

    def stop(self):
        self._stop.set()

    def _prep(self, item):
        """Per-camera pre-processing (OpenCV releases the GIL => runs truly parallel in the pool)."""
        c, frame, ts, active, now = item
        rt = self.cfg.runtime
        if c.clips is not None:
            c.clips.add(frame, ts)
        if now - c.last_scene >= rt.scene_check_interval_s:
            c.last_scene = now
            self._scene_check(c, frame, ts)
        moving = c.gate.moving(frame) if c.gate else True
        return moving or active or now - c.last_detect >= rt.keepalive_detect_s

    def step(self) -> bool:
        rt = self.cfg.runtime
        now = time.time()
        due = []
        for c in self.cams.values():
            if now < c.next_due:
                continue
            frame, ts, seq = c.reader.latest()
            if frame is None or seq == c.last_seq:
                continue
            c.last_seq = seq
            active = c.engine.has_moving_tracks()
            c.next_due = now + 1.0 / (rt.process_fps if active else rt.idle_fps)
            c.last_frame = frame
            c.try_load((frame.shape[1], frame.shape[0]))
            due.append((c, frame, ts, active, now))
        if not due:
            return False
        flags = list(self.pool.map(self._prep, due)) if len(due) > 1 else [self._prep(due[0])]
        to_detect = [(c, f, ts) for (c, f, ts, _, _), d in zip(due, flags) if d]
        gated = [(c, f, ts) for (c, f, ts, _, _), d in zip(due, flags) if not d]
        if to_detect:
            t0 = time.perf_counter()
            dets = self.detector.infer([f for _, f, _ in to_detect])
            dt = (time.perf_counter() - t0) * 1000
            s = self.loop_stats
            s["batches"] += 1
            s["images"] += len(to_detect)
            s["infer_ms"] = 0.95 * s["infer_ms"] + 0.05 * dt if s["batches"] > 1 else dt
            for (c, f, ts), d in zip(to_detect, dets):
                c.last_detect = now
                c.detected += 1
                self._feed(c, f, ts, d)
        for c, f, ts in gated:
            self._feed(c, f, ts, None)
        for c in self.cams.values():
            if now - c.last_save >= rt.save_interval_s:
                c.save()
        return True

    def _feed(self, c: CameraContext, frame, ts, dets):
        c.processed += 1
        evs = c.engine.update(ts, dets, (frame.shape[1], frame.shape[0]))
        if ts < c.paused_until:
            for e in evs:
                if e["type"] == "wrong_way" and e["severity"] == "alert":
                    e["severity"], e["suppress_reason"] = "suppressed", "view_unstable"
        for e in evs:
            self.alerts.submit(e, frame if e["type"] == "wrong_way" else None, c.clips,
                               self.cfg.runtime.clip_pre_s, self.cfg.runtime.clip_post_s)

    def _scene_check(self, c: CameraContext, frame, ts):
        st = c.guard.check(frame)
        if st == "suspect":
            c.paused_until = ts + 2 * self.cfg.runtime.scene_check_interval_s
        elif st == "changed":
            log.warning("[%s] camera view changed: archiving flow map and relearning", c.cfg.id)
            c.archive_and_relearn("view_changed")
            self.alerts.submit({"type": "camera_view_changed", "severity": "warning", "camera_id": c.cfg.id,
                                "ts": ts, "message": "View moved/re-aimed. Flow map archived; relearning. "
                                "Operator zones (if any) may need re-drawing."})

    # ------------------------------------------------------------------ status
    def status(self) -> dict:
        now = time.time()
        cams = {}
        for cid, c in self.cams.items():
            s = c.engine.status()
            s.update({"online": c.reader.online, "fps_in": round(getattr(c.reader, "fps_in", 0.0), 1),
                      "last_frame_age_s": round(now - c.reader.last_ok, 1) if c.reader.last_ok else None,
                      "processed": c.processed, "detected": c.detected,
                      "paused": now < c.paused_until})
            cams[cid] = s
        return {"uptime_s": round(now - self.t_start), "cameras": len(self.cams),
                "online": sum(1 for c in self.cams.values() if c.reader.online),
                "detector": {**self.loop_stats, "infer_ms": round(self.loop_stats["infer_ms"], 1)},
                "camera_status": cams}


# ---------------------------------------------------------------------- HTTP API
def start_api(runner: Runner):
    rt = runner.cfg.runtime

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, obj, code=200):
            b = json.dumps(obj, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def _body(self):
            n = int(self.headers.get("Content-Length", 0) or 0)
            return json.loads(self.rfile.read(n) or b"{}") if n else {}

        def _cam(self, parts):
            c = runner.cams.get(parts[1]) if len(parts) > 1 else None
            if c is None:
                self._json({"error": "unknown camera"}, 404)
            return c

        def do_GET(self):
            p = [x for x in urlparse(self.path).path.split("/") if x]
            if p == ["health"]:
                return self._json({"ok": True, "cameras": len(runner.cams)})
            if p == ["status"]:
                return self._json(runner.status())
            if p == ["events"]:
                return self._json(list(runner.alerts.recent)[-100:])
            if len(p) == 3 and p[0] == "cameras" and p[2] == "flowmap.jpg":
                c = self._cam(p)
                if c is None:
                    return
                img = draw_flow(c.last_frame, c.engine)
                ok, jpg = cv2.imencode(".jpg", img)
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.end_headers()
                self.wfile.write(jpg.tobytes())
                return
            if len(p) == 2 and p[0] == "cameras":
                c = self._cam(p)
                if c is not None:
                    self._json(c.engine.status())
                return
            self._json({"error": "not found"}, 404)

        def do_POST(self):
            p = [x for x in urlparse(self.path).path.split("/") if x]
            if len(p) == 3 and p[0] == "cameras":
                c = self._cam(p)
                if c is None:
                    return
                b = self._body()
                if p[2] == "override":       # {"mode":"suppress","minutes":90,"zone":null,"reason":"road works"}
                    o = c.engine.add_runtime_override(b.get("mode", "suppress"), float(b.get("minutes", 60)),
                                                      b.get("zone"), b.get("reason", "operator"))
                    return self._json({"ok": True, "until": o.until})
                if p[2] == "clear_overrides":
                    c.engine.clear_runtime_overrides()
                    return self._json({"ok": True})
                if p[2] == "relearn":
                    c.archive_and_relearn("operator")
                    return self._json({"ok": True})
                if p[2] == "save":
                    c.save()
                    return self._json({"ok": True})
            self._json({"error": "not found"}, 404)

    srv = ThreadingHTTPServer((rt.api_host, rt.api_port), H)
    threading.Thread(target=srv.serve_forever, name="api", daemon=True).start()
    log.info("API on http://%s:%d", rt.api_host, rt.api_port)
    return srv


# ---------------------------------------------------------------------- offline video
def process_video(path: str, sys_cfg: SystemConfig, cam_cfg: CameraConfig, out_dir: str, passes: int = 1,
                  learn_only_first: bool = True, write_video: bool = True, max_seconds: float | None = None,
                  detector=None, state_in: str | None = None) -> dict:
    """Run one camera on a recorded video (commissioning / tuning / validation).

    With passes=2 the first pass only learns the flow (alerts ignored), the
    second pass reports events - emulating a camera that has been running for a while.
    """
    os.makedirs(out_dir, exist_ok=True)
    det = detector or build_detector(sys_cfg.detector)
    eng = WrongWayEngine(cam_cfg.id, sys_cfg, cam_cfg)
    rt = sys_cfg.runtime
    all_events = []
    base = time.time()
    for pi in range(passes):
        cap = cv2.VideoCapture(path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        step = max(1, int(round(fps / rt.process_fps)))
        k = 0
        vw = None
        report = pi == passes - 1 or not learn_only_first
        if state_in and pi == 0 and os.path.exists(state_in):
            ok, fr = cap.read()
            if ok:
                eng.load(state_in, (fr.shape[1], fr.shape[0]))
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        if pi < passes - 1 and learn_only_first:
            eng.fcfg.min_learning_s = 0.0
        while True:
            ok = cap.grab()
            if not ok:
                break
            if k % step:
                k += 1
                continue
            ok, frame = cap.retrieve()
            if not ok:
                break
            ts = base + pi * 10 ** 6 + k / fps
            if max_seconds and k / fps > max_seconds:
                break
            d = det.infer([frame])[0]
            evs = eng.update(ts, d, (frame.shape[1], frame.shape[0]))
            if report:
                for e in evs:
                    e["video_time_s"] = round(k / fps, 2)
                    all_events.append(e)
                    if e["type"] == "wrong_way":
                        cv2.imwrite(os.path.join(out_dir, f"{e['severity']}_{e['track_id']}_{k}.jpg"),
                                    draw_alert(frame, e))
                if write_video:
                    if vw is None:
                        vw = cv2.VideoWriter(os.path.join(out_dir, "annotated.mp4"),
                                             cv2.VideoWriter_fourcc(*"mp4v"), fps / step,
                                             (frame.shape[1], frame.shape[0]))
                    vis = draw_flow(frame, eng, alpha=0.5)
                    for t in eng.tracker.tracks:
                        if t.confirmed and t.updated:
                            x1, y1, x2, y2 = t.bbox.astype(int)
                            col = (0, 0, 255) if eng.states.get(t.id) and eng.states[t.id].alerted_t else (255, 255, 0)
                            cv2.rectangle(vis, (x1, y1), (x2, y2), col, 2)
                            cv2.putText(vis, str(t.id), (x1, y1 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 1)
                    vw.write(vis)
            k += 1
        cap.release()
        if vw is not None:
            vw.release()
        eng.fcfg.min_learning_s = sys_cfg.camera_flow(cam_cfg).min_learning_s
    eng.save(os.path.join(out_dir, f"{cam_cfg.id}.npz"))
    cv2.imwrite(os.path.join(out_dir, "flowmap.jpg"), draw_flow(None, eng))
    with open(os.path.join(out_dir, "events.json"), "w") as f:
        json.dump([{k: v for k, v in e.items() if k != "trajectory"} for e in all_events], f, indent=1, default=str)
    return {"events": all_events, "status": eng.status()}
