"""Per-camera wrong-way engine: tracker + self-learned flow field + evidence judge.

Pure logic, no I/O. Feed it detections (or tracks from an existing tracker in
the Naval Anchorage AI System) and it returns event dicts.

    eng = WrongWayEngine("cam_017", sys_cfg, cam_cfg)
    events = eng.update(ts, dets, (W, H))          # dets: (N,6) x1,y1,x2,y2,score,cls
    events = eng.update_tracks(ts, [(tid, xyxy, cls, score), ...], (W, H))

Decision logic per confirmed track (all distances in *body sizes* =
sqrt(bbox w*h), so it is resolution, camera-height and zoom independent):

  1. direction of travel = displacement of the bbox ground point over ~0.8 s
  2. legal direction at that point: operator zone > learned ONE_WAY cell;
     TWO_WAY / MULTI / UNKNOWN / ignore => no judgement (never an alert)
  3. moving >=130 deg against legal direction adds wrong path; moving within
     70 deg removes evidence (U-turn completed, lane re-entry, jitter)
  4. alert only if: wrong path >= 5 bodies, >= 1.2 s, >= 3 distinct cells,
     >= 75% of recent path wrong, track age >= 1.5 s, speed >= 0.35 body/s and
     not much slower than the typical speed there (reversing / parking).
"""
from __future__ import annotations

import datetime as _dt
import math
import os
import time
from collections import deque
from typing import Iterable, Optional

import numpy as np

from .config import CameraConfig, SystemConfig
from .flowmap import FlowMap, ONE_WAY, KIND_NAMES
from .geometry import angdiff
from .roundabout import circulation, discover
from .tracker import ByteTracker
from .zones import Override, parse_overrides, parse_zones, zone_at


class _TrackState:
    __slots__ = ("id", "cls", "t_first", "t_seen", "hist", "last_eval", "wrong_path", "wrong_time",
                 "wrong_cells", "steps", "alerted_t", "alerts", "acc", "last_commit", "max_delta", "last_info",
                 "r_voted")

    def __init__(self, tid, ts):
        self.id = tid
        self.cls = -1
        self.t_first = ts
        self.t_seen = ts
        self.hist = deque(maxlen=48)       # (t, x, y, size)
        self.last_eval = None              # (t, x, y)
        self.wrong_path = 0.0
        self.wrong_time = 0.0
        self.wrong_cells = set()
        self.steps = deque(maxlen=12)      # signed path per step: +wrong, -correct
        self.alerted_t = None
        self.alerts = 0
        self.acc = {}                      # cell -> [dx, dy, path_px, size_sum, spd_sum, n]
        self.last_commit = ts
        self.max_delta = 0.0
        self.last_info = None
        self.r_voted = set()

    def reset_evidence(self):
        self.wrong_path = 0.0
        self.wrong_time = 0.0
        self.wrong_cells.clear()
        self.steps.clear()


