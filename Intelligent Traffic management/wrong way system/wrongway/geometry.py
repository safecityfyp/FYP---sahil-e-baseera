"""Small geometry helpers (pure python / numpy, no heavy deps)."""
from __future__ import annotations

import math
from typing import Sequence

TWO_PI = 2.0 * math.pi


def angle_of(dx: float, dy: float) -> float:
    """Angle of a vector in image coordinates (x right, y down), radians in (-pi, pi]."""
    return math.atan2(dy, dx)


def angdiff(a: float, b: float) -> float:
    """Absolute smallest difference between two angles, in [0, pi]."""
    return abs((a - b + math.pi) % TWO_PI - math.pi)


def point_in_poly(x: float, y: float, poly: Sequence[Sequence[float]]) -> bool:
    """Ray-casting point-in-polygon. Works in any consistent coordinate system."""
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i][0], poly[i][1]
        xj, yj = poly[j][0], poly[j][1]
        if (yi > y) != (yj > y):
            xin = (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi
            if x < xin:
                inside = not inside
        j = i
    return inside


def cw_tangent(px: float, py: float, cx: float, cy: float) -> tuple[float, float]:
    """Unit tangent for CLOCKWISE motion (as seen on screen) around centre (cx, cy).

    Image coordinates have y pointing down; on-screen clockwise motion has a
    positive z-component of cross(r, v), and v = (-ry, rx) satisfies that.
    A camera looking down at the ground plane preserves orientation, so
    clockwise on the ground (left-hand traffic, Pakistan) is clockwise on screen.
    """
    rx, ry = px - cx, py - cy
    d = math.hypot(rx, ry) or 1e-9
    return -ry / d, rx / d
