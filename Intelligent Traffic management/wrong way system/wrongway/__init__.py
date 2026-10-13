"""Naval Anchorage wrong-way vehicle detection.

Self-calibrating, per-camera wrong-way detection for heterogeneous CCTV networks.
Core idea: every camera learns its own traffic flow field from observed vehicle
trajectories (no manual calibration needed), then flags vehicles that travel
persistently against a confidently one-way flow.
"""

__version__ = "1.0.0"

from .config import SystemConfig, CameraConfig, load_system_config  # noqa: F401
from .engine import WrongWayEngine  # noqa: F401