class WrongWayEngine:
    def __init__(self, camera_id: str, sys_cfg: SystemConfig | None = None, cam_cfg: CameraConfig | None = None):
        sys_cfg = sys_cfg or SystemConfig()
        cam_cfg = cam_cfg or CameraConfig(id=camera_id)
        self.camera_id = camera_id
        self.fcfg = sys_cfg.camera_flow(cam_cfg)
        self.jcfg = sys_cfg.camera_judge(cam_cfg)
        self.class_names = dict(sys_cfg.detector.classes)
        self.default_rotation = "cw" if sys_cfg.runtime.traffic_side == "left" else "ccw"
        self.tracker = ByteTracker(sys_cfg.tracker)
        self.zones = parse_zones(cam_cfg.zones)
        self.overrides: list[Override] = parse_overrides(cam_cfg.overrides)
        self.runtime_overrides: list[Override] = []
        self.fm: Optional[FlowMap] = None
        self.frame_size = None
        self.states: dict[int, _TrackState] = {}
        self.t_last: Optional[float] = None
        self.recent_alerts = deque(maxlen=200)    # (ts, track_id, (r, c))
        self.recent_triggers = deque(maxlen=500)  # (ts, track_id, frozenset(cells)) learned-rule triggers
        self._cf_active = False
        self._persist_reported = False
        self._t_round = -1e18
        self.discovered_roundabout = None
        self.stats = {"frames": 0, "alerts": 0, "suppressed": 0, "tracks": 0}

    # ------------------------------------------------------------- setup
    def _ensure_map(self, frame_size):
        W, H = int(frame_size[0]), int(frame_size[1])
        if self.fm is None:
            self.fm = FlowMap(self.fcfg, W, H)
            self.frame_size = (W, H)
        elif (W, H) != self.frame_size:
            # stream resolution changed (e.g. vendor firmware / substream switch): rescale input
            pass

    def _scale(self, frame_size):
        if self.frame_size is None or tuple(frame_size) == self.frame_size:
            return 1.0, 1.0
        return self.frame_size[0] / frame_size[0], self.frame_size[1] / frame_size[1]

    # ------------------------------------------------------------- public API
    def update(self, ts: float, dets, frame_size) -> list[dict]:
        """Detections path (internal ByteTrack). dets: (N,6) or None (motion-gated frame)."""
        self._ensure_map(frame_size)
        sx, sy = self._scale(frame_size)
        d = np.zeros((0, 6)) if dets is None or len(dets) == 0 else np.asarray(dets, float).copy()
        if len(d):
            d = d[np.isin(d[:, 5].astype(int), list(self.class_names))] if self.class_names else d
            d[:, [0, 2]] *= sx
            d[:, [1, 3]] *= sy
        tracks = self.tracker.update(d, ts)
        items = [(t.id, t.bbox, t.cls, t.score) for t in tracks if t.confirmed and t.updated]
        alive = {t.id for t in tracks}
        return self._step(ts, items, alive)

    def update_tracks(self, ts: float, tracks: Iterable, frame_size) -> list[dict]:
        """External-tracker path: tracks = iterable of (track_id, xyxy, cls, score)."""
        self._ensure_map(frame_size)
        sx, sy = self._scale(frame_size)
        items = []
        for tid, b, c, s in tracks:
            b = np.asarray(b, float) * np.array([sx, sy, sx, sy])
            items.append((tid, b, int(c), float(s)))
        alive = {i[0] for i in items} | {k for k, st in self.states.items() if ts - st.t_seen < 2.0}
        return self._step(ts, items, alive)

    def has_moving_tracks(self) -> bool:
        return any(st.last_info and st.last_info.get("speed", 0) >= self.jcfg.min_speed_bps
                   for st in self.states.values())

    # ------------------------------------------------------------- core step
    def _step(self, ts, items, alive_ids) -> list[dict]:
        events: list[dict] = []
        fm = self.fm
        if self.t_last is not None:
            fm.learned_s += min(max(ts - self.t_last, 0.0), 1.0)
        self.t_last = ts
        self.stats["frames"] += 1
        if fm.analysis is None or ts - fm.analysis.t >= self.fcfg.analysis_interval_s:
            fm.analyze(ts)
            events += self._after_analysis(ts)

        for tid, bbox, cls, score in items:
            st = self.states.get(tid)
            if st is None:
                st = self.states[tid] = _TrackState(tid, ts)
                self.stats["tracks"] += 1
            st.t_seen = ts
            st.cls = cls
            ev = self._observe(st, ts, bbox)
            if ev:
                events.append(ev)
            if ts - st.last_commit >= self.fcfg.commit_interval_s:
                self._commit(st, ts)

        for tid in [k for k in self.states if k not in alive_ids]:
            self._commit(self.states.pop(tid), ts)
        return events

    def _observe(self, st: _TrackState, ts, bbox) -> Optional[dict]:
        jc, fm = self.jcfg, self.fm
        W, H = fm.frame_w, fm.frame_h
        x1, y1, x2, y2 = [float(v) for v in bbox]
        m = jc.border_margin
        if x1 < m * W or x2 > (1 - m) * W or y2 > (1 - m) * H or y1 < m * H:
            st.hist.clear()           # truncated box: ground point unreliable
            st.last_eval = None
            return None
        x, y = (x1 + x2) / 2.0, y2          # ground contact point
        size = math.sqrt(max((x2 - x1) * (y2 - y1), 1.0))
        if st.hist:
            t0, x0, y0, s0 = st.hist[-1]
            if math.hypot(x - x0, y - y0) / ((size + s0) / 2) > jc.max_jump_bodies * max(1.0, (ts - t0) / 0.5):
                self._commit(st, ts)        # probable ID switch: keep what was learned, drop evidence
                st.reset_evidence()
                st.hist.clear()
                st.last_eval = None
        st.hist.append((ts, x, y, size))

        ref = None
        for h in st.hist:
            if h[0] <= ts - jc.eval_window_s:
                ref = h
            else:
                break
        if ref is None:
            return None
        tr, xr, yr, sr = ref
        body = (size + sr) / 2.0
        dx, dy, dtw = x - xr, y - yr, ts - tr
        speed = math.hypot(dx, dy) / body / max(dtw, 1e-3)
        theta = math.atan2(dy, dx)
        le = st.last_eval or (tr, xr, yr)
        st.last_eval = (ts, x, y)
        sdx, sdy = x - le[1], y - le[2]
        seg = math.hypot(sdx, sdy) / body
        dstep = max(ts - le[0], 0.0)
        cells = fm.cells_on_segment(le[1], le[2], x, y)
        if speed >= 0.5 * jc.min_speed_bps and cells:
            k = 1.0 / len(cells)
            for rc in cells:
                a = st.acc.setdefault(rc, [0.0, 0.0, 0.0, 0.0, 0.0, 0])
                a[0] += sdx * k
                a[1] += sdy * k
                a[2] += math.hypot(sdx, sdy) * k
                a[3] += size
                a[4] += speed
                a[5] += 1
        cell = fm.cell_of(x, y)
        allowed, source, zone = self._rule(x, y, cell)
        st.last_info = {"speed": speed, "theta": theta, "allowed": allowed, "source": source}
        if allowed is None or cell is None or speed < jc.min_speed_bps:
            return None
        an = fm.analysis
        typ = an.speed[cell] if an is not None else float("nan")
        if source == "learned" and np.isfinite(typ) and speed < jc.reverse_speed_ratio * typ:
            return None          # far slower than normal traffic here: reversing / manoeuvring
        delta = angdiff(theta, allowed)
        if delta >= math.radians(jc.wrong_angle_deg):
            st.wrong_path += seg
            st.wrong_time += dstep
            st.wrong_cells.add(cell)
            st.steps.append(seg)
            st.max_delta = max(st.max_delta, delta)
        elif delta <= math.radians(jc.ok_angle_deg):
            st.steps.append(-seg)
            st.wrong_path = max(0.0, st.wrong_path - 2.0 * seg)
            if st.wrong_path == 0.0:
                st.reset_evidence()
            return None
        else:
            return None

        wrong = sum(s for s in st.steps if s > 0)
        tot = sum(abs(s) for s in st.steps) or 1e-9
        ratio = wrong / tot
        if (st.wrong_path >= jc.min_wrong_path_bodies and st.wrong_time >= jc.min_wrong_time_s
                and len(st.wrong_cells) >= jc.min_wrong_cells and ratio >= jc.min_wrong_ratio
                and ts - st.t_first >= jc.min_track_age_s
                and (st.alerted_t is None or ts - st.alerted_t >= jc.realert_after_s)):
            if source == "learned":
                # count this vehicle in recent memory right away (don't wait for it to leave the view),
                # so a diversion is recognised after the first few vehicles, then refresh the analysis.
                for rc in st.wrong_cells - st.r_voted:
                    fm.vote(rc[0], rc[1], theta, w_slow=0.0, w_fast=0.0, w_recent=1.0)
                st.r_voted |= st.wrong_cells
                self._contraflow_trigger(st, ts)
                fm.analyze(ts)
            return self._make_event(st, ts, bbox, theta, allowed, delta, speed, ratio, source, zone, cell)
        return None

    def _contraflow_trigger(self, st: _TrackState, ts: float):
        """Distinct-vehicle onset test: >= N different vehicles flagged at the same spot within the
        window => treat as diversion right away (latched in the flow map, released by recent memory)."""
        cfg = self.fcfg
        win = cfg.contraflow_window_min * 60.0
        mine = frozenset(st.wrong_cells)
        while self.recent_triggers and ts - self.recent_triggers[0][0] > win:
            self.recent_triggers.popleft()

        def near(a, b):
            return any(abs(r1 - r2) <= 2 and abs(c1 - c2) <= 2 for r1, c1 in a for r2, c2 in b)

        hits = [tr for tr in self.recent_triggers if tr[1] != st.id and near(tr[2], mine)]
        self.recent_triggers.append((ts, st.id, mine))
        if len({tr[1] for tr in hits}) + 1 >= cfg.contraflow_min_tracks:
            an = self.fm.analysis
            for cells in [mine] + [tr[2] for tr in hits]:
                for r, c in cells:
                    if an is None or an.kind[r, c] == ONE_WAY:
                        self.fm.cf_latch[r, c] = True

    def _rule(self, x, y, cell):
        """(allowed_angle | None, source, zone)."""
        W, H = self.fm.frame_w, self.fm.frame_h
        z = zone_at(self.zones, x / W, y / H) if self.zones else None
        if z is not None:
            if z.type in ("ignore", "two_way"):
                return None, z.type, z
            return z.allowed_angle(x, y, W, H, self.default_rotation), f"zone:{z.name}", z
        an = self.fm.analysis
        if cell is None or an is None or self.fm.learned_s < self.fcfg.min_learning_s:
            return None, "learning", None
        if an.kind[cell] == ONE_WAY:
            return float(an.direction[cell]), "learned", None
        return None, KIND_NAMES[int(an.kind[cell])], None

    def _suppression(self, ts, zone, cell) -> Optional[str]:
        for o in self.overrides + self.runtime_overrides:
            if o.active(ts) and (o.zone is None or (zone is not None and o.zone == zone.name)):
                return f"override:{o.mode}" + (f"({o.reason})" if o.reason else "")
        an = self.fm.analysis
        if self.fcfg.contraflow_adapt and an is not None and cell is not None and an.contraflow[cell]:
            return "contraflow_adaptation"
        return None

    def _make_event(self, st, ts, bbox, theta, allowed, delta, speed, ratio, source, zone, cell):
        st.alerted_t = ts
        st.alerts += 1
        sup = self._suppression(ts, zone, cell)
        sev = "suppressed" if sup else "alert"
        self.stats["alerts" if sev == "alert" else "suppressed"] += 1
        self.recent_alerts.append((ts, st.id, cell))
        W, H = self.fm.frame_w, self.fm.frame_h
        return {
            "type": "wrong_way",
            "severity": sev,
            "suppress_reason": sup,
            "camera_id": self.camera_id,
            "track_id": int(st.id),
            "ts": ts,
            "time": _dt.datetime.fromtimestamp(ts).isoformat(timespec="seconds"),
            "class": self.class_names.get(st.cls, str(st.cls)),
            "rule": source,
            "allowed_deg": round(math.degrees(allowed), 1),
            "travel_deg": round(math.degrees(theta), 1),
            "angle_diff_deg": round(math.degrees(delta), 1),
            "wrong_path_bodies": round(st.wrong_path, 2),
            "wrong_time_s": round(st.wrong_time, 2),
            "wrong_ratio": round(ratio, 2),
            "speed_bps": round(speed, 2),
            "repeat": st.alerts,
            "bbox": [round(float(v), 1) for v in bbox],
            "position_norm": [round(((bbox[0] + bbox[2]) / 2) / W, 4), round(bbox[3] / H, 4)],
            "trajectory": [[round(h[1], 1), round(h[2], 1)] for h in list(st.hist)[-30:]],
            "frame_size": [W, H],
        }

    # ------------------------------------------------------------- learning
    def _commit(self, st: _TrackState, ts):
        fm = self.fm
        an = fm.analysis
        w_slow_base = self.fcfg.alerted_vote_weight if st.alerted_t is not None else 1.0
        for (r, c), a in st.acc.items():
            dx, dy, path, ssum, vsum, n = a
            if n == 0:
                continue
            size = ssum / n
            if path < min(0.3 * size, 0.5 * min(fm.cell_w, fm.cell_h)):   # too little motion in this cell
                continue
            if math.hypot(dx, dy) / max(path, 1e-6) < 0.6:   # incoherent motion inside the cell
                continue
            theta = math.atan2(dy, dx)
            w_slow = w_slow_base
            if (an is not None and an.contraflow[r, c]
                    and angdiff(theta, float(an.direction[r, c])) > math.pi / 2):
                w_slow = 0.0                                   # diversion traffic: don't rewrite the road
            fm.vote(r, c, theta, w_slow=w_slow, w_fast=1.0, w_recent=0.0 if (r, c) in st.r_voted else 1.0)
            if w_slow > 0:
                fm.observe(r, c, size, vsum / n)
        st.acc.clear()
        st.last_commit = ts

    def _after_analysis(self, ts) -> list[dict]:
        events = []
        fm, an = self.fm, self.fm.analysis
        cf = an.contraflow
        if cf.any() and not self._cf_active:
            self._cf_active = True
            rr, cc = np.nonzero(cf)
            region = [round(float(cc.min() / fm.cols), 3), round(float(rr.min() / fm.rows), 3),
                      round(float((cc.max() + 1) / fm.cols), 3), round(float((rr.max() + 1) / fm.rows), 3)]
            cfset = set(zip(rr.tolist(), cc.tolist()))
            related = [tid for (t, tid, cell) in self.recent_alerts if ts - t < 1800 and cell in cfset]
            events.append({"type": "contraflow_suspected", "severity": "info", "camera_id": self.camera_id,
                           "ts": ts, "time": _dt.datetime.fromtimestamp(ts).isoformat(timespec="seconds"),
                           "region_norm": region, "cells": int(cf.sum()),
                           "adapting": bool(self.fcfg.contraflow_adapt), "related_alert_track_ids": related,
                           "message": "Several vehicles recently used this one-way area in the opposite "
                                      "direction (diversion / blockage / habitual violation). "
                                      + ("Alerts here are suppressed until normal flow resumes."
                                         if self.fcfg.contraflow_adapt else "Alerts continue (adaptation off).")})
        elif not cf.any() and self._cf_active:
            self._cf_active = False
            self._persist_reported = False
            events.append({"type": "contraflow_cleared", "severity": "info", "camera_id": self.camera_id,
                           "ts": ts, "time": _dt.datetime.fromtimestamp(ts).isoformat(timespec="seconds")})
        if self._cf_active and not self._persist_reported:
            since = np.nanmin(fm.contraflow_since) if np.isfinite(fm.contraflow_since).any() else ts
            if ts - since >= self.fcfg.persistent_change_h * 3600:
                self._persist_reported = True
                events.append({"type": "flow_change_persistent", "severity": "warning", "camera_id": self.camera_id,
                               "ts": ts, "message": "Opposite flow has persisted for "
                               f"{self.fcfg.persistent_change_h:.0f} h. If the road rule changed, relearn this camera."})
        if ts - self._t_round >= 600 and fm.learned_s >= self.fcfg.min_learning_s:
            self._t_round = ts
            for z in self.zones:
                if z.type == "roundabout" and z.center:
                    r = min(fm.frame_w, fm.frame_h)
                    rot, coh, n = circulation(fm, an, z.center[0] * fm.frame_w, z.center[1] * fm.frame_h,
                                              0.05 * r, 0.6 * r)
                    if rot and coh > 0.7:
                        z.learned_rotation = rot
                        if z.rotation in ("cw", "ccw") and rot != z.rotation:
                            events.append({"type": "config_warning", "severity": "warning",
                                           "camera_id": self.camera_id, "ts": ts,
                                           "message": f"roundabout zone {z.name}: configured {z.rotation} but "
                                                      f"traffic circulates {rot}. Check the zone."})
            found = discover(fm, an)
            if found and (self.discovered_roundabout is None
                          or found["rotation"] != self.discovered_roundabout["rotation"]):
                self.discovered_roundabout = found
                events.append({"type": "roundabout_detected", "severity": "info", "camera_id": self.camera_id,
                               "ts": ts, **{k: v for k, v in found.items() if k != "score"},
                               "expected_rotation": self.default_rotation})
        return events

    # ------------------------------------------------------------- operations
    def add_runtime_override(self, mode="suppress", minutes=60.0, zone=None, reason="operator"):
        o = Override(mode=mode, zone=zone, until=time.time() + minutes * 60.0, reason=reason)
        self.runtime_overrides.append(o)
        return o

    def clear_runtime_overrides(self):
        self.runtime_overrides.clear()

    def relearn(self):
        if self.fm is not None:
            self.fm.reset()
        self.tracker.reset()
        self.states.clear()
        self._cf_active = False
        self.discovered_roundabout = None

    def save(self, path: str, extra: dict | None = None):
        if self.fm is None:
            return
        tmp = path + ".tmp.npz"
        self.fm.save(tmp, extra)
        os.replace(tmp, path)

    def load(self, path: str, frame_size) -> dict:
        self._ensure_map(frame_size)
        return self.fm.load(path)

    def status(self) -> dict:
        s = {"camera_id": self.camera_id, **self.stats, "active_tracks": len(self.states),
             "zones": [z.name for z in self.zones], "contraflow_active": self._cf_active,
             "runtime_overrides": len([o for o in self.runtime_overrides if o.active(time.time())])}
        if self.fm is not None:
            s["learned_s"] = round(self.fm.learned_s, 1)
            s["learning_complete"] = self.fm.learned_s >= self.fcfg.min_learning_s
            if self.fm.analysis is not None:
                s["flow"] = self.fm.analysis.summary()
        if self.discovered_roundabout:
            s["roundabout"] = {k: v for k, v in self.discovered_roundabout.items() if k != "score"}
        return s
