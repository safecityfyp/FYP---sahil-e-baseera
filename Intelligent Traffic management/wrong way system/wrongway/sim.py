"""Synthetic scenario simulator for validating the engine end-to-end.

Vehicles move on a ground plane (metres), are projected through a pinhole
camera (configurable height / focal length / resolution -> perspective, near
vehicles big and fast, far vehicles small and slow), and turned into noisy
detections (jitter, misses, score noise). The engine (tracker + learning +
judge) runs on those detections exactly as in production.

Ground frame: X to the right, Z forward (away from the camera). Left-hand
traffic (Pakistan). Clockwise roundabout = increasing phi where
position = (R sin phi, Zc + R cos phi).
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

import numpy as np

from .config import CameraConfig, SystemConfig
from .engine import WrongWayEngine
from .tracker import iou_matrix

SIZES = {2: (1.8, 1.7), 3: (0.8, 1.6), 5: (2.5, 3.2), 7: (2.4, 3.0)}   # cls -> (width, apparent height) m


@dataclass
class Cam:
    W: int = 1920
    H: int = 1080
    f: float = 1200.0
    hc: float = 8.0          # camera height (m)
    v0: float = 300.0        # horizon row

    def project(self, X, Z, cls):
        if Z < 3:
            return None
        u = self.W / 2 + self.f * X / Z
        v = self.v0 + self.f * self.hc / Z
        wv, hv = SIZES[cls]
        w = self.f * wv / Z
        h = self.f * hv / Z
        return np.array([u - w / 2, v - h, u + w / 2, v])


@dataclass
class Vehicle:
    vid: int
    pts: list                 # [(X, Z), ...]
    speeds: list              # speed (m/s) for each segment
    t0: float
    cls: int = 2
    label: str = "normal"     # normal | wrong | reverse | uturn | diverted ...
    wander: float = 0.15
    _cum: list = field(default_factory=list)

    def __post_init__(self):
        self._cum = [0.0]
        for i in range(len(self.pts) - 1):
            seg = math.dist(self.pts[i], self.pts[i + 1]) / max(self.speeds[i], 1e-6)
            self._cum.append(self._cum[-1] + seg)
        self.phase = random.random() * 6.28

    @property
    def t_end(self):
        return self.t0 + self._cum[-1]

    def pos(self, t):
        tt = t - self.t0
        if tt < 0 or tt > self._cum[-1]:
            return None
        for i in range(len(self.pts) - 1):
            if tt <= self._cum[i + 1]:
                a = (tt - self._cum[i]) / max(self._cum[i + 1] - self._cum[i], 1e-9)
                (x0, z0), (x1, z1) = self.pts[i], self.pts[i + 1]
                X = x0 + (x1 - x0) * a
                Z = z0 + (z1 - z0) * a
                return X + self.wander * math.sin(0.4 * t + self.phase), Z
        return None


def _poisson_times(rng, t0, t1, mean_gap):
    t, out = t0, []
    while True:
        t += rng.expovariate(1.0 / mean_gap)
        if t >= t1:
            return out
        out.append(t)


def _rand_cls(rng):
    r = rng.random()
    return 3 if r < 0.30 else (5 if r < 0.35 else (7 if r < 0.40 else 2))


# --------------------------------------------------------------- scenarios
def scenario_divided_road(rng, T=1800, learn=900, cam=None):
    """Divided main road. A: X<0 away (+Z). B: X>0 toward (-Z). Median |X|<1.5."""
    V, vid = [], 0
    for lane_x, sign in ((-2.8, 1), (-5.6, 1), (2.8, -1), (5.6, -1)):
        for t in _poisson_times(rng, 0, T, 9.0):
            z0, z1 = (8, 140) if sign > 0 else (140, 8)
            sp = rng.uniform(8, 16)
            lx = lane_x + rng.uniform(-0.4, 0.4)
            pts = [(lx, z0), (lx, z1)]
            if rng.random() < 0.15:     # lane change
                zc = rng.uniform(30, 90)
                nx = (-4.2 if sign > 0 else 4.2) + rng.uniform(-1.2, 1.2)
                pts = [(lx, z0), (lx, zc), (nx, zc + 15 * sign), (nx, z1)]
            vid += 1
            V.append(Vehicle(vid, pts, [sp] * (len(pts) - 1), t, _rand_cls(rng)))
    vid += 1; V.append(Vehicle(vid, [(-4.0, 130), (-4.0, 10)], [10], learn + 120, 2, "wrong"))
    vid += 1; V.append(Vehicle(vid, [(4.5, 10), (4.5, 130)], [7], learn + 300, 3, "wrong"))
    # reversing car in carriageway A: drives forward, then backs up 7 m slowly
    vid += 1; V.append(Vehicle(vid, [(-5.6, 10), (-5.6, 40), (-5.6, 33)], [6, 1.0], learn + 200, 2, "reverse", 0.0))
    # legal U-turn through a median gap at Z=60
    vid += 1; V.append(Vehicle(vid, [(-2.8, 10), (-2.8, 57), (0, 61), (2.8, 57), (2.8, 10)],
                               [9, 3, 3, 9], learn + 450, 2, "uturn"))
    # vehicle that briefly drifts across then corrects (no alert expected)
    vid += 1; V.append(Vehicle(vid, [(-2.8, 10), (-2.8, 50), (-1.0, 58), (-2.8, 66), (-2.8, 130)],
                               [11, 11, 11, 11], learn + 600, 2, "drift"))
    return V, T


def scenario_two_way_street(rng, T=1800, learn=900):
    """7 m undivided society street, 70/30 traffic, parked cars force using the other side."""
    V, vid = [], 0
    parked = [(-3.0, 30), (-3.0, 52)]
    for sign, gap, lx in ((1, 11.0, -1.6), (-1, 26.0, 1.6)):
        for t in _poisson_times(rng, 0, T, gap):
            sp = rng.uniform(5, 10)
            x = lx + rng.uniform(-0.5, 0.5)
            if sign > 0:
                pts = [(x, 8), (x, 24), (0.4, 30), (0.4, 58), (x, 64), (x, 110)]
            else:
                pts = [(x, 110), (x, 8)]
            vid += 1
            V.append(Vehicle(vid, pts, [sp] * (len(pts) - 1), t, _rand_cls(rng), wander=0.3))
    for i, (px, pz) in enumerate(parked):
        vid += 1
        V.append(Vehicle(vid, [(px, pz), (px, pz + 0.01)], [1e-6], 0, 2, "parked", 0.0))
    # overtaking on the right side for 40 m (legal on a two-way street)
    vid += 1; V.append(Vehicle(vid, [(-1.6, 10), (1.4, 25), (1.4, 65), (-1.6, 80), (-1.6, 110)],
                               [9, 9, 9, 9], learn + 300, 2, "overtake"))
    # downhill car forced onto the far-left kerb by a double-parked truck (legal manoeuvre on a street)
    vid += 1; V.append(Vehicle(vid, [(1.6, 110), (1.6, 70), (-2.6, 62), (-2.6, 30), (1.6, 22), (1.6, 8)],
                               [8, 8, 8, 8, 8], learn + 500, 2, "kerb_swap", 0.0))
    return V, T


def scenario_roundabout(rng, T=1800, learn=900):
    """Clockwise roundabout (left-hand traffic), 4 arms, centre Z=45, R=10."""
    Zc, R, d = 45.0, 10.0, math.asin(2.0 / 10.0)
    arms = [0.0, math.pi / 2, math.pi, 3 * math.pi / 2]

    def arm_pt(phi, off, dist):
        # point on arm `phi` at distance `dist` from centre, lateral offset `off` (+ = increasing phi side)
        ux, uz = math.sin(phi), math.cos(phi)
        tx, tz = math.cos(phi), -math.sin(phi)
        return (ux * dist + tx * off, Zc + uz * dist + tz * off)

    def ring(p0, p1, step=0.15, direction=1):
        pts, p = [], p0
        while (p1 - p) * direction > 0:
            pts.append((R * math.sin(p), Zc + R * math.cos(p)))
            p += step * direction
        pts.append((R * math.sin(p1), Zc + R * math.cos(p1)))
        return pts

    def trip(a_in, a_out, wrong=False):
        pin, pout = arms[a_in], arms[a_out]
        if not wrong:
            p0 = pin + d
            p1 = pout - d
            while p1 <= p0:
                p1 += 2 * math.pi
            entry = [arm_pt(pin, 2.0, 40), arm_pt(pin, 2.0, R + 1)]
            exitp = [arm_pt(pout, -2.0, R + 1), arm_pt(pout, -2.0, 40)]
            return entry + ring(p0, p1) + exitp
        p0, p1 = pin - d, pout + d
        while p1 >= p0:
            p1 -= 2 * math.pi
        entry = [arm_pt(pin, -2.0, 40), arm_pt(pin, -2.0, R + 1)]
        exitp = [arm_pt(pout, 2.0, R + 1), arm_pt(pout, 2.0, 40)]
        return entry + ring(p0, p1, direction=-1) + exitp

    V, vid = [], 0
    for t in _poisson_times(rng, 0, T, 3.5):
        a_in = rng.randrange(4)
        a_out = (a_in + rng.choice([1, 2, 2, 3])) % 4
        pts = trip(a_in, a_out)
        vid += 1
        V.append(Vehicle(vid, pts, [rng.uniform(5, 8)] * (len(pts) - 1), t, _rand_cls(rng), wander=0.2))
    pts = trip(2, 1, wrong=True)   # south -> east the short (counter-clockwise) way
    vid += 1; V.append(Vehicle(vid, pts, [7.0] * (len(pts) - 1), learn + 200, 2, "wrong"))
    pts = trip(1, 0, wrong=True)   # east -> north counter-clockwise (motorbike)
    vid += 1; V.append(Vehicle(vid, pts, [6.0] * (len(pts) - 1), learn + 500, 3, "wrong"))
    return V, T


def scenario_diversion(rng, T=6600, learn=900, div=(1500, 2700)):
    """Divided road; carriageway B closed during `div`, its traffic runs contraflow in A's inner lane."""
    V, vid = [], 0
    for lane_x, sign in ((-2.8, 1), (-5.6, 1), (2.8, -1), (5.6, -1)):
        for t in _poisson_times(rng, 0, T, 9.0):
            sp = rng.uniform(8, 14)
            lx = lane_x + rng.uniform(-0.4, 0.4)
            label = "normal"
            if sign < 0 and div[0] <= t < div[1]:
                lx = -2.6 + rng.uniform(-0.3, 0.3)   # diverted into A
                label = "diverted"
            elif sign > 0 and div[0] <= t < div[1]:
                lx = -5.4 + rng.uniform(-0.3, 0.3)   # A traffic squeezed to outer lane
            z0, z1 = (8, 140) if sign > 0 else (140, 8)
            vid += 1
            V.append(Vehicle(vid, [(lx, z0), (lx, z1)], [sp], t, _rand_cls(rng), label))
    vid += 1; V.append(Vehicle(vid, [(-4.0, 130), (-4.0, 10)], [10], T - 300, 2, "wrong"))
    return V, T


