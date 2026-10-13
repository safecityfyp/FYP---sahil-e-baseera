"""Roundabout discovery + circulation estimation from the learned flow field.

Judging inside a roundabout does NOT depend on this module: the learned grid
already stores the local tangential direction for every cell of the ring, so a
vehicle circulating the wrong way is opposite to its cell's flow. Entry/exit
cells come out as MULTI and are not judged.

This module adds:
  * auto-discovery of circular flow (reported to operators, used for
    commissioning sanity checks: in Pakistan circulation must be clockwise),
  * rotation estimate for operator-declared roundabout zones with rotation=auto.
"""
from __future__ import annotations

import math

import numpy as np

from .flowmap import ONE_WAY, FlowAnalysis, FlowMap


def _one_way_vectors(fm: FlowMap, an: FlowAnalysis):
    rr, cc = np.nonzero(an.kind == ONE_WAY)
    if len(rr) == 0:
        return None
    px = (cc + 0.5) * fm.cell_w
    py = (rr + 0.5) * fm.cell_h
    d = an.direction[rr, cc]
    return px, py, np.cos(d), np.sin(d)


def circulation(fm: FlowMap, an: FlowAnalysis, cx: float, cy: float, rmin: float, rmax: float):
    """Return (rotation 'cw'|'ccw'|None, tangential_coherence, n_cells) around a pixel centre."""
    v = _one_way_vectors(fm, an)
    if v is None:
        return None, 0.0, 0
    px, py, ux, uy = v
    rx, ry = px - cx, py - cy
    d = np.hypot(rx, ry)
    m = (d >= rmin) & (d <= rmax)
    if m.sum() < 4:
        return None, 0.0, int(m.sum())
    tx, ty = -ry[m] / d[m], rx[m] / d[m]            # clockwise tangent (screen)
    s = tx * ux[m] + ty * uy[m]
    coh = float(np.mean(np.abs(s)))
    sign = float(np.mean(np.sign(s)))
    rot = "cw" if sign > 0.6 else ("ccw" if sign < -0.6 else None)
    return rot, coh, int(m.sum())


def discover(fm: FlowMap, an: FlowAnalysis, min_cells: int = 10, min_sectors: int = 5, min_headings: int = 5):
    """Search for circular flow. Returns best candidate dict or None.

    Guards against look-alikes: a divided road seen in perspective also looks
    like a very elongated loop (up on one side, down on the other). A real
    roundabout additionally shows travel headings spread over most of the
    compass (>= 5 of 8 octants), which straight carriageways never do.
    """
    v = _one_way_vectors(fm, an)
    if v is None or len(v[0]) < min_cells:
        return None
    px, py, ux, uy = v
    heading_oct = ((np.arctan2(uy, ux) + math.pi) / (2 * math.pi) * 8).astype(int) % 8
    W, H = fm.frame_w, fm.frame_h
    best = None
    radii = [r * min(W, H) for r in (0.08, 0.12, 0.17, 0.24, 0.33, 0.45)]
    for cy in np.linspace(0.1 * H, 0.9 * H, 12):
        for cx in np.linspace(0.05 * W, 0.95 * W, 20):
            rx, ry = px - cx, py - cy
            d = np.hypot(rx, ry) + 1e-6
            tx, ty = -ry / d, rx / d
            s = tx * ux + ty * uy
            sector = ((np.arctan2(ry, rx) + math.pi) / (2 * math.pi) * 12).astype(int) % 12
            for R in radii:
                m = (d > 0.6 * R) & (d < 1.4 * R)
                n = int(m.sum())
                if n < min_cells:
                    continue
                coh = float(np.mean(np.abs(s[m])))
                sign = float(np.mean(np.sign(s[m])))
                nsec = len(set(sector[m].tolist()))
                if coh < 0.85 or abs(sign) < 0.8 or nsec < min_sectors:
                    continue
                hc = np.bincount(heading_oct[m], minlength=8)
                if int((hc >= max(2, 0.04 * n)).sum()) < min_headings:
                    continue
                score = coh * abs(sign) * nsec * math.log(1 + n)
                if best is None or score > best["score"]:
                    best = {"center": [float(cx / W), float(cy / H)], "radius": float(R / min(W, H)),
                            "rotation": "cw" if sign > 0 else "ccw", "coherence": round(coh, 3),
                            "sectors": nsec, "cells": n, "score": score}
    return best
