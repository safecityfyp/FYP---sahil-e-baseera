"""Tests: unit checks + end-to-end synthetic scenarios + runtime integration.

Run:  pytest -q tests            (full scenarios take ~2-3 min on one CPU core)
"""
import json
import math
import os
import time

import cv2
import numpy as np
import pytest

from wrongway.config import CameraConfig, SystemConfig, load_system_config
from wrongway.engine import WrongWayEngine
from wrongway.flowmap import ONE_WAY, TWO_WAY, FlowMap
from wrongway.geometry import angdiff, cw_tangent
from wrongway.scene_guard import SceneGuard
from wrongway.sim import evaluate, run_scenario
from wrongway.tracker import ByteTracker
from wrongway.zones import parse_overrides, parse_zones, zone_at

HERE = os.path.dirname(__file__)


# ----------------------------------------------------------------- unit
def test_angles_and_tangent():
    assert abs(angdiff(math.pi - 0.1, -math.pi + 0.1) - 0.2) < 1e-9
    tx, ty = cw_tangent(1, 0, 0, 0)          # right of centre, clockwise on screen => moving down (+y)
    assert (round(tx, 6), round(ty, 6)) == (0.0, 1.0)


def test_flowmap_one_way_vs_two_way():
    cfg = SystemConfig().flow
    fm = FlowMap(cfg, 1920, 1080)
    for _ in range(20):
        fm.vote(10, 10, math.pi / 2)                       # all down
        fm.observe(10, 10, 60, 2.0)
        fm.vote(10, 30, math.pi / 2)
        fm.vote(10, 30, -math.pi / 2) if _ % 2 else None    # half up, half down
        fm.observe(10, 30, 60, 2.0)
    an = fm.analyze(0.0)
    assert an.kind[10, 10] == ONE_WAY and abs(an.direction[10, 10] - math.pi / 2) < 0.1
    assert an.kind[10, 30] == TWO_WAY


def test_tracker_low_fps_fast_vehicle():
    tr = ByteTracker()
    ids = set()
    for k in range(12):   # 100x100 box moving 80 px per frame (no IoU overlap at times)
        x = 100 + 80 * k
        out = tr.update(np.array([[x, 500, x + 100, 600, 0.9, 2]]), k / 6.0)
        ids |= {t.id for t in out if t.confirmed}
    assert len(ids) == 1


def test_zones_and_overrides():
    z = parse_zones([{"name": "a", "type": "one_way", "polygon": [[0, 0], [1, 0], [1, 1], [0, 1]],
                      "direction": [[0.5, 0.9], [0.5, 0.1]]},
                     {"name": "b", "type": "ignore", "polygon": [[0, 0], [0.2, 0], [0.2, 0.2], [0, 0.2]]}])
    assert zone_at(z, 0.1, 0.1).name == "b" and zone_at(z, 0.5, 0.5).name == "a"
    ang = z[0].allowed_angle(960, 540, 1920, 1080)
    assert abs(ang - (-math.pi / 2)) < 1e-6        # up the image
    o = parse_overrides([{"mode": "suppress", "until": "2099-01-01T00:00"}])[0]
    assert o.active(time.time())


def test_config_loads():
    cfg = load_system_config(os.path.join(HERE, "..", "configs", "system.yaml"))
    assert len(cfg.cameras) >= 3
    street = next(c for c in cfg.cameras if c.road_profile == "street")
    assert cfg.camera_flow(street).pool_body_sizes > cfg.flow.pool_body_sizes


def test_scene_guard():
    rng = np.random.default_rng(0)
    img = (rng.random((540, 960)) * 255).astype(np.uint8)
    img = cv2.GaussianBlur(img, (0, 0), 3)
    img = cv2.cvtColor(cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX), cv2.COLOR_GRAY2BGR)
    g = SceneGuard()
    assert g.check(img) == "init"
    assert g.check(cv2.convertScaleAbs(img, alpha=0.6, beta=10)) == "same"       # darker (dusk)
    shifted = np.roll(img, 120, axis=1)
    res = [g.check(shifted) for _ in range(3)]
    assert res[-1] == "changed"


# ----------------------------------------------------------------- scenarios
@pytest.mark.parametrize("name", ["divided_road", "divided_road_low_cam", "two_way_street", "roundabout"])
def test_scenarios(name):
    r = evaluate(run_scenario(name))
    assert not r["missed"], r
    assert r["false_alerts"] == 0, r


def test_diversion_adapts():
    res = run_scenario("diversion")
    r = evaluate(res)
    types = [e["type"] for e in res["events"]]
    assert "contraflow_suspected" in types and "contraflow_cleared" in types
    assert r["false_alerts"] <= 3, r            # only the vehicles before the diversion is recognised
    assert r["suppressed"] > 50
    assert not r["missed"], r                   # wrong-way detection works again after the diversion


# ----------------------------------------------------------------- runtime integration
class _FakeReader:
    def __init__(self, frames):
        self.frames, self.i = frames, -1
        self.online, self.last_ok, self.fps_in = True, time.time(), 6.0

    def start(self):
        pass

    def stop(self):
        pass

    def latest(self):
        self.i = min(self.i + 1, len(self.frames) - 1)
        f, ts = self.frames[self.i]
        return f, ts, self.i


class _FakeDetector:
    def __init__(self, dets_by_ts):
        self.d = dets_by_ts

    def infer(self, frames):
        return [self.d.pop(0) if self.d else np.zeros((0, 6)) for _ in frames]


def test_runner_end_to_end(tmp_path):
    from wrongway.runner import CameraContext, Runner
    cfg = SystemConfig()
    cfg.runtime.state_dir = str(tmp_path / "state")
    cfg.runtime.events_dir = str(tmp_path / "events")
    cfg.runtime.api_port = 0
    cfg.runtime.process_fps = 1e6
    cfg.runtime.idle_fps = 1e6
    cfg.flow.min_learning_s = 0
    cfg.flow.min_tracks = 3
    cfg.cameras = [CameraConfig(id="t1")]
    W, H = 1280, 720
    frames, dets = [], []
    base = time.time()
    # 40 vehicles going up the left half, then 1 going down
    t = 0.0
    for v in range(41):
        down = v == 40
        for k in range(40):
            y = (100 + 14 * k) if down else (650 - 14 * k)
            img = np.full((H, W, 3), 40, np.uint8)
            cv2.rectangle(img, (400, y - 60), (480, y), (200, 200, 200), -1)
            frames.append((img, base + t))
            dets.append(np.array([[400, y - 60, 480, y, 0.9, 2]], float))
            t += 1 / 6
        frames.append((np.full((H, W, 3), 40, np.uint8), base + t))
        dets.append(np.zeros((0, 6)))
        t += 3.0
    r = Runner(cfg, detector=_FakeDetector(dets))
    ctx = r.cams["t1"]
    ctx.reader = _FakeReader(frames)
    ctx.gate = None
    r.alerts.start()
    for _ in range(len(frames)):
        for c in r.cams.values():
            c.next_due = 0
        r.step()
    time.sleep(1.0)
    ww = [e for e in r.alerts.recent if e["type"] == "wrong_way" and e["severity"] == "alert"]
    assert len(ww) == 1
    assert os.path.exists(ww[0]["snapshot"])
    ctx.save()
    assert os.path.exists(ctx.state_path)
    eng2 = WrongWayEngine("t1", cfg, cfg.cameras[0])
    eng2.load(ctx.state_path, (W, H))
    assert eng2.fm.S.sum() > 0
    st = r.status()
    json.dumps(st, default=str)
