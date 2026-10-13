"""Vehicle detector backends.

Default: Ultralytics YOLO (YOLO11 / YOLO26 / YOLOv8 weights, or an exported
TensorRT .engine for best throughput). Frames from many cameras are batched
into one forward pass. Only vehicle classes are returned.

Export once for production (FP16 TensorRT, dynamic batch):
    wrongway export-model --model yolo11s.pt --imgsz 640 --batch 16
"""
from __future__ import annotations

import logging

import numpy as np

from .config import DetectorConfig

log = logging.getLogger(__name__)


class Detector:
    def infer(self, frames: list[np.ndarray]) -> list[np.ndarray]:
        """Return one (N, 6) array [x1, y1, x2, y2, score, cls] per frame, in frame pixels."""
        raise NotImplementedError


class UltralyticsDetector(Detector):
    def __init__(self, cfg: DetectorConfig):
        from ultralytics import YOLO  # lazy: optional dependency

        self.cfg = cfg
        self.model = YOLO(cfg.model, task="detect")
        self.classes = sorted(int(c) for c in cfg.classes)
        self.is_engine = str(cfg.model).endswith(".engine")
        log.info("detector: %s imgsz=%d half=%s device=%s classes=%s", cfg.model, cfg.imgsz, cfg.half,
                 cfg.device, self.classes)

    def infer(self, frames):
        if not frames:
            return []
        out = []
        bs = self.cfg.batch_size
        for i in range(0, len(frames), bs):
            chunk = frames[i:i + bs]
            res = self.model.predict(chunk, imgsz=self.cfg.imgsz, conf=self.cfg.conf, iou=self.cfg.iou,
                                     classes=self.classes, half=self.cfg.half, device=self.cfg.device,
                                     verbose=False)
            for r in res:
                b = r.boxes
                if b is None or len(b) == 0:
                    out.append(np.zeros((0, 6), np.float32))
                    continue
                xyxy = b.xyxy.cpu().numpy()
                conf = b.conf.cpu().numpy()[:, None]
                cls = b.cls.cpu().numpy()[:, None]
                out.append(np.hstack([xyxy, conf, cls]).astype(np.float32))
        return out


class NullDetector(Detector):
    """For deployments that feed detections/tracks from the existing AI pipeline."""

    def infer(self, frames):
        return [np.zeros((0, 6), np.float32) for _ in frames]


def build_detector(cfg: DetectorConfig) -> Detector:
    if cfg.backend == "ultralytics":
        return UltralyticsDetector(cfg)
    if cfg.backend == "none":
        return NullDetector()
    raise ValueError(f"unknown detector backend {cfg.backend}")


def export_model(model: str, imgsz: int = 640, batch: int = 16, half: bool = True, fmt: str = "engine",
                 device: str = "0") -> str:
    from ultralytics import YOLO

    m = YOLO(model)
    return m.export(format=fmt, imgsz=imgsz, half=half, dynamic=True, batch=batch, device=device, simplify=True)
