"""Stream ingestion, motion gating and pre-event clip buffering.

* StreamReader: one daemon thread per camera that keeps only the LATEST frame
  (no queue build-up when the GPU is busy), reconnects with back-off and
  reports online/offline. RTSP over TCP by default (fewer smeared frames on
  mixed-vendor networks). Tip: point `url` at the camera SUB-stream
  (704x576 / 640x360 / 1280x720) - detection at 640 px gains nothing from 4K.
* MotionGate: 96x54 frame difference; skip the detector when nothing moves
  (quiet society roads at night => large GPU savings).
* ClipBuffer: rolling, JPEG-compressed, downscaled frames for evidence clips.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque

import cv2
import numpy as np

log = logging.getLogger(__name__)
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|stimeout;5000000")


class StreamReader(threading.Thread):
    def __init__(self, cam_id: str, url: str, reconnect_max_s: float = 30.0):
        super().__init__(name=f"reader-{cam_id}", daemon=True)
        self.cam_id, self.url = cam_id, url
        self.reconnect_max_s = reconnect_max_s
        self._lock = threading.Lock()
        self._frame = None
        self._ts = 0.0
        self._seq = 0
        self.online = False
        self.last_ok = 0.0
        self.fps_in = 0.0
        self._halt = threading.Event()

    def latest(self):
        with self._lock:
            return self._frame, self._ts, self._seq

    def stop(self):
        self._halt.set()

    def run(self):
        backoff = 1.0
        while not self._halt.is_set():
            cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
            if not cap.isOpened():
                self.online = False
                log.warning("[%s] cannot open stream, retry in %.0fs", self.cam_id, backoff)
                self._halt.wait(backoff)
                backoff = min(backoff * 2, self.reconnect_max_s)
                continue
            backoff = 1.0
            self.online = True
            n, t0 = 0, time.time()
            while not self._halt.is_set():
                ok = cap.grab()
                if not ok:
                    break
                ok, frame = cap.retrieve()
                if not ok or frame is None:
                    break
                now = time.time()
                with self._lock:
                    self._frame, self._ts, self._seq = frame, now, self._seq + 1
                self.last_ok = now
                n += 1
                if now - t0 >= 5:
                    self.fps_in, n, t0 = n / (now - t0), 0, now
            cap.release()
            self.online = False
            log.warning("[%s] stream dropped, reconnecting", self.cam_id)
            self._halt.wait(1.0)


class MotionGate:
    def __init__(self, thresh: float = 0.002, diff_level: int = 18):
        self.prev = None
        self.thresh = thresh
        self.level = diff_level

    def moving(self, frame: np.ndarray) -> bool:
        g = cv2.cvtColor(cv2.resize(frame, (96, 54), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
        g = cv2.GaussianBlur(g, (3, 3), 0)
        if self.prev is None:
            self.prev = g
            return True
        frac = float((cv2.absdiff(g, self.prev) > self.level).mean())
        self.prev = g
        return frac >= self.thresh


class ClipBuffer:
    def __init__(self, seconds: float = 10.0, width: int = 960, quality: int = 70):
        self.seconds = seconds
        self.width = width
        self.quality = quality
        self.buf: deque = deque()

    def add(self, frame: np.ndarray, ts: float):
        h, w = frame.shape[:2]
        if w > self.width:
            frame = cv2.resize(frame, (self.width, int(h * self.width / w)), interpolation=cv2.INTER_LINEAR)
        ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self.quality])
        if ok:
            self.buf.append((ts, jpg))
        while self.buf and ts - self.buf[0][0] > self.seconds:
            self.buf.popleft()

    def window(self, t0: float, t1: float):
        return [(t, j) for t, j in self.buf if t0 <= t <= t1]


def write_clip(frames, path: str, fps: float = 6.0) -> bool:
    """frames: list of (ts, jpeg-bytes). Writes mp4 (mp4v)."""
    if not frames:
        return False
    imgs = [cv2.imdecode(j, cv2.IMREAD_COLOR) for _, j in frames]
    h, w = imgs[0].shape[:2]
    if len(frames) > 1:
        fps = max(1.0, (len(frames) - 1) / max(frames[-1][0] - frames[0][0], 1e-3))
    vw = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    for im in imgs:
        if im.shape[:2] != (h, w):
            im = cv2.resize(im, (w, h))
        vw.write(im)
    vw.release()
    return True
