# Automatic CCTV vehicle speed estimation

Feature branch: `feature/automatic-speed-estimation`

This FYP prototype first checks whether this camera view has usable saved calibration. It reuses that mapping when valid; otherwise it obtains vehicle geometry and fits a local road mapping. It then calculates provisional speeds from tracked ground motion. Approximate car dimensions supply the physical scale; camera-specific filters restrict the usable road region.

**Status: experimental inference prototype. Real-world speed accuracy has not been validated.** The displayed ranges show sensitivity to assumed dimensions and calibration-track selection; they are not confidence intervals or guaranteed error bounds.

## Automatic workflow

Run one command from this feature folder:

```powershell
python -m pip install -r requirements.txt
python workflow.py --video 'C:\path\to\A3_ch14_20260822105146_20260822110347.mp4' --camera-id A3-CH14
```

The default interval is 150–210 seconds. Use `--start` and `--duration` for another interval. The workflow performs these steps:

1. Read the video and compare five sampled views. If movement or insufficient visual evidence makes the camera view uncertain within the interval, stop without reporting speeds.
2. Look up this camera ID's calibration. Check resolution, model and calculation settings, file integrity, and visual alignment to the saved camera reference.
3. Obtain tracking and vehicle ground positions for this video interval. Exact matching saved inference outputs are reused after checking the source SHA-256, interval, configuration and artifact hashes. Otherwise the detection/tracking and vehicle-geometry models run automatically.
4. If the calibration check missed, fit and save new local road mappings. If it hit, skip calibration fitting and reuse the saved mappings.
5. Calculate experimental speeds inside the calibrated road support, apply consistency screens, and save the tables, reports, charts and annotated video.

Fresh video intervals still need vehicle positions even when the road mapping is cached. That geometry inference locates the vehicles; it does not refit the road calibration. Speed itself is calculated from mapped movement and elapsed time.

The original 150–210 s experiment includes hash-verified inference inputs, so that exact footage can run on CPU without repeating GPU inference. For footage with no matching saved inputs, install `requirements-inference.txt` or use the [automatic GPU workflow notebook](workflow_notebook/automatic_workflow.ipynb). FFmpeg is required for rendering. Add `--no-render` to produce speed tables and workflow reports without video regeneration.

Calibration persists under `outputs/calibration_cache/`; reusable inference inputs under `outputs/inference_cache/`; each invocation writes a new `outputs/runs/<run-id>/` folder. Its `workflow_report.json` records whether calibration and inference were reused, recalculated, or unavailable. `--work-dir` chooses another working directory, `--cache-dir` chooses persistent calibration storage, and `--recalibrate` forces a new fit.

The visual check uses ORB features and robust alignment. Uncertain matches trigger a fresh calibration rather than reuse. Five samples cannot rule out brief camera movement between them. For new camera layouts, review the current left/right carriageway split and road-region filters; this prototype does not automatically reconstruct arbitrary roads. Poor calibration evidence produces an unavailable result, not a guessed speed. Camera angle and road length are represented through the projective mapping and assumed metric scale, not independently measured road dimensions.

See the [workflow verification records](output/workflow_demo/README.md) for the tested calibration-missing and calibration-present paths.

## View the completed experiment

The saved experiment covers **150–210 seconds** of `A3_ch14_20260822105146_20260822110347.mp4`, at the source rate of **25 FPS**. The full 12-minute footage has not been processed for speeds.

- [Output gallery and file guide](output/README.md)
- [Open/download the 60-second annotated video](output/experimental_speed_preview.mp4)
- [Qualified speed estimates, CSV](output/qualified_experimental_speeds.csv) · [JSON for application integration](output/vehicle_speed_estimates.json)
- [All candidate estimates and rejection reasons](output/experimental_speeds.csv)
- [Detailed methodology and experiment review](calibration_review.md)

![Experimental speed example; values are provisional](output/speed_example.jpg)

| Track ID | Carriageway | Experimental km/h | Sensitivity range, km/h | Fitted source-video interval |
|---|---|---:|---:|---|
| 1 | Right | 19.4 | 13.8–22.5 | 150.0–151.8 s |
| 115 | Left | 27.4 | 18.2–31.6 | 172.8–174.4 s |
| 147 | Left | 40.1 | 28.2–46.2 | 177.2–178.6 s |
| 175 | Left | 48.6 | 34.6–55.9 | 184.4–185.8 s |

These are average speeds over short qualifying track spans. Tracker IDs are not verified unique vehicle identities. Four of eight candidate spans passed internal consistency screening. Yellow labels appear only within accepted spans; grey boxes indicate tracked objects without an accepted speed.

## How it works

