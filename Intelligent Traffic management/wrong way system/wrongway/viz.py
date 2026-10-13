"""Overlays for commissioning and alert evidence (OpenCV)."""
from __future__ import annotations

import math

import cv2
import numpy as np

from .flowmap import MULTI, ONE_WAY, TWO_WAY

GREEN, YELLOW, GREY, ORANGE, RED, CYAN, WHITE = (60, 200, 60), (0, 220, 255), (150, 150, 150), (0, 140, 255), \
    (40, 40, 230), (230, 200, 0), (255, 255, 255)


def draw_flow(img: np.ndarray, engine, alpha: float = 0.85) -> np.ndarray:
    """Draw the learned flow map + zones of an engine onto a BGR image (resized to map frame size)."""
    fm = engine.fm
    if fm is None:
        return img
    if img is None:
        img = np.full((fm.frame_h, fm.frame_w, 3), 30, np.uint8)
    if (img.shape[1], img.shape[0]) != (fm.frame_w, fm.frame_h):
        img = cv2.resize(img, (fm.frame_w, fm.frame_h))
    an = fm.analysis
    over = img.copy()
    if an is not None:
        L = 0.42 * min(fm.cell_w, fm.cell_h)
        for r in range(fm.rows):
            for c in range(fm.cols):
                k = an.kind[r, c]
                if k == 0:
                    continue
                cx, cy = fm.cell_center(r, c)
                d = an.direction[r, c]
                dx, dy = math.cos(d) * L, math.sin(d) * L
                p0 = (int(cx - dx), int(cy - dy))
                p1 = (int(cx + dx), int(cy + dy))
                if k == ONE_WAY:
                    col = ORANGE if an.contraflow[r, c] else GREEN
                    cv2.arrowedLine(over, p0, p1, col, 2, tipLength=0.45)
                elif k == TWO_WAY:
                    cv2.arrowedLine(over, (int(cx), int(cy)), p1, YELLOW, 1, tipLength=0.4)
                    cv2.arrowedLine(over, (int(cx), int(cy)), p0, YELLOW, 1, tipLength=0.4)
                elif k == MULTI:
                    cv2.circle(over, (int(cx), int(cy)), 3, GREY, -1)
    img = cv2.addWeighted(over, alpha, img, 1 - alpha, 0)
    W, H = fm.frame_w, fm.frame_h
    for z in engine.zones:
        pts = np.array([[p[0] * W, p[1] * H] for p in z.polygon], np.int32)
        col = {"one_way": CYAN, "two_way": YELLOW, "ignore": GREY, "roundabout": WHITE}[z.type]
        cv2.polylines(img, [pts], True, col, 2)
        cv2.putText(img, f"{z.name} [{z.type}]", tuple(pts[0]), cv2.FONT_HERSHEY_SIMPLEX, 0.6, col, 2)
        if z.type == "one_way" and z.direction:
            (x0, y0), (x1, y1) = z.direction
            cv2.arrowedLine(img, (int(x0 * W), int(y0 * H)), (int(x1 * W), int(y1 * H)), CYAN, 4, tipLength=0.2)
    rb = engine.discovered_roundabout
    if rb:
        c = (int(rb["center"][0] * W), int(rb["center"][1] * H))
        cv2.circle(img, c, int(rb["radius"] * min(W, H)), WHITE, 1)
        cv2.putText(img, f"roundabout {rb['rotation']}", c, cv2.FONT_HERSHEY_SIMPLEX, 0.7, WHITE, 2)
    st = engine.status()
    fl = st.get("flow", {})
    txt = (f"{engine.camera_id}  learned {fl.get('learned_pct', 0)}%  one-way {fl.get('one_way', 0)}  "
           f"two-way {fl.get('two_way', 0)}  multi {fl.get('multi', 0)}  "
           f"{'LEARNING' if not st.get('learning_complete') else 'ACTIVE'}")
    cv2.rectangle(img, (0, 0), (W, 34), (0, 0, 0), -1)
    cv2.putText(img, txt, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, WHITE, 2)
    return img


def draw_alert(frame: np.ndarray, ev: dict) -> np.ndarray:
    """Evidence snapshot: bbox, trajectory, legal vs actual direction."""
    img = frame.copy()
    W, H = ev["frame_size"]
    if (img.shape[1], img.shape[0]) != (W, H):
        sx, sy = img.shape[1] / W, img.shape[0] / H
    else:
        sx = sy = 1.0
    x1, y1, x2, y2 = ev["bbox"]
    p1, p2 = (int(x1 * sx), int(y1 * sy)), (int(x2 * sx), int(y2 * sy))
    col = RED if ev["severity"] == "alert" else ORANGE
    cv2.rectangle(img, p1, p2, col, 3)
    tr = np.array([[p[0] * sx, p[1] * sy] for p in ev["trajectory"]], np.int32)
    if len(tr) > 1:
        cv2.polylines(img, [tr], False, col, 2)
    cx, cy = int((x1 + x2) / 2 * sx), int(y2 * sy)
    L = max(40, int((x2 - x1) * sx))
    a = math.radians(ev["allowed_deg"])
    cv2.arrowedLine(img, (cx, cy), (int(cx + L * math.cos(a)), int(cy + L * math.sin(a))), GREEN, 3, tipLength=0.3)
    b = math.radians(ev["travel_deg"])
    cv2.arrowedLine(img, (cx, cy), (int(cx + L * math.cos(b)), int(cy + L * math.sin(b))), col, 3, tipLength=0.3)
    label = f"WRONG WAY {ev['class']} #{ev['track_id']} ({ev['angle_diff_deg']:.0f} deg)"
    if ev["severity"] != "alert":
        label += f" [suppressed: {ev['suppress_reason']}]"
    cv2.rectangle(img, (0, 0), (img.shape[1], 36), (0, 0, 0), -1)
    cv2.putText(img, f"{ev['camera_id']}  {ev['time']}  {label}", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, col, 2)
    return img
