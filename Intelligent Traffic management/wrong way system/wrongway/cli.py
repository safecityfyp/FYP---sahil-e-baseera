"""Command line entry point: `python -m wrongway <command>` (or `wrongway <command>` once installed)."""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys


def _setup_logging(level):
    logging.basicConfig(level=getattr(logging, level.upper()), format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def cmd_run(a):
    from .config import load_system_config
    from .runner import Runner
    cfg = load_system_config(a.config)
    i, n = (int(x) for x in a.shard.split("/"))
    Runner(cfg, shard=(i, n)).run()


def cmd_check(a):
    from .config import load_system_config
    from .zones import parse_overrides, parse_zones
    cfg = load_system_config(a.config)
    for c in cfg.cameras:
        parse_zones(c.zones)
        parse_overrides(c.overrides)
        cfg.camera_flow(c)
        cfg.camera_judge(c)
    print(f"OK: {len(cfg.cameras)} cameras, detector={cfg.detector.model}, "
          f"profiles={sorted({c.road_profile for c in cfg.cameras})}")


def cmd_offline(a):
    from .config import CameraConfig, SystemConfig, load_system_config
    from .runner import process_video
    cfg = load_system_config(a.config) if a.config else SystemConfig()
    cam = next((c for c in cfg.cameras if c.id == a.camera), None) or CameraConfig(id=a.camera or "offline",
                                                                                   road_profile=a.profile)
    res = process_video(a.video, cfg, cam, a.out, passes=a.passes, write_video=not a.no_video,
                        max_seconds=a.max_seconds, state_in=a.state)
    ww = [e for e in res["events"] if e["type"] == "wrong_way"]
    print(json.dumps({"wrong_way_alerts": sum(e["severity"] == "alert" for e in ww),
                      "suppressed": sum(e["severity"] != "alert" for e in ww),
                      "other_events": [e["type"] for e in res["events"] if e["type"] != "wrong_way"],
                      "status": res["status"]}, indent=1, default=str))
    print(f"outputs in {a.out}")


def cmd_simulate(a):
    from .sim import SCENARIOS, evaluate, run_scenario
    names = list(SCENARIOS) if a.scenario == "all" else [a.scenario]
    ok = True
    for n in names:
        r = evaluate(run_scenario(n, seed=a.seed, verbose=a.verbose))
        good = not r["missed"] and r["false_alerts"] <= (2 if n == "diversion" else 0)
        ok &= good
        print(f"{'PASS' if good else 'FAIL'} {n:22s} wrong={r['true_wrong_vehicles']} detected={r['detected']} "
              f"false_alerts={r['false_alert_labels']} suppressed={r['suppressed']} events={r['other_events']}")
    sys.exit(0 if ok else 1)


def cmd_viz(a):
    import cv2
    from .config import CameraConfig, SystemConfig, load_system_config
    from .engine import WrongWayEngine
    from .viz import draw_flow
    cfg = load_system_config(a.config) if a.config else SystemConfig()
    cam = next((c for c in cfg.cameras if c.id == a.camera), None) or CameraConfig(id=a.camera)
    img = cv2.imread(a.image) if a.image else None
    eng = WrongWayEngine(cam.id, cfg, cam)
    import numpy as np
    meta = np.load(a.state)["meta"]
    eng.load(a.state, (int(meta[0]), int(meta[1])))
    eng.fm.analyze(eng.fm.t_decay or 0)
    cv2.imwrite(a.out, draw_flow(img, eng))
    print(a.out)


def cmd_export(a):
    from .detector import export_model
    print(export_model(a.model, a.imgsz, a.batch, not a.fp32, a.format, a.device))


def main(argv=None):
    p = argparse.ArgumentParser(prog="wrongway", description="Naval Anchorage wrong-way vehicle detection")
    p.add_argument("--log", default="INFO")
    sp = p.add_subparsers(dest="cmd", required=True)

    s = sp.add_parser("run", help="run live on all configured cameras")
    s.add_argument("-c", "--config", required=True)
    s.add_argument("--shard", default="0/1", help="i/n: this process handles every n-th camera starting at i")
    s.set_defaults(fn=cmd_run)

    s = sp.add_parser("check", help="validate configuration")
    s.add_argument("-c", "--config", required=True)
    s.set_defaults(fn=cmd_check)

    s = sp.add_parser("offline", help="process a recorded video (commissioning / validation)")
    s.add_argument("video")
    s.add_argument("-c", "--config")
    s.add_argument("--camera", default="offline")
    s.add_argument("--profile", default="auto", choices=["auto", "main_road", "street", "roundabout"])
    s.add_argument("--passes", type=int, default=2, help="2 = learn on pass 1, report on pass 2")
    s.add_argument("--state", help="start from a saved flow map (.npz)")
    s.add_argument("--max-seconds", type=float)
    s.add_argument("--no-video", action="store_true")
    s.add_argument("-o", "--out", default="offline_out")
    s.set_defaults(fn=cmd_offline)

    s = sp.add_parser("simulate", help="run synthetic validation scenarios")
    s.add_argument("scenario", nargs="?", default="all")
    s.add_argument("--seed", type=int, default=7)
    s.add_argument("-v", "--verbose", action="store_true")
    s.set_defaults(fn=cmd_simulate)

    s = sp.add_parser("viz", help="render a saved flow map over a camera snapshot")
    s.add_argument("state")
    s.add_argument("--image")
    s.add_argument("--camera", default="cam")
    s.add_argument("-c", "--config")
    s.add_argument("-o", "--out", default="flowmap.jpg")
    s.set_defaults(fn=cmd_viz)

    s = sp.add_parser("export-model", help="export YOLO weights to TensorRT/ONNX")
    s.add_argument("--model", default="yolo11s.pt")
    s.add_argument("--imgsz", type=int, default=640)
    s.add_argument("--batch", type=int, default=16)
    s.add_argument("--format", default="engine")
    s.add_argument("--device", default="0")
    s.add_argument("--fp32", action="store_true")
    s.set_defaults(fn=cmd_export)

    a = p.parse_args(argv)
    _setup_logging(a.log)
    a.fn(a)


if __name__ == "__main__":
    main()
