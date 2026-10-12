# Experiment 2 — experimental automatic geometry and speed

The pipeline now produces provisional speeds from learned 3D vehicle footprints, with a separate local road mapping for each carriageway. It uses no manually clicked calibration points or measured road lengths. It does use explicit approximate vehicle-size priors and image-region filters for this camera.

The [automatic workflow](README.md#automatic-workflow) now checks for a saved calibration for the camera view, fits it only when missing or invalid, then calculates speeds. The original experiment below remains the saved baseline result; [workflow verification records](output/workflow_demo/README.md) document the subsequent cache and orchestration checks.

## Results on the same one-minute clip

The larger UrbanOmniDetect model processed 197 selected video frames on a Tesla T4, matched 224 geometry observations to 12 existing tracker IDs, and took 109.6 seconds for geometry extraction. The mapping stage retained 93 qualifying footprints. Eight track spans had enough geometry for an experimental speed calculation; four passed the geometry and temporal consistency screens.

| Track | Carriageway | Nominal experimental speed | Sensitivity envelope | Fitted video interval |
|---|---|---:|---:|---|
| 1 | Right | 19.4 km/h | 13.8–22.5 km/h | 150.0–151.8 s |
| 115 | Left | 27.4 km/h | 18.2–31.6 km/h | 172.8–174.4 s |
| 147 | Left | 40.1 km/h | 28.2–46.2 km/h | 177.2–178.6 s |
| 175 | Left | 48.6 km/h | 34.6–55.9 km/h | 184.4–185.8 s |

These are averages over short qualifying spans, not continuously measured instantaneous speeds or verified unique vehicle counts. Four other candidate spans failed because their predicted vehicle size, trajectory or speed changed too much across the fitted interval. The annotated preview displays speed only for qualifying spans; other tracked objects have grey boxes.

## What the range means

The nominal mapping assumes a car length of 4.5 m and width of 1.8 m. Alternative fits vary length from 3.2–5.2 m and width from 1.45–2.0 m. Additional fits vary the subset of calibration tracks where there are enough tracks to do so. The displayed envelope is the minimum and maximum speed across those fits.

This is a sensitivity envelope, not a statistical confidence interval or an accuracy guarantee. It does not bound errors from wrong predicted ground corners, lens distortion, road grade, incorrect track associations, or unsuitable vehicle dimensions. Actual make/model dimensions have not been recognized or confirmed. No independent measured speed or road distance has been used for validation.

## How the mapping is estimated

The model predicts the eight projected corners of a vehicle cuboid. The released checkpoint's bottom-corner indices are resolved by voting across detections, rather than assuming the ordering in the paper text. This experiment consistently selected indices 0–3.

Predictions are associated with baseline car tracks. Convex ground footprints inside the selected near/middle road region are retained; small, clipped and weak observations are filtered. Vehicle motion identifies the longitudinal edge pair. A four-parameter projective rectification then minimizes rectangle-angle error, opposite-edge nonparallelism, mismatch to the assumed length/width ratio, and changes in a given vehicle's inferred length over time. Each calibration track receives balanced weight. The nominal dimensions establish metric scale; the two carriageways have separate arbitrary local origins.

Speeds come from a robust linear fit of the mapped ground-footprint centre against the video's timestamps. Geometry and temporal consistency checks decide whether to display each result. The road mapping is limited to the footprint-supported local region; it does not calibrate the crest or every visible road surface.

The left mapping used five fitting track IDs and three held-out track IDs for predicted-footprint consistency. Median right-angle error was approximately 3.1° on fitting footprints and 2.2° on the held-out footprints. This checks internal geometry consistency, not physical road distances or speed accuracy. The right mapping had only three fitting IDs and no held-out track check, so its evidence is more limited.

## Checks performed

Synthetic tests recovered known 4.5 × 1.8 m rectangles from a known perspective projection and recovered a known 14.4 km/h motion. A 20% dimension-scale change produced the corresponding 20% speed change. Subpixel corner-noise tests stayed within 5% in that synthetic case. These tests validate the calculation under its assumptions; they do not establish real-footage accuracy.

The model outputs, road-grid overlay, speed chart and annotated video were visually reviewed. Dataset and experiment notebooks are private. Model checkpoint revision and SHA-256 are recorded in the geometry and speed reports.

The final CPU speed notebook (version 2) completed on Kaggle. Its four qualifying IDs matched the local calculation, and nominal speeds agreed within 0.05 km/h. This is a reproducibility check, not comparison to true vehicle speeds. The downloaded H.264 preview was verified as 60 seconds, 1,500 frames and 25 FPS; experimental labels appear in 159 frames. The reviewed Kaggle artifacts are committed under [`output/`](output/README.md), together with the small inputs needed for CPU recalculation. New runs write to the ignored `outputs/` directory.

## Reproduce and inspect

- Geometry notebook: https://www.kaggle.com/code/hayyanfaisal/fyp-cctv-automatic-vehicle-geometry
- Speed notebook: https://www.kaggle.com/code/hayyanfaisal/fyp-cctv-experimental-speed-estimation
- Saved preview: [experimental_speed_preview.mp4](output/experimental_speed_preview.mp4)
- Saved road overlay: [road_mapping.jpg](output/road_mapping.jpg)
- Qualified results: [qualified_experimental_speeds.csv](output/qualified_experimental_speeds.csv)
- App-friendly qualified results: [vehicle_speed_estimates.json](output/vehicle_speed_estimates.json)
- Full candidate diagnostics: [experimental_speeds.csv](output/experimental_speeds.csv)

The speed notebook reuses saved geometry and tracking outputs and runs on CPU, avoiding repeated GPU inference. Locally, `calibrate_speed.py` can use the committed geometry observations without a download. Set `FYP_SPEED_SOURCE` to the original video before running `render_speed.py`. See the [feature README](README.md) for dependencies, commands and optional input overrides.

## Next work

Improve coverage and shorten the dimension range by identifying usable vehicle models and applying their actual geometry. Test additional footage segments and road-grade regions. Independently measure selected road distances or vehicle speeds, then report per-vehicle and per-region error. The full 12-minute video has not yet been processed for speeds.

## Research attribution

- Sochor, Juránek and Herout (2017), *Traffic Surveillance Camera Calibration by 3D Model Bounding Box Alignment for Accurate Vehicle Speed Measurement*: https://arxiv.org/abs/1702.06451
- Turkcan, Gumaste and Kostic (2026), *Calibration-Free View-Agnostic Monocular 3D Object Detection for Urban Scenes*, CVPR Workshops, pp. 786–795: https://github.com/mkturkcan/urbanomnidetect. The pretrained UrbanOmniDetect checkpoint is used; the repository states AGPL-3.0 licensing. Calibration and speed-fitting code here is independently implemented.

This prototype uses learned cuboids and class-level size priors. It does not reproduce Sochor et al.'s fine-grained vehicle classification and exact rendered vehicle-model alignment.
