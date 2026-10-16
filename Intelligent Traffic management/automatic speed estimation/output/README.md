# Experimental speed-estimation outputs

The latest [Kia Sportage report](kia_validation/README.md) adds 33 individual tests and **66 calibration/speed videos**. Eight clips supplied development calibration; the method was frozen before evaluating 25 reserved clips. Reserved MAE improves from **3.81 to 2.36 km/h**, with **13/25 within ±2 km/h** and worst error **7.28 km/h**. These are reference-assisted, vehicle-specific results; the requested tolerance is still not met across all clips.

The earlier [Mercedes calibration research report](calibration_comparison/README.md) compares 18 calibration/model versions and 20 fusion configurations, with a new pair of videos for every Mercedes clip. The selected hybrid's development result is approximately **2.38 km/h MAE, 19/30 within ±2 km/h, and no error above 10 km/h**. It uses other labelled reference passes while excluding each test's own speed. The remaining worst error is about 8.3 km/h.

This folder contains the completed Kaggle experiments. The original CCTV snapshot covers source-video seconds **150–210**, **25 FPS**, 1,500 frames. Tracking notebook v1, geometry v2 and CPU speed v3 produced its current artifacts. See [the feature README](../README.md) for reproduction and limitations.

The [automatic-workflow verification records](workflow_demo/README.md) demonstrate calibration creation when missing and reuse on the next run. The main gallery below preserves the original reviewed experiment.

Videos have been updated to show one decimal speed estimate and to separate [calibration review](calibration_preview.mp4) from [speed estimation](experimental_speed_preview.mp4). [Mercedes validation results](mercedes_validation/README.md) are kept separately from the original CCTV experiment.

The completed [Mercedes report](mercedes_validation/README.md) includes before/after results for all 30 clips and **60 videos**, one calibration and one speed video per clip. Three pilots supplied reference calibration; 27 clips were held out. Their final mean absolute error is **9.41 km/h**, with **6/27** within ±2 km/h and a worst error of **30.78 km/h**. **The requested accuracy target is not met.** See the [failure investigations](mercedes_validation/diagnostics/README.md) for further calibration and model attempts that were not promoted.

**All speeds are provisional. Real speed accuracy is unvalidated. Ranges are dimension-and-fit sensitivity envelopes, not confidence intervals.** Four of eight candidate spans passed internal consistency screening; the full 12-minute video has not been processed for speeds.

[Open/download the 60-second speed video](experimental_speed_preview.mp4) and [calibration video](calibration_preview.mp4) (1280 × 720, H.264). Yellow labels show decimal speed estimates during qualifying spans; grey boxes have no accepted speed. Calibration videos display predicted nodes and the fitted road grid without speed labels.

## Annotated example

![Experimental speed labels](speed_example.jpg)

## Local road mapping

The 5 m grid is a hypothesis under assumed car dimensions. The two carriageways use separate local mappings and origins. Only footprint-supported regions are drawn.

![Experimental local road mapping](road_mapping.jpg)

## Dimension and fit sensitivity

![Experimental speed estimates with sensitivity envelopes](speed_sensitivity.jpg)

## Mapped trajectories

![Qualifying trajectories in separate local road coordinates](birdseye_trajectories.jpg)

## Data and reports

| File | Contents |
|---|---|
| [qualified_experimental_speeds.csv](qualified_experimental_speeds.csv) | Four estimates passing the internal screens, ranges and fitted intervals |
| [vehicle_speed_estimates.json](vehicle_speed_estimates.json) | Qualified results for application integration, including `accuracy_validated: false` |
| [experimental_speeds.csv](experimental_speeds.csv) | All eight candidates, including failures and rejection reasons |
| [calibration.json](calibration.json) | Per-carriageway projective mappings and geometry diagnostics |
| [filtered_ground_footprints.json](filtered_ground_footprints.json) | The 93 footprints used for local fitting and speed candidates |
| [speed_run_report.json](speed_run_report.json) | Dimensions, scenarios, model hash, screening totals and limitations |
| [render_report.json](render_report.json) | Preview frame rate, duration and number of labelled frames |
| [manifest.json](manifest.json) | Run provenance and file checksums for this snapshot |
| [inputs/geometry/observations.json](inputs/geometry/observations.json) | 224 matched model observations, allowing CPU recalibration without footage |
| [inputs/geometry/geometry_run_report.json](inputs/geometry/geometry_run_report.json) | Geometry-model revision, hash, corner order and inference summary |
| [inputs/tracking/tracks.csv](inputs/tracking/tracks.csv) | Original per-frame detection and tracking rows for this minute |
| [inputs/tracking/track_summary.csv](inputs/tracking/track_summary.csv) | Baseline track summaries |
| [inputs/tracking/run_report.json](inputs/tracking/run_report.json) | Source metadata, detector/tracker settings and software versions |

The original CCTV recording and model weights are excluded. Regenerated local results go to the separate ignored `../outputs/` directory. These saved outputs demonstrate the prototype and must not be treated as ground-truth speed labels.
