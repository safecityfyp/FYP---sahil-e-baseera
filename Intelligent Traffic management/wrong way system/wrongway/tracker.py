"""ByteTrack-style multi-object tracker, tuned for low processing FPS.

Differences from the reference ByteTrack:
  * Kalman filter is time-aware (variable dt) because cameras are processed at
    adaptive rates (2-8 FPS) and frames can be skipped by the motion gate.
  * A third association stage matches by Kalman-predicted centre distance
    (normalised by box size) - fast vehicles near the camera often have zero
    IoU between frames at 5-6 FPS.
  * Class label is a running vote (detector class flicker is common at night).
Pure numpy + scipy; costs ~0.1 ms per camera per frame.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import linear_sum_assignment

from .config import TrackerConfig

_WP = 1.0 / 20.0   # position noise weight (relative to box height)
_WV = 1.0 / 160.0  # velocity noise weight (per 1/30 s, ByteTrack convention)
_REF_FPS = 30.0


class KalmanXYAH:
    """State: [cx, cy, aspect, h, vcx, vcy, va, vh]; velocities per second."""

    def initiate(self, z):
        mean = np.r_[z, np.zeros(4)]
        h = z[3]
        std = [2 * _WP * h, 2 * _WP * h, 1e-2, 2 * _WP * h,
               10 * _WV * h * _REF_FPS, 10 * _WV * h * _REF_FPS, 1e-5 * _REF_FPS, 10 * _WV * h * _REF_FPS]
        return mean, np.diag(np.square(std))

    def predict(self, mean, cov, dt):
        dt = max(dt, 1e-3)
        F = np.eye(8)
        F[:4, 4:] = np.eye(4) * dt
        h = max(mean[3], 1.0)
        k = dt * _REF_FPS
        sp = [_WP * h, _WP * h, 1e-2, _WP * h]
        sv = [_WV * h * _REF_FPS, _WV * h * _REF_FPS, 1e-5 * _REF_FPS, _WV * h * _REF_FPS]
        Q = np.diag(np.square(np.r_[sp, sv]) * k)
        return F @ mean, F @ cov @ F.T + Q

    def update(self, mean, cov, z):
        H = np.eye(4, 8)
        h = max(mean[3], 1.0)
        R = np.diag(np.square([_WP * h, _WP * h, 1e-1, _WP * h]))
        S = H @ cov @ H.T + R
        K = cov @ H.T @ np.linalg.inv(S)
        mean = mean + K @ (z - H @ mean)
        cov = (np.eye(8) - K @ H) @ cov
        return mean, cov


def xyxy_to_xyah(b):
    w, h = b[2] - b[0], b[3] - b[1]
    return np.array([b[0] + w / 2, b[1] + h / 2, w / max(h, 1e-6), h], dtype=float)


def xyah_to_xyxy(s):
    w = s[2] * s[3]
    return np.array([s[0] - w / 2, s[1] - s[3] / 2, s[0] + w / 2, s[1] + s[3] / 2])


def iou_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)))
    x1 = np.maximum(a[:, None, 0], b[None, :, 0])
    y1 = np.maximum(a[:, None, 1], b[None, :, 1])
    x2 = np.minimum(a[:, None, 2], b[None, :, 2])
    y2 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    aa = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    ab = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    return inter / (aa[:, None] + ab[None, :] - inter + 1e-9)


_ids = itertools.count(1)


@dataclass
class Track:
    id: int
    mean: np.ndarray
    cov: np.ndarray
    score: float
    t_first: float
    t_last: float
    hits: int = 1
    confirmed: bool = False
    lost: bool = False
    updated: bool = True              # updated by a detection in the latest step
    cls_votes: dict = field(default_factory=dict)
    bbox: np.ndarray = None           # last *detected* bbox (xyxy)

    @property
    def cls(self) -> int:
        return max(self.cls_votes, key=self.cls_votes.get) if self.cls_votes else -1

    @property
    def pred_bbox(self) -> np.ndarray:
        return xyah_to_xyxy(self.mean[:4])


class ByteTracker:
    def __init__(self, cfg: TrackerConfig | None = None):
        self.cfg = cfg or TrackerConfig()
        self.kf = KalmanXYAH()
        self.tracks: list[Track] = []
        self.t_last: float | None = None

    def reset(self):
        self.tracks.clear()
        self.t_last = None

    def _match(self, tracks, dets, thresh, use_dist=False):
        if not tracks or len(dets) == 0:
            return [], list(range(len(tracks))), list(range(len(dets)))
        tb = np.array([t.pred_bbox for t in tracks])
        if use_dist:
            tc = (tb[:, :2] + tb[:, 2:]) / 2
            dc = (dets[:, :2] + dets[:, 2:4]) / 2
            size = np.sqrt(np.clip((tb[:, 2] - tb[:, 0]) * (tb[:, 3] - tb[:, 1]), 1, None))
            cost = np.linalg.norm(tc[:, None] - dc[None], axis=2) / size[:, None]
        else:
            cost = 1.0 - iou_matrix(tb, dets[:, :4])
            cost = 1.0 - (1.0 - cost) * dets[None, :, 4]  # ByteTrack score fusion
        cost = np.where(cost > thresh, 1e6, cost)
        r, c = linear_sum_assignment(cost)
        matches = [(i, j) for i, j in zip(r, c) if cost[i, j] <= thresh]
        mi = {i for i, _ in matches}
        mj = {j for _, j in matches}
        return matches, [i for i in range(len(tracks)) if i not in mi], [j for j in range(len(dets)) if j not in mj]

    def _apply(self, t: Track, det, ts):
        t.mean, t.cov = self.kf.update(t.mean, t.cov, xyxy_to_xyah(det[:4]))
        t.score = float(det[4])
        t.bbox = det[:4].copy()
        t.t_last = ts
        t.hits += 1
        t.lost = False
        t.updated = True
        c = int(det[5])
        t.cls_votes[c] = t.cls_votes.get(c, 0) + t.score
        if t.hits >= self.cfg.min_hits:
            t.confirmed = True

    def update(self, dets: np.ndarray, ts: float) -> list[Track]:
        """dets: (N, 6) [x1, y1, x2, y2, score, cls]. Returns live (non-removed) tracks."""
        cfg = self.cfg
        dets = np.asarray(dets, dtype=float).reshape(-1, 6) if dets is not None and len(dets) else np.zeros((0, 6))
        dt = 0.0 if self.t_last is None else max(ts - self.t_last, 1e-3)
        self.t_last = ts
        for t in self.tracks:
            t.mean, t.cov = self.kf.predict(t.mean, t.cov, dt)
            t.updated = False

        high = dets[dets[:, 4] >= cfg.high_thresh]
        low = dets[(dets[:, 4] >= cfg.low_thresh) & (dets[:, 4] < cfg.high_thresh)]

        pool = [t for t in self.tracks if t.confirmed]
        unconf = [t for t in self.tracks if not t.confirmed]

        # 1) high-score dets vs confirmed (incl. lost) tracks by IoU
        m, ut, ud = self._match(pool, high, cfg.match_thresh)
        for i, j in m:
            self._apply(pool[i], high[j], ts)
        rem_tracks = [pool[i] for i in ut]
        rem_high = high[ud]
        # 2) leftover high dets vs leftover tracks by predicted-centre distance (low-FPS rescue)
        m, ut, ud = self._match(rem_tracks, rem_high, cfg.dist_gate, use_dist=True)
        for i, j in m:
            self._apply(rem_tracks[i], rem_high[j], ts)
        rem_tracks = [rem_tracks[i] for i in ut]
        rem_high = rem_high[ud]
        # 3) low-score dets vs still-unmatched, currently tracked tracks
        active = [t for t in rem_tracks if not t.lost]
        m, ut, _ = self._match(active, low, 0.5)
        for i, j in m:
            self._apply(active[i], low[j], ts)
        matched_ids = {id(active[i]) for i, _ in m}
        for t in rem_tracks:
            if id(t) not in matched_ids:
                t.lost = True
        # 4) unconfirmed tracks vs remaining high dets
        m, ut, ud = self._match(unconf, rem_high, 0.7)
        for i, j in m:
            self._apply(unconf[i], rem_high[j], ts)
        rem_unconf = [unconf[i] for i in ut]
        rem_high = rem_high[ud]
        #    (fast vehicles close to the camera have no IoU overlap at low FPS: gate by distance)
        m, ut, ud = self._match(rem_unconf, rem_high, cfg.dist_gate, use_dist=True)
        for i, j in m:
            self._apply(rem_unconf[i], rem_high[j], ts)
        dead_unconf = {id(rem_unconf[i]) for i in ut}
        rem_high = rem_high[ud]
        # 5) new tracks
        for d in rem_high:
            if d[4] < cfg.new_track_thresh:
                continue
            mean, cov = self.kf.initiate(xyxy_to_xyah(d[:4]))
            t = Track(id=next(_ids), mean=mean, cov=cov, score=float(d[4]), t_first=ts, t_last=ts,
                      cls_votes={int(d[5]): float(d[4])}, bbox=d[:4].copy())
            self.tracks.append(t)
        # prune
        self.tracks = [t for t in self.tracks
                       if id(t) not in dead_unconf and (ts - t.t_last) <= cfg.max_lost_s]
        return self.tracks
