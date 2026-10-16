# Calibration patterns across vehicles

This analysis describes the completed tests. It does not retune the model or turn the reserved clips into calibration references.

## What the Kia tests establish

1. Camera compatibility must be checked per clip. One recording session does not imply one fixed view: the development contact sheet shows changes in direction and framing. Most attempted shared maps fell back to the baseline because they lacked sufficient compatible references.
2. The strong motion vanishing-point constraint can amplify errors on short/noisy ground-corner tracks. On the 105 km/h development clip, it gives 136.7 km/h, while the unconstrained 2D temporal fit is about 106.1 km/h before transferred scale correction. The far-window fit is unstable on this clip, so a smaller window alone is not a reliable fix.
3. Correcting two template scales and averaging their independently fitted cameras reduced reserved MAE from 3.81 to 2.36 km/h. This uses eight known-speed Kia calibration passes and does not demonstrate dimension-only automatic accuracy.
4. The remaining worst error is 58 → 65.3 km/h. A fixed template correction does not resolve every view. When both templates share a bias, a small disagreement cannot certify accuracy. The disagreement field is a diagnostic, not an uncertainty bound.

| Geometry diagnostic (all 33; descriptive) | Clips | MAE | Worst error | Within ±2 |
|---|---:|---:|---:|---:|
| fewer_than_20_usable_ground_observations | 9 | 2.60 | 5.37 | 3 |
| at_least_20_usable_ground_observations | 24 | 1.88 | 7.28 | 17 |
| radial_fit_at_bound | 15 | 2.49 | 7.28 | 8 |
| radial_fit_inside_bounds | 18 | 1.73 | 3.97 | 12 |

Counts alone do not establish why a particular estimate failed. Radial fits touching a bound can reflect an inadequate lens/shape model or an underconstrained fit; they are not measurements of true lens distortion.

## Remaining worst tests

| Clip | Group | Reference | Estimate | Error | Usable ground observations |
|---|---|---:|---:|---:|---:|
| [KiaSportage_58.MP4](videos/KiaSportage_58/speed.mp4) | reserved | 58.0 | 65.3 | +7.28 | 44 |
| [KiaSportage_100.MP4](videos/KiaSportage_100/speed.mp4) | reserved | 100.0 | 105.4 | +5.37 | 14 |
| [KiaSportage_68.MP4](videos/KiaSportage_68/speed.mp4) | reserved | 68.0 | 72.0 | +3.97 | 35 |
| [KiaSportage_98.MP4](videos/KiaSportage_98/speed.mp4) | reserved | 98.0 | 94.2 | -3.84 | 15 |
| [KiaSportage_93.MP4](videos/KiaSportage_93/speed.mp4) | reserved | 93.0 | 89.7 | -3.26 | 16 |

## Cross-check on the previous Mercedes recordings

These are additional development reruns of the same Mercedes clips, each excluding itself. They use the other Mercedes references; Kia reserved speeds are absent. The published original Mercedes results are preserved.

| Mercedes version | MAE | Within ±2 / 30 |
|---|---:|---:|
| previous_nested_hybrid | 2.38 | 19 |
| shared_flow | 2.72 | 15 |
| shared_trajectory | 3.04 | 15 |
| shared_trajectory_radial | 2.30 | 21 |
| shared_curve2 | 4.08 | 9 |
| shared_curve3 | 4.01 | 9 |

Shared lens-aware trajectory calibration gives a small Mercedes improvement; other shared maps are worse. This supports retaining version-specific evidence rather than replacing every camera with one calibration recipe.

## What remains to reach the tolerance

The next calibration version should fit only well-supported ground contacts, model lens/camera changes explicitly, and reuse a reference road map only where the correspondence is supported. Template-scale transfer should be tied to a recognized vehicle family. These tests do not yet demonstrate that those quality measures can guarantee ±2 km/h. More accurate ground-contact/keypoint evidence or independently measured road/camera references, followed by new reserved clips, are needed to verify that claim.

The current committed solution is the frozen geometry ensemble. No post-reserved correction, filename-speed shortcut or manual per-video adjustment was applied.

[Per-video geometry diagnostics](geometry_patterns.csv) · [Full report and all paired videos](README.md)
