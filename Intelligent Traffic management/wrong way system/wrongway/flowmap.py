"""Self-learned traffic flow field.

The image is divided into a grid. Each cell keeps a circular histogram of the
directions in which *distinct vehicles* moved through it (one vote per vehicle
per cell), in three memories:

  slow    (half-life ~3 days)  - what the road normally is (one-way / two-way)
  fast    (half-life ~12 min)  - current traffic picture
  recent  (half-life ~3 min)   - onset / end of diversions

From these the cell is classified (vectorised, every few seconds):

  UNKNOWN  - not enough distinct vehicles yet, or no own traffic: never judged
  ONE_WAY  - >=80% of mass within +-45 deg of one direction and no material
             opposite flow in the lateral neighbourhood (lane-side tolerance)
  TWO_WAY  - opposite flow exists nearby: never judged (society streets)
  MULTI    - junction / turning area: never judged
  plus a CONTRAFLOW flag: ONE_WAY by long-term memory, but several distinct
  vehicles recently moved the opposite way => temporary diversion.

The lateral pooling radius is learned per cell from the observed vehicle size,
so the same parameters work for near/far, high/low and 2MP/8MP cameras.
"""
from __future__ import annotations

import math
import time

import numpy as np
from scipy.ndimage import maximum_filter

from .config import FlowConfig

UNKNOWN, ONE_WAY, TWO_WAY, MULTI = 0, 1, 2, 3
KIND_NAMES = {UNKNOWN: "unknown", ONE_WAY: "one_way", TWO_WAY: "two_way", MULTI: "multi"}
_MAX_POOL = 16


def _pool(H: np.ndarray, r: int) -> np.ndarray:
    """Square neighbourhood sum of radius r cells via an integral image (O(N) for any r)."""
    if r == 0:
        return H
    rows, cols = H.shape[:2]
    I = np.zeros((rows + 1, cols + 1) + H.shape[2:], H.dtype)
    I[1:, 1:] = H.cumsum(0).cumsum(1)
    y0 = np.clip(np.arange(rows) - r, 0, rows)
    y1 = np.clip(np.arange(rows) + r + 1, 0, rows)
    x0 = np.clip(np.arange(cols) - r, 0, cols)
    x1 = np.clip(np.arange(cols) + r + 1, 0, cols)
    return I[y1][:, x1] - I[y0][:, x1] - I[y1][:, x0] + I[y0][:, x0]


def _pool_var(H: np.ndarray, rad: np.ndarray) -> np.ndarray:
    out = np.zeros_like(H)
    for r in np.unique(rad):
        m = rad == r
        out[m] = _pool(H, int(r))[m]
    return out


def _dilate(mask: np.ndarray) -> np.ndarray:
    out = mask.copy()
    out[1:] |= mask[:-1]
    out[:-1] |= mask[1:]
    out[:, 1:] |= mask[:, :-1]
    out[:, :-1] |= mask[:, 1:]
    return out


class FlowAnalysis:
    """Snapshot of the classified flow field (read-only for the judge)."""

    def __init__(self, kind, direction, frac, n, contraflow, speed, size, t):
        self.kind = kind              # (rows, cols) int8
        self.direction = direction    # (rows, cols) radians, image coords
        self.frac = frac              # dominant-direction purity
        self.n = n                    # effective distinct vehicles (0 where no own traffic)
        self.contraflow = contraflow  # (rows, cols) bool
        self.speed = speed            # typical speed, body-sizes/s (nan = unknown)
        self.size = size              # typical vehicle size, px (nan = unknown)
        self.t = t

    def summary(self) -> dict:
        seen = self.n > 0
        tot = max(int(seen.sum()), 1)
        return {
            "cells_seen": int(seen.sum()),
            "one_way": int((self.kind == ONE_WAY).sum()),
            "two_way": int((self.kind == TWO_WAY).sum()),
            "multi": int((self.kind == MULTI).sum()),
            "unknown_seen": int(((self.kind == UNKNOWN) & seen).sum()),
            "learned_pct": round(100.0 * float(((self.kind != UNKNOWN) & seen).sum()) / tot, 1),
            "contraflow_cells": int(self.contraflow.sum()),
        }


