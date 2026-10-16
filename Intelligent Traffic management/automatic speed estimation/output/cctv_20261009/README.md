# Two real CCTV cameras: calibration and full speed videos

Both supplied recordings were processed independently, with multi-car camera calibration followed by local speed estimation. **All 187,641 frames across 141 minutes 22.05 seconds are covered by the annotated speed outputs.** Each camera also has its own separate calibration video.

| Camera and full report | Complete recording | Calibration replay | Car track IDs with qualified speeds | Ordered speed parts |
|---|---:|---:|---:|---:|
| [Commercial II-01](commercial_ii_01/README.md) | 01:00:00 | 10 min | 306 | 6 |
| [K Block St 20 opposite side](k_block_st20/README.md) | 01:21:22 | 5 min | 355 | 9 |

Open either camera report for its calibration video, every speed-video segment, tables, maps and diagnostics. The parts preserve full source frame rates and complete source coverage. Single full-length speed files are also exported locally under the supplied CCTV folder's `output` directory.

**Accuracy is unverified.** These cameras have no independently measured speeds or road dimensions. Multiple cars improve geometric consistency and sample stability; they do not remove the unknown absolute scale of monocular footage. A 4.5 × 1.8 m nominal car supplies the metric scale. No Mercedes/Kia empirical speed correction or expected traffic speed was used. The requested ±1–2 km/h accuracy cannot be established on this material.

## What changed for these angles

- Commercial uses separate carriageway maps. Its left mapping is supported by 14 qualifying car tracks in 5 minutes; the right uses 21 tracks in 10 minutes. Adding a soft fleet-size constraint improved internal calibration consistency and car-subset stability.
- K Block separates the near approach from the cross street. Its first 2.5 FPS geometry run missed most brief passes. The revised 10 FPS run provides 18 near-approach and 14 cross-street calibration tracks within 5 minutes. The ordinary projective fit scores better there than the metric-prior variant, so it is retained.
- The pinned cuboid checkpoint's actual XY/corner convention is handled explicitly. Parked cars are excluded from calibration. Later inference uses the fixed road map to locate vehicles; it does not fit a new camera from each passing car.
- Local 2D speed windows support turning, acceleration and braking. Grey tracks lack a qualified speed. Passenger cars receive decimal km/h labels plus a secondary sensitivity range; other vehicle classes remain tracking-only.

See [the detailed pattern and pilot history](PATTERNS.md), [method and reproduction steps](../../cctv_method.md), [experiment summary](experiment_summary.json), [source hashes](source_inventory.json), [Kaggle provenance](provenance/kaggle_jobs.json), and [verification](verification.json). Raw source footage, API credentials and model weights are excluded from Git.
