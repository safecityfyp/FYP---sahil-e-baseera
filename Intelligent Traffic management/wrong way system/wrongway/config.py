"""Configuration: dataclasses with sane production defaults + YAML loading.

Every per-camera section (flow / judge) can override the system defaults, and
`road_profile` applies a preset first (main_road / street / roundabout / auto).
"""
from __future__ import annotations

import copy
import glob
import os
from dataclasses import dataclass, field, fields, asdict
from typing import Any, Optional

import yaml


@dataclass
class DetectorConfig:
    backend: str = "ultralytics"          # "ultralytics" | "none" (external detections)
    model: str = "yolo11s.pt"             # .pt, or exported .engine (TensorRT) / .onnx
    imgsz: int = 640
    conf: float = 0.20                    # low on purpose: ByteTrack uses low-score boxes
    iou: float = 0.6
    half: bool = True
    device: str = "cuda:0"
    batch_size: int = 16
    # COCO ids -> label. Motorcycles matter a lot locally.
    classes: dict = field(default_factory=lambda: {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"})


@dataclass
class TrackerConfig:
    high_thresh: float = 0.45
    low_thresh: float = 0.10
    new_track_thresh: float = 0.50
    match_thresh: float = 0.80            # max (1 - IoU) for a match
    dist_gate: float = 1.0                # fallback centre-distance gate, in box sizes (low-FPS help)
    max_lost_s: float = 1.5
    min_hits: int = 2


@dataclass
class FlowConfig:
    grid_cols: int = 48                   # rows derived from aspect ratio
    bins: int = 16                        # direction histogram bins (22.5 deg)
    slow_half_life_h: float = 72.0        # long-term road "knowledge"
    fast_half_life_min: float = 12.0      # short-term memory (diversions)
    min_tracks: float = 8.0               # distinct vehicles before a cell is trusted
    one_way_frac: float = 0.80            # mass within +-45 deg of dominant direction
    two_way_min_frac: float = 0.06        # opposite mass (pooled) that makes a cell two-way
    pool_body_sizes: float = 1.5          # lateral pooling radius (vehicle widths) -> lane-side tolerance
    alerted_vote_weight: float = 0.3      # how much confirmed violators teach the long-term map
    contraflow_adapt: bool = True         # auto-suppress during temporary diversions
    contraflow_min_tracks: float = 3.0     # distinct opposite vehicles in recent memory
    contraflow_min_frac: float = 0.25      # ...and this share of recent traffic in those cells
    recent_half_life_min: float = 3.0      # memory used for diversion onset / end
    contraflow_window_min: float = 10.0    # N wrong-way triggers at the same spot within this window => diversion
    analysis_interval_s: float = 5.0
    commit_interval_s: float = 8.0
    min_learning_s: float = 1800.0        # observed seconds before learned cells may alert
    persistent_change_h: float = 24.0     # contraflow lasting this long -> "relearn?" event


@dataclass
class JudgeConfig:
    eval_window_s: float = 0.8
    min_speed_bps: float = 0.35           # body-sizes per second
    reverse_speed_ratio: float = 0.30     # slower than this x typical cell speed -> likely reversing
    wrong_angle_deg: float = 130.0
    ok_angle_deg: float = 70.0
    min_wrong_path_bodies: float = 5.0
    min_wrong_time_s: float = 1.2
    min_wrong_cells: int = 3
    min_track_age_s: float = 1.5
    min_wrong_ratio: float = 0.75
    max_jump_bodies: float = 3.0          # bigger jump between updates = ID switch -> reset evidence
    border_margin: float = 0.01
    realert_after_s: float = 120.0


@dataclass
class RuntimeConfig:
    process_fps: float = 6.0
    idle_fps: float = 2.0
    motion_gate: bool = True
    motion_thresh: float = 0.002
    keepalive_detect_s: float = 5.0
    clip_buffer: bool = True
    clip_pre_s: float = 6.0
    clip_post_s: float = 4.0
    clip_width: int = 960
    state_dir: str = "state"
    events_dir: str = "events"
    save_interval_s: float = 300.0
    scene_check_interval_s: float = 60.0
    api_host: str = "0.0.0.0"
    api_port: int = 8088
    webhook_url: Optional[str] = None
    webhook_timeout_s: float = 3.0
    traffic_side: str = "left"            # Pakistan: drive on the left -> roundabouts clockwise


ROAD_PROFILES: dict[str, dict[str, dict[str, Any]]] = {
    "auto": {},
    # Divided carriageways: tolerate a higher violation rate before calling a cell two-way.
    "main_road": {"flow": {"two_way_min_frac": 0.15, "pool_body_sizes": 1.2}},
    # Narrow society streets: anything that looks two-way is two-way; demand more evidence.
    # Pool across the whole carriageway (~3.5 vehicle widths ~ 6 m) so kerb-side cells are two-way too.
    "street": {"flow": {"two_way_min_frac": 0.03, "pool_body_sizes": 3.5},
               "judge": {"min_wrong_path_bodies": 7.0, "min_wrong_cells": 4}},
    "roundabout": {"flow": {"one_way_frac": 0.75}},
}


@dataclass
class CameraConfig:
    id: str
    url: str = ""
    name: str = ""
    enabled: bool = True
    road_profile: str = "auto"
    zones: list = field(default_factory=list)
    overrides: list = field(default_factory=list)
    flow: dict = field(default_factory=dict)
    judge: dict = field(default_factory=dict)


@dataclass
class SystemConfig:
    detector: DetectorConfig = field(default_factory=DetectorConfig)
    tracker: TrackerConfig = field(default_factory=TrackerConfig)
    flow: FlowConfig = field(default_factory=FlowConfig)
    judge: JudgeConfig = field(default_factory=JudgeConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    cameras: list = field(default_factory=list)   # list[CameraConfig]

    def camera_flow(self, cam: CameraConfig) -> FlowConfig:
        return _merge(self.flow, ROAD_PROFILES.get(cam.road_profile, {}).get("flow", {}), cam.flow)

    def camera_judge(self, cam: CameraConfig) -> JudgeConfig:
        return _merge(self.judge, ROAD_PROFILES.get(cam.road_profile, {}).get("judge", {}), cam.judge)


def _merge(base, *overrides):
    out = copy.deepcopy(base)
    names = {f.name for f in fields(out)}
    for ov in overrides:
        for k, v in (ov or {}).items():
            if k not in names:
                raise ValueError(f"unknown config key {k!r} for {type(out).__name__}")
            setattr(out, k, v)
    return out


def _build(cls, data: dict | None):
    data = data or {}
    names = {f.name for f in fields(cls)}
    bad = set(data) - names
    if bad:
        raise ValueError(f"unknown keys for {cls.__name__}: {sorted(bad)}")
    return cls(**data)


def load_system_config(path: str) -> SystemConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    base_dir = os.path.dirname(os.path.abspath(path))
    det = raw.get("detector", {}) or {}
    if "classes" in det:
        det["classes"] = {int(k): v for k, v in det["classes"].items()}
    cfg = SystemConfig(
        detector=_build(DetectorConfig, det),
        tracker=_build(TrackerConfig, raw.get("tracker")),
        flow=_build(FlowConfig, raw.get("flow")),
        judge=_build(JudgeConfig, raw.get("judge")),
        runtime=_build(RuntimeConfig, raw.get("runtime")),
    )
    cams = list(raw.get("cameras", []) or [])
    cam_dir = raw.get("cameras_dir")
    if cam_dir:
        cam_dir = cam_dir if os.path.isabs(cam_dir) else os.path.join(base_dir, cam_dir)
        for p in sorted(glob.glob(os.path.join(cam_dir, "*.y*ml"))):
            with open(p, "r", encoding="utf-8") as f:
                c = yaml.safe_load(f)
            cams.extend(c if isinstance(c, list) else [c])
    seen = set()
    for c in cams:
        cc = _build(CameraConfig, c)
        if cc.id in seen:
            raise ValueError(f"duplicate camera id {cc.id}")
        if cc.road_profile not in ROAD_PROFILES:
            raise ValueError(f"camera {cc.id}: unknown road_profile {cc.road_profile}")
        seen.add(cc.id)
        cfg.cameras.append(cc)
    return cfg


def config_to_dict(cfg: SystemConfig) -> dict:
    return asdict(cfg)