1. **Detection and tracking:** pretrained YOLO11s and ByteTrack process all 1,500 frames of the selected minute. Cars, motorcycles, buses and trucks are tracked; this speed experiment uses passenger-car hypotheses only.
2. **Vehicle geometry:** a pretrained UrbanOmniDetect model predicts eight projected cuboid corners. Hungarian assignment matches predictions to baseline car tracks using bounding-box overlap. The model processes 197 selected frames and produces 224 matched observations across 12 tracker IDs.
3. **Local road mapping:** 93 usable ground footprints remain after clipping, size, confidence and road-region filters. Motion resolves the longitudinal edge pair. A robust projective fit uses rectangle angles, opposite-edge parallelism, aspect ratio and within-track size consistency. Each carriageway receives its own mapping and arbitrary local origin.
4. **Metric scale and motion:** nominal dimensions are **4.5 m long × 1.8 m wide**. Ground corners are projected before their centre is averaged. A robust linear trajectory fit gives distance per second, converted to km/h.
5. **Screening and sensitivity:** geometry, size stability, trajectory fit and speed drift determine which spans receive labels. Dimension scenarios use lengths 3.2–5.2 m and widths 1.45–2.0 m; additional fits vary calibration tracks where possible. The reported minimum and maximum form the sensitivity envelope.

The road rises toward a crest. The local planar mappings apply only to footprint-supported regions and do not calibrate the entire road. Vehicles' actual make/model dimensions are not identified. This is an independent prototype inspired by [Sochor et al. (2017)](https://arxiv.org/abs/1702.06451), rather than a reproduction of their rendered, vehicle-model-specific bounding-box alignment method.

## Folder structure

```text
Intelligent Traffic management/
  automatic speed estimation/
    README.md
    requirements.txt                 Local CPU dependencies
    requirements-kaggle.txt          Optional Kaggle client
    requirements-inference.txt       Optional local model inference
    workflow.py                     Automatic lookup, inference, calibration and speed entry point
    camera_cache.py                 Camera-view checks and persistent calibration storage
    workflow_notebook/              Single-entry GPU Kaggle workflow
    notebook/                       Stage 1 tracking notebook, source and metadata
    geometry_notebook/              Stage 2 vehicle-geometry notebook and source
    speed_notebook/                 Stage 3 CPU speed notebook and metadata
    calibrate_speed.py              Projective fitting, speed calculation and screening
    render_speed.py                 Road overlay, charts and annotated video
    test_calibration_math.py         Synthetic checks with known geometry and speed
    test_workflow.py                 Cache reuse, invalidation and failure behavior checks
    build_notebook.py               Convert percent-cell Python to a notebook
    prepare_speed_notebook.py       Embed current calibration/renderer in stage 3
    build_workflow_notebook.py       Package the automatic workflow for Kaggle
    manage.py                       Kaggle status and output download
    experiments.json                Non-secret notebook references and snapshot versions
    calibration_review.md           Results, assumptions and limitations
    output/                         Committed experiment snapshot and calculation inputs
    outputs/                        Ignored downloads and newly generated local results
```

`output/` contains the reviewed Kaggle speed result and small saved geometry/tracking inputs. It is tracked so results remain visible on this branch. `outputs/` is created at runtime to keep new runs separate from the saved snapshot. Original CCTV footage, credentials, downloaded model weights and notebook logs are excluded.

## Reproduce the calculation locally