SCENARIOS = {
    "divided_road": (scenario_divided_road, {}, Cam()),
    "divided_road_low_cam": (scenario_divided_road, {}, Cam(W=1280, H=720, f=900, hc=4.5, v0=220)),
    "two_way_street": (scenario_two_way_street, {"road_profile": "street"}, Cam(hc=6.0)),
    "roundabout": (scenario_roundabout, {"road_profile": "roundabout"}, Cam(hc=25.0, f=1000, v0=-150)),
    "diversion": (scenario_diversion, {"road_profile": "main_road"}, Cam()),
}


def run_scenario(name: str, seed: int = 7, fps: float = 6.0, learn_s: float = 900.0, verbose=False):
    fn, cam_kw, cam = SCENARIOS[name]
    rng = random.Random(seed)
    random.seed(seed)
    vehicles, T = fn(rng)
    sys_cfg = SystemConfig()
    sys_cfg.flow.min_learning_s = learn_s
    eng = WrongWayEngine(name, sys_cfg, CameraConfig(id=name, **cam_kw))
    base = 1_760_000_000.0
    dt = 1.0 / fps
    events, n = [], int(T * fps)
    for k in range(n):
        t = k * dt
        dets, gt = [], []
        for v in vehicles:
            if t < v.t0 or t > v.t_end:
                continue
            p = v.pos(t)
            if p is None:
                continue
            b = cam.project(p[0], p[1], v.cls)
            if b is None:
                continue
            bw, bh = b[2] - b[0], b[3] - b[1]
            if b[2] < 0 or b[0] > cam.W or b[3] < 0 or b[1] > cam.H or bh < 8:
                continue
            gt.append((v, b.copy()))
            if rng.random() < 0.07:
                continue
            jb = b + np.array([rng.gauss(0, 0.03 * bw), rng.gauss(0, 0.03 * bh),
                               rng.gauss(0, 0.03 * bw), rng.gauss(0, 0.03 * bh)])
            jb = np.clip(jb, 0, [cam.W, cam.H, cam.W, cam.H])
            dets.append([*jb, rng.uniform(0.45, 0.95), v.cls])
        if rng.random() < 0.02:   # occasional ghost box
            x, y = rng.uniform(0, cam.W - 60), rng.uniform(cam.H * 0.4, cam.H - 60)
            dets.append([x, y, x + 50, y + 40, rng.uniform(0.3, 0.6), 2])
        evs = eng.update(base + t, np.array(dets) if dets else None, (cam.W, cam.H))
        for e in evs:
            if e["type"] == "wrong_way" and gt:
                gb = np.array([g[1] for g in gt])
                iou = iou_matrix(np.array([e["bbox"]]), gb)[0]
                j = int(iou.argmax())
                e["_gt"] = (gt[j][0].vid, gt[j][0].label) if iou[j] > 0.3 else (None, "unmatched")
            e["_t"] = t
            events.append(e)
            if verbose:
                print(f"[{name} t={t:7.1f}] {e['type']} {e.get('severity')} {e.get('_gt', '')} "
                      f"{e.get('suppress_reason') or ''} {e.get('rule', '')}")
    return {"engine": eng, "events": events, "vehicles": vehicles, "T": T}


def evaluate(result) -> dict:
    ww = [e for e in result["events"] if e["type"] == "wrong_way" and e["severity"] == "alert"]
    sup = [e for e in result["events"] if e["type"] == "wrong_way" and e["severity"] == "suppressed"]
    wrong_ids = {v.vid for v in result["vehicles"] if v.label == "wrong"}
    hit_ids = {e["_gt"][0] for e in ww if e.get("_gt") and e["_gt"][0] in wrong_ids}
    fps = [e for e in ww if not (e.get("_gt") and e["_gt"][1] == "wrong")]
    return {
        "true_wrong_vehicles": len(wrong_ids),
        "detected": len(hit_ids),
        "missed": sorted(wrong_ids - hit_ids),
        "false_alerts": len(fps),
        "false_alert_labels": [e.get("_gt", (None, "?"))[1] for e in fps],
        "suppressed": len(sup),
        "suppressed_labels": [e.get("_gt", (None, "?"))[1] for e in sup],
        "other_events": [e["type"] for e in result["events"] if e["type"] != "wrong_way"],
        "flow": result["engine"].status().get("flow"),
        "vehicles_simulated": len(result["vehicles"]),
    }