class FlowMap:
    _CORE = ("S", "F", "R", "size_sum", "spd_sum", "stat_n", "cf_latch", "meta")

    def __init__(self, cfg: FlowConfig, frame_w: int, frame_h: int):
        self.cfg = cfg
        self.frame_w, self.frame_h = int(frame_w), int(frame_h)
        self.cols = int(cfg.grid_cols)
        self.rows = max(4, int(round(self.cols * frame_h / frame_w)))
        self.cell_w = frame_w / self.cols
        self.cell_h = frame_h / self.rows
        self.B = int(cfg.bins)
        shape = (self.rows, self.cols, self.B)
        self.S = np.zeros(shape, np.float32)       # slow direction votes
        self.F = np.zeros(shape, np.float32)       # fast direction votes
        self.R = np.zeros(shape, np.float32)       # recent votes (diversion onset/end)
        self.cf_latch = np.zeros(shape[:2], bool)
        self.size_sum = np.zeros(shape[:2], np.float32)
        self.spd_sum = np.zeros(shape[:2], np.float32)
        self.stat_n = np.zeros(shape[:2], np.float32)
        self.learned_s = 0.0
        self.t_decay: float | None = None
        self.contraflow_since = np.full(shape[:2], np.nan)
        self.created = time.time()
        self._bin_ang = np.arange(self.B) * 2 * math.pi / self.B - math.pi
        self._win = max(1, int(round(45.0 / (360.0 / self.B))))
        self.analysis: FlowAnalysis | None = None

    # ------------------------------------------------------------------ cells
    def cell_of(self, x: float, y: float):
        c = int(x / self.cell_w)
        r = int(y / self.cell_h)
        if 0 <= r < self.rows and 0 <= c < self.cols:
            return r, c
        return None

    def cells_on_segment(self, x0, y0, x1, y1):
        n = int(max(abs(x1 - x0) / self.cell_w, abs(y1 - y0) / self.cell_h) * 2) + 1
        out = []
        for k in range(n + 1):
            a = k / n
            rc = self.cell_of(x0 + (x1 - x0) * a, y0 + (y1 - y0) * a)
            if rc is not None and (not out or out[-1] != rc):
                out.append(rc)
        return out

    def cell_center(self, r, c):
        return (c + 0.5) * self.cell_w, (r + 0.5) * self.cell_h

    # ---------------------------------------------------------------- learning
    def _angle_bins(self, theta):
        f = (theta + math.pi) / (2 * math.pi) * self.B
        b0 = int(math.floor(f)) % self.B
        a = f - math.floor(f)
        return b0, (b0 + 1) % self.B, 1.0 - a, a

    def vote(self, r, c, theta, w_slow=1.0, w_fast=1.0, w_recent=None):
        b0, b1, a0, a1 = self._angle_bins(theta)
        w_recent = w_fast if w_recent is None else w_recent
        for H, w in ((self.S, w_slow), (self.F, w_fast), (self.R, w_recent)):
            if w > 0:
                H[r, c, b0] += w * a0
                H[r, c, b1] += w * a1

    def observe(self, r, c, size_px, speed_bps):
        self.size_sum[r, c] += size_px
        self.spd_sum[r, c] += speed_bps
        self.stat_n[r, c] += 1.0

    def decay(self, now: float):
        if self.t_decay is None:
            self.t_decay = now
            return
        dt = now - self.t_decay
        if dt <= 0:
            return
        fs = 0.5 ** (dt / (self.cfg.slow_half_life_h * 3600.0))
        ff = 0.5 ** (dt / (self.cfg.fast_half_life_min * 60.0))
        fr = 0.5 ** (dt / (self.cfg.recent_half_life_min * 60.0))
        self.S *= fs
        self.F *= ff
        self.R *= fr
        self.size_sum *= fs
        self.spd_sum *= fs
        self.stat_n *= fs
        self.t_decay = now

    def reset(self):
        for a in (self.S, self.F, self.R, self.size_sum, self.spd_sum, self.stat_n):
            a[...] = 0
        self.cf_latch[...] = False
        self.contraflow_since[...] = np.nan
        self.learned_s = 0.0
        self.analysis = None

    # ---------------------------------------------------------------- analysis
    def _wsum(self, H):
        return sum(np.roll(H, k, axis=-1) for k in range(-self._win, self._win + 1))

    def analyze(self, now: float) -> FlowAnalysis:
        cfg = self.cfg
        self.decay(now)
        B, w = self.B, self._win
        eps = 1e-6
        with np.errstate(invalid="ignore", divide="ignore"):
            size = np.where(self.stat_n > 0.5, self.size_sum / self.stat_n, np.nan)
            speed = np.where(self.stat_n > 0.5, self.spd_sum / self.stat_n, np.nan)
        # cells with little own traffic borrow the LARGEST nearby vehicle size (conservative:
        # bigger pooling radius => more likely two-way => fewer false alerts)
        s0 = np.nan_to_num(size, nan=0.0)
        near = maximum_filter(s0, size=7, mode="constant")
        gmax = float(np.nanmax(size)) if np.isfinite(size).any() else self.cell_w
        size_f = np.where(np.isfinite(size), size, np.where(near > 0, near, gmax))
        # lateral pooling radius (cells) = pool_body_sizes vehicle sizes
        rad = np.clip(np.ceil(cfg.pool_body_sizes * size_f / self.cell_w - 0.5), 0, _MAX_POOL).astype(int)
        L = self.S
        P = _pool_var(L, rad)
        nL, nP = L.sum(-1), P.sum(-1)
        D = np.where((nL >= cfg.min_tracks)[..., None], L, P)
        nD = D.sum(-1)
        WD = self._wsum(D)
        p1 = WD.argmax(-1)
        frac1 = np.take_along_axis(WD, p1[..., None], -1)[..., 0] / (nD + eps)
        opp = (p1 + B // 2) % B
        WP = self._wsum(P)
        oppfrac = np.take_along_axis(WP, opp[..., None], -1)[..., 0] / (nP + eps)
        idx = (p1[..., None] + np.arange(-w, w + 1)) % B
        wts = np.take_along_axis(D, idx, -1)
        ang = self._bin_ang[idx]   # votes are linearly interpolated between bin anchor angles
        direction = np.arctan2((wts * np.sin(ang)).sum(-1), (wts * np.cos(ang)).sum(-1))

        # pooled data may only fill cells within ~half a vehicle of cells that see traffic themselves
        own = (nL >= 1.0).astype(np.float32)
        rad_own = np.clip(np.ceil(0.6 * size_f / self.cell_w), 1, 4).astype(int)
        near_own = _pool_var(own, rad_own) > 0
        known = (nD >= cfg.min_tracks) & near_own

        kind = np.full(L.shape[:2], UNKNOWN, np.int8)
        kind[known & (oppfrac >= cfg.two_way_min_frac)] = TWO_WAY
        kind[known & (oppfrac < cfg.two_way_min_frac) & (frac1 >= cfg.one_way_frac)] = ONE_WAY
        kind[known & (oppfrac < cfg.two_way_min_frac) & (frac1 < cfg.one_way_frac)] = MULTI

        # diversion / contraflow: several distinct vehicles *recently* moved against the long-term
        # direction and they are a material share of recent traffic there. Latched with hysteresis:
        # stays on until the recent opposite flow has essentially vanished.
        WR = self._wsum(self.R)
        nR = self.R.sum(-1)
        oppR = np.take_along_axis(WR, opp[..., None], -1)[..., 0]
        onset = (oppR >= cfg.contraflow_min_tracks) & (oppR / (nR + eps) >= cfg.contraflow_min_frac)
        self.cf_latch = (onset | (self.cf_latch & (oppR >= 0.5))) & (kind == ONE_WAY)
        cf = _dilate(_dilate(self.cf_latch)) & (kind == ONE_WAY)
        self.contraflow_since = np.where(cf, np.where(np.isnan(self.contraflow_since), now,
                                                      self.contraflow_since), np.nan)

        self.analysis = FlowAnalysis(kind, direction, frac1, np.where(near_own, nD, 0.0), cf, speed, size, now)
        return self.analysis

    # ------------------------------------------------------------- persistence
    def save(self, path: str, extra: dict | None = None):
        np.savez_compressed(
            path, S=self.S, F=self.F, R=self.R, size_sum=self.size_sum, spd_sum=self.spd_sum,
            stat_n=self.stat_n, cf_latch=self.cf_latch,
            meta=np.array([self.frame_w, self.frame_h, self.cols, self.rows, self.B, self.learned_s,
                           self.t_decay or 0.0], dtype=np.float64),
            **({k: np.asarray(v) for k, v in (extra or {}).items()}))

    def load(self, path: str) -> dict:
        z = np.load(path, allow_pickle=False)
        fw, fh, cols, rows, B, learned, t_decay = z["meta"]
        if (int(cols), int(rows), int(B)) != (self.cols, self.rows, self.B):
            raise ValueError("saved flow map grid does not match current config/resolution")
        self.S[...] = z["S"]
        self.F[...] = z["F"]
        if "R" in z.files:
            self.R[...] = z["R"]
            self.cf_latch[...] = z["cf_latch"]
        self.size_sum[...] = z["size_sum"] * (self.frame_w / fw)
        self.spd_sum[...] = z["spd_sum"]
        self.stat_n[...] = z["stat_n"]
        self.learned_s = float(learned)
        self.t_decay = float(t_decay) or None
        return {k: z[k] for k in z.files if k not in self._CORE}