Use Python 3.13, open a terminal in this feature folder, and install the local dependencies:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python test_calibration_math.py
python calibrate_speed.py
```

The calibration defaults to the committed `output/inputs/geometry/` observations and writes fresh results to `outputs/speed_experiment/`. It needs neither the original video nor a GPU nor a Kaggle login. If `outputs/geometry/` exists after a download, those newer observations take precedence.

To regenerate the video and charts, set the path to your original footage. FFmpeg must be on `PATH`, and OpenCV must be able to decode its HEVC stream:

```powershell
$env:FYP_SPEED_SOURCE = 'C:\path\to\A3_ch14_20260822105146_20260822110347.mp4'
python render_speed.py
```

The standalone renderer expects tracks from the same video and interval. `workflow.py` sets its source, interval and input paths automatically. When using the renderer directly, `FYP_START_S` and `FYP_DURATION_S` override the default 150–210 s interval; pointing it at unrelated footage does not perform detection.

Optional environment variables override the default locations:

| Variable | Purpose |
|---|---|
| `FYP_SPEED_ROOT` | Feature working root; defaults to this folder |
| `FYP_GEOMETRY_DIR` | Folder containing `observations.json` and `geometry_run_report.json` |
| `FYP_SPEED_OUTPUT` | Destination for newly calculated speed artifacts |
| `FYP_BASELINE_TRACKS` | Tracking CSV for the renderer |
| `FYP_SPEED_SOURCE` | Original video path, required for rendering |
| `FYP_START_S`, `FYP_DURATION_S` | Source interval for inference and rendering |

## Kaggle workflow

The existing dataset and notebooks are private and require the owner's Kaggle access:

| Stage | Notebook | Saved version | Compute |
|---|---|---:|---|
| Tracking | [Vehicle tracking baseline](https://www.kaggle.com/code/hayyanfaisal/fyp-cctv-vehicle-tracking-baseline) | 1 | GPU T4 |
| Geometry | [Automatic vehicle geometry](https://www.kaggle.com/code/hayyanfaisal/fyp-cctv-automatic-vehicle-geometry) | 2 | GPU T4 |
| Speed | [Experimental speed estimation](https://www.kaggle.com/code/hayyanfaisal/fyp-cctv-experimental-speed-estimation) | 2 | CPU |
| Automatic workflow | [Camera calibration workflow](https://www.kaggle.com/code/hayyanfaisal/fyp-cctv-camera-calibration-workflow) | 1 | GPU T4 |

The automatic notebook is the single-entry workflow. It embeds the current scripts, attaches the private video, runs fresh inference when inputs are missing, verifies calibration creation, and verifies a second run reuses it without fitting. Version 1 completed successfully on Kaggle with fresh GPU inference and identical qualifying speed results on the cached run; the [saved verification records](output/workflow_demo/README.md) include both reports. Use the three individual notebooks for inspecting or developing a particular stage.

Kaggle working storage is temporary across sessions. Download `workflow_outputs/calibration_cache/` with the notebook outputs and preserve it, or mount a saved copy into a later session and copy it into the writable cache directory before running. Local `outputs/calibration_cache/` remains available across local invocations. Cache files remain versioned against the calculation code and settings; changing them can require recalibration.

Private source: [A3 CH14 dataset](https://www.kaggle.com/datasets/hayyanfaisal/fyp-cctv-a3-ch14-speed-estimation). API credentials are read from your user profile or environment; no token belongs in this repository or a notebook.

Install the optional client, then inspect or download a completed run:

```powershell
python -m pip install -r requirements-kaggle.txt
python manage.py status --experiment speed
python manage.py status --experiment workflow
python manage.py download --experiment workflow
python manage.py download --experiment baseline
python manage.py download --experiment geometry
```

Downloads go to ignored `outputs/` and fetch the latest successful notebook output. The committed `output/` snapshot retains the versions listed above. Downloading newer tracking or geometry can therefore change a subsequent local result.

To update the notebook sources and submit new Kaggle runs:

```powershell
python build_notebook.py notebook/baseline.py
python build_notebook.py geometry_notebook/extract_geometry.py
python prepare_speed_notebook.py
kaggle kernels push -p notebook
# Wait for tracking to finish successfully, then:
kaggle kernels push -p geometry_notebook
# Wait for geometry to finish successfully, then:
kaggle kernels push -p speed_notebook
# Or rebuild and submit the single-entry automatic workflow:
python build_workflow_notebook.py
kaggle kernels push -p workflow_notebook
```

The metadata files target the owner's existing private notebooks and preserve their dataset and notebook dependencies. Change those references if running in another Kaggle account. Stage 3 reuses saved inference outputs without repeating GPU inference. Its embedded scripts must be rebuilt with `prepare_speed_notebook.py` after editing calibration or rendering code.

## Checks and limitations

Synthetic checks recover known 4.5 × 1.8 m rectangles and 14.4 km/h motion from a known projection, verify proportional changes with dimension scale, and check subpixel corner noise. Local and Kaggle runs agreed on the four accepted IDs, with nominal speeds within 0.05 km/h. The saved H.264 video contains 1,500 frames at 25 FPS and lasts 60 seconds.

Run `python -m unittest test_workflow -v` for behavior checks: reuse without calling the fitter; camera movement, zoom, resolution/settings changes and corrupt-cache rejection; input provenance; unavailable speeds outside calibrated support; empty results replacing stale data; and stopping on an uncertain within-clip view. The saved local workflow demonstration also runs the actual footage twice and requires identical qualifying results while forbidding calibration fitting in the second run.

These establish calculation consistency and reproducibility, not measured accuracy. There are no reference speed labels, measured road distances or scene-specific detection/keypoint labels. Wrong hidden corners, track associations, road grade, lens distortion and unsuitable dimension assumptions can cause errors outside the displayed range. Left-carriageway held-out checks measure predicted-rectangle consistency only; the right side has no held-out calibration tracks. No detection AP, tracking accuracy or real-speed error is claimed.

Next steps are to identify specific vehicle models and dimensions, independently measure selected distances or speeds, evaluate additional segments and road regions, and report per-vehicle speed errors and coverage before deploying this feature.

## Research and model attribution

- Sochor, Juránek and Herout (2017), [Traffic Surveillance Camera Calibration by 3D Model Bounding Box Alignment for Accurate Vehicle Speed Measurement](https://arxiv.org/abs/1702.06451).
- Turkcan, Gumaste and Kostic (2026), [UrbanOmniDetect: Calibration-Free View-Agnostic Monocular 3D Object Detection for Urban Scenes](https://github.com/mkturkcan/urbanomnidetect). The pretrained checkpoint is downloaded from [the authors' model repository](https://huggingface.co/mehmetkeremturkcan/UrbanOmniDetect), revision `2701a2eec9a73afb5ffd852740d125dfcd065ce5`, file `checkpoints/urbanomnidetect_yolo11x-p2_1920.pt`. SHA-256 is recorded in the saved geometry report. The upstream repository states AGPL-3.0 licensing.
- [Ultralytics](https://github.com/ultralytics/ultralytics) supplies YOLO11 and the ByteTrack integration. Notebook inference uses version `8.4.175`. Upstream software and models retain their own licenses; weights are not committed here.
