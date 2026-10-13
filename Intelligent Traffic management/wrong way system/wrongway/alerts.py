"""Event dispatch: JSONL log, evidence snapshot + clip, webhook to the Naval Anchorage AI System.

All I/O happens on a background thread so inference never blocks on disk or network.
Nothing is dropped silently: suppressed wrong-way events are logged too (severity
"suppressed" + reason) so operators can audit diversions / overrides later.
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import queue
import threading
import time
import urllib.request
from collections import deque

import cv2
import numpy as np

from .camera import write_clip
from .viz import draw_alert

log = logging.getLogger(__name__)


def _jsonable(o):
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(type(o))


class AlertDispatcher(threading.Thread):
    def __init__(self, events_dir: str, webhook_url: str | None = None, webhook_timeout_s: float = 3.0,
                 webhook_min_severity: tuple = ("alert", "warning", "info")):
        super().__init__(name="alert-dispatcher", daemon=True)
        self.dir = events_dir
        os.makedirs(self.dir, exist_ok=True)
        self.webhook = webhook_url
        self.timeout = webhook_timeout_s
        self.send_sev = set(webhook_min_severity)
        self.q: queue.Queue = queue.Queue(maxsize=5000)
        self.recent = deque(maxlen=500)
        self.pending_clips: list = []     # (due_ts, event, clipbuffer, pre, post)

    # called from the inference loop ------------------------------------
    def submit(self, ev: dict, frame: np.ndarray | None = None, clipbuf=None, pre_s=6.0, post_s=4.0):
        ev = dict(ev)
        ev.pop("_gt", None)
        ev["event_id"] = f"{ev['camera_id']}-{int(ev['ts'] * 1000)}-{ev.get('track_id', 0)}"
        try:
            self.q.put_nowait((ev, frame, clipbuf, pre_s, post_s))
        except queue.Full:
            log.error("alert queue full, dropping %s", ev["event_id"])

    # background ---------------------------------------------------------
    def run(self):
        while True:
            try:
                item = self.q.get(timeout=0.5)
            except queue.Empty:
                item = None
            if item is not None:
                try:
                    self._process(*item)
                except Exception:  # never kill the dispatcher
                    log.exception("alert handling failed")
            self._flush_clips()

    def _day_dir(self, ts):
        d = os.path.join(self.dir, _dt.datetime.fromtimestamp(ts).strftime("%Y%m%d"))
        os.makedirs(d, exist_ok=True)
        return d

    def _process(self, ev, frame, clipbuf, pre_s, post_s):
        d = self._day_dir(ev["ts"])
        if ev["type"] == "wrong_way" and frame is not None:
            snap = os.path.join(d, ev["event_id"] + ".jpg")
            cv2.imwrite(snap, draw_alert(frame, ev), [cv2.IMWRITE_JPEG_QUALITY, 85])
            ev["snapshot"] = snap
            if clipbuf is not None:
                ev["clip"] = os.path.join(d, ev["event_id"] + ".mp4")
                self.pending_clips.append((ev["ts"] + post_s, ev, clipbuf, pre_s, post_s))
        with open(os.path.join(d, "events.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(ev, default=_jsonable) + "\n")
        self.recent.append(ev)
        if self.webhook and ev.get("severity") in self.send_sev:
            self._post(ev)
        lvl = logging.WARNING if ev.get("severity") == "alert" else logging.INFO
        log.log(lvl, "EVENT %s %s %s %s", ev["type"], ev.get("severity"), ev["camera_id"],
                ev.get("suppress_reason") or ev.get("message", ""))

    def _flush_clips(self):
        now = time.time()
        keep = []
        for due, ev, cb, pre, post in self.pending_clips:
            if now < due:
                keep.append((due, ev, cb, pre, post))
                continue
            try:
                write_clip(cb.window(ev["ts"] - pre, ev["ts"] + post), ev["clip"])
            except Exception:
                log.exception("clip write failed")
        self.pending_clips = keep

    def _post(self, ev, retries=2):
        body = json.dumps(ev, default=_jsonable).encode()
        for i in range(retries + 1):
            try:
                req = urllib.request.Request(self.webhook, data=body, headers={"Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=self.timeout).read()
                return
            except Exception as e:
                if i == retries:
                    log.error("webhook failed for %s: %s", ev["event_id"], e)
                time.sleep(0.5 * (i + 1))
