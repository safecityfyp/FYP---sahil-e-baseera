"""Camera view-change / tamper guard.

A learned flow map is only valid for the view it was learned on. If a camera
is bumped, re-aimed, a PTZ preset changes or a vendor swaps the unit, the map
must be invalidated, otherwise every vehicle could be "wrong way".

Method (cheap: one 160x90 edge image per minute per camera):
  * keep a small bank of reference edge maps (day / dusk / night-IR look different)
  * phase-correlate the current edge map against each reference
  * a view is "same" if any reference matches with small shift and decent
    correlation; a strong match with a large shift, or no match at all for
    several consecutive checks => view changed.
Edges (not intensities) keep IR switching and headlights from looking like a move.
"""
from __future__ import annotations

import cv2
import numpy as np

_W, _H = 160, 90


def _edge_map(frame: np.ndarray) -> np.ndarray:
    g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    g = cv2.resize(g, (_W, _H), interpolation=cv2.INTER_AREA)
    g = cv2.GaussianBlur(g, (3, 3), 0)
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1)
    m = cv2.magnitude(gx, gy)
    m -= m.mean()
    return m / (m.std() + 1e-6)


class SceneGuard:
    def __init__(self, max_refs: int = 4, shift_thresh: float = 0.04, min_corr: float = 0.25,
                 confirm_checks: int = 3):
        self.refs: list[np.ndarray] = []
        self.max_refs = max_refs
        self.shift_thresh = shift_thresh
        self.min_corr = min_corr
        self.confirm = confirm_checks
        self.bad = 0
        self._win = cv2.createHanningWindow((_W, _H), cv2.CV_32F)

    def _match(self, e, ref):
        (dx, dy), resp = cv2.phaseCorrelate(ref * self._win, e * self._win)
        corr = float((e * ref).mean())
        return abs(dx) / _W, abs(dy) / _H, corr, resp

    def check(self, frame: np.ndarray) -> str:
        """Returns 'init' | 'same' | 'suspect' | 'changed'."""
        e = _edge_map(frame)
        if not self.refs:
            self.refs.append(e)
            return "init"
        best = None
        for i, ref in enumerate(self.refs):
            sx, sy, corr, resp = self._match(e, ref)
            same = sx < self.shift_thresh and sy < self.shift_thresh and corr >= self.min_corr
            if same:
                best = i
                break
        if best is not None:
            self.bad = 0
            # refresh the matched reference slowly (weather, seasons, new signage)
            self.refs[best] = 0.9 * self.refs[best] + 0.1 * e
            return "same"
        # lighting regime we have not stored yet (first night)? store if no geometric shift evidence
        sx, sy, corr, resp = self._match(e, self.refs[0])
        if resp > 0.3 and (sx >= self.shift_thresh or sy >= self.shift_thresh):
            self.bad += 1                         # confident translation => moved
        elif len(self.refs) < self.max_refs and corr > 0.05:
            self.refs.append(e)                   # plausible new lighting regime
            return "same"
        else:
            self.bad += 1
        if self.bad >= self.confirm:
            self.bad = 0
            self.refs = [e]
            return "changed"
        return "suspect"

    def state(self) -> dict:
        return {f"ref{i}": r.astype(np.float16) for i, r in enumerate(self.refs)}

    def load_state(self, d: dict):
        refs = [d[k].astype(np.float32) for k in sorted(d) if k.startswith("ref")]
        if refs:
            self.refs = refs[: self.max_refs]
