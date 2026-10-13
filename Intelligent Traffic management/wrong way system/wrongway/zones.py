"""Operator-drawn zones and time-based overrides.

Zones are optional: the learned flow map works without them. Use them to
(a) give certainty on critical main-road stretches from minute one,
(b) silence areas where direction rules do not apply (parking, gates, fuel
    stations, service lanes), and
(c) declare roundabouts.

Coordinates are normalised [0..1] (x by width, y by height) so the same file
survives resolution / stream changes.

    zones:
      - name: main_blvd_north
        type: one_way                  # one_way | two_way | ignore | roundabout
        polygon: [[0.1,0.5],[0.45,0.5],[0.4,1.0],[0.0,1.0]]
        direction: [[0.25,0.95],[0.3,0.55]]   # arrow tail -> head (legal travel)
      - name: rbt
        type: roundabout
        polygon: [...]
        center: [0.55, 0.45]
        rotation: auto                 # auto | cw | ccw
    overrides:
      - zone: main_blvd_north          # omit for the whole camera
        mode: suppress                 # suppress | two_way
        schedule: {days: [fri], start: "12:30", end: "14:30"}   # Friday prayers diversion
      - mode: suppress
        until: "2026-10-20T18:00"      # one-off event / road works
"""
from __future__ import annotations

import datetime as _dt
import math
from dataclasses import dataclass
from typing import Optional

from .geometry import angle_of, cw_tangent, point_in_poly

ZONE_TYPES = {"one_way", "two_way", "ignore", "roundabout"}
_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


@dataclass
class Zone:
    name: str
    type: str
    polygon: list
    direction: Optional[list] = None
    center: Optional[list] = None
    rotation: str = "auto"
    learned_rotation: Optional[str] = None   # filled from flow map for roundabouts

    def contains(self, xn: float, yn: float) -> bool:
        return point_in_poly(xn, yn, self.polygon)

    def allowed_angle(self, x_px: float, y_px: float, W: int, H: int, default_rotation: str = "cw"):
        """Legal travel direction (radians, pixel space) at a point, or None."""
        if self.type == "one_way" and self.direction:
            (x0, y0), (x1, y1) = self.direction
            return angle_of((x1 - x0) * W, (y1 - y0) * H)
        if self.type == "roundabout" and self.center:
            rot = self.rotation if self.rotation in ("cw", "ccw") else (self.learned_rotation or default_rotation)
            tx, ty = cw_tangent(x_px, y_px, self.center[0] * W, self.center[1] * H)
            if rot == "ccw":
                tx, ty = -tx, -ty
            return math.atan2(ty, tx)
        return None


def parse_zones(raw: list) -> list[Zone]:
    zones = []
    for i, z in enumerate(raw or []):
        t = z.get("type")
        if t not in ZONE_TYPES:
            raise ValueError(f"zone {i}: type must be one of {sorted(ZONE_TYPES)}")
        poly = z.get("polygon")
        if not poly or len(poly) < 3:
            raise ValueError(f"zone {i}: polygon needs >= 3 points")
        if t == "one_way" and not z.get("direction"):
            raise ValueError(f"zone {i}: one_way needs direction [[x0,y0],[x1,y1]]")
        if t == "roundabout" and not z.get("center"):
            raise ValueError(f"zone {i}: roundabout needs center")
        zones.append(Zone(name=z.get("name", f"zone{i}"), type=t, polygon=poly, direction=z.get("direction"),
                          center=z.get("center"), rotation=z.get("rotation", "auto")))
    return zones


# priority when zones overlap
_PRIO = {"ignore": 0, "one_way": 1, "roundabout": 2, "two_way": 3}


def zone_at(zones: list[Zone], xn: float, yn: float) -> Optional[Zone]:
    hits = [z for z in zones if z.contains(xn, yn)]
    return min(hits, key=lambda z: _PRIO[z.type]) if hits else None


@dataclass
class Override:
    mode: str = "suppress"
    zone: Optional[str] = None
    days: Optional[list] = None
    start: Optional[str] = None
    end: Optional[str] = None
    until: Optional[float] = None    # epoch seconds
    reason: str = ""

    def active(self, ts: float) -> bool:
        if self.until is not None:
            return ts <= self.until
        if self.start and self.end:
            t = _dt.datetime.fromtimestamp(ts)
            if self.days and _DAYS[t.weekday()] not in self.days:
                return False
            hm = t.strftime("%H:%M")
            if self.start <= self.end:
                return self.start <= hm < self.end
            return hm >= self.start or hm < self.end   # crosses midnight
        return True


def parse_overrides(raw: list) -> list[Override]:
    out = []
    for o in raw or []:
        sch = o.get("schedule") or {}
        until = o.get("until")
        if isinstance(until, str):
            until = _dt.datetime.fromisoformat(until).timestamp()
        elif isinstance(until, _dt.datetime):
            until = until.timestamp()
        days = [d.lower()[:3] for d in sch.get("days", [])] or None
        out.append(Override(mode=o.get("mode", "suppress"), zone=o.get("zone"), days=days,
                            start=sch.get("start"), end=sch.get("end"), until=until, reason=o.get("reason", "")))
    return out
