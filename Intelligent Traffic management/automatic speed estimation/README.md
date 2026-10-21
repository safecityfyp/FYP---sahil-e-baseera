# Automatic vehicle speed estimation

Deployment branch: **`feature/speed-estimation`**. This folder contains the CCTV runtime: extract vehicle tracks, calibrate the camera, estimate speed, and render separate calibration/speed videos.

The complete research history, Mercedes/Kia tests, Kaggle notebooks, screenshots, reports and generated videos are on [feature/experiments/speed-estimtaion](https://github.com/safecityfyp/FYP---sahil-e-baseera/tree/feature/experiments/speed-estimtaion/Intelligent%20Traffic%20management/automatic%20speed%20estimation). Start with this branch to use or deploy the feature.

## Files you use

| File/folder | Purpose |
|---|---|
| `extract_tracks.py` | Detect vehicles, track them and save ground geometry/timestamps. |
| `calibrate.py` | Compare three road mappings per region and save the selected calibration. |
| `estimate_speed.py` | Load calibration and calculate decimal km/h from ground motion. |
| `render_video.py` | Export a calibration replay and annotated speed videos. |
| `download_models.py` | Fetch and verify the two pretrained checkpoints. |
| `speed_estimation/` | Shared runtime code; keep this package with the commands. |
| `configs/cameras.json` | Source identities, road regions and sampling settings. |
| `calibrations/` | Frozen mappings for the two supplied CCTV recordings. |
| `output/` | Local run outputs; its guide links to the archived output gallery. |

## Install

Use Python 3.13. Open a terminal in this folder. Calibration, speed calculation and rendering from existing measurements need only the CPU dependencies:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

For fresh vehicle/geometry extraction, also install the inference dependencies and download the models. A compatible GPU speeds up extraction; `--device cpu` is also supported.

```powershell
python -m pip install -r requirements-inference.txt
python download_models.py --output models
```

Rendering additionally needs **FFmpeg and FFprobe on PATH**. Source videos and model weights are stored locally. No Kaggle account or external LLM key is required by the runtime. On Linux/macOS, activate the virtual environment with `source .venv/bin/activate`.

## Run

The example below uses the already-configured Commercial II-01 recording. Replace its local path with the location of that recording. For another camera or recording, prepare a matching profile first using [camera configuration](docs/CONFIGURATION.md).

**1. Extract measurements.** Skip this step when you already have its measurement folder.

```powershell
python extract_tracks.py --video "C:\footage\NVR_ch6_main_20261009170002_20261009180000.mp4" --camera commercial_ii_01 --output output/commercial/measurements --device 0
```

**2. Calibrate the road.** Skip fitting when a valid camera-specific calibration already exists. Calibration considers the first 5, 10 and 15 minutes and freezes supported regions once enough moving cars and stability evidence are available.

```powershell
python calibrate.py --inputs output/commercial/measurements --camera commercial_ii_01 --output output/commercial/calibration
```

**3. Estimate speeds using the saved calibration.** This step reuses the mapping; it does not refit the camera from each car.

```powershell
python estimate_speed.py --inputs output/commercial/measurements --calibration output/commercial/calibration/calibration.json --output output/commercial/speed
```

The committed mapping for this supplied recording can also be used directly:

```powershell
python estimate_speed.py --inputs output/commercial/measurements --calibration calibrations/commercial_ii_01.json --output output/commercial/speed
```

**4. Render the two video outputs.** Speed video segments are ordered ten-minute parts, retaining source FPS. `--duration 30` makes a short preview; omit it for full source coverage.

```powershell
python render_video.py --video "C:\footage\NVR_ch6_main_20261009170002_20261009180000.mp4" --inputs output/commercial/measurements --calibration calibrations/commercial_ii_01.json --speed output/commercial/speed --output output/commercial/videos
```

For K Block, use camera ID `k_block_st20`, recording `D02_20261009160351.mp4`, its own output directory, and `calibrations/k_block_st20.json`. The two cameras' mappings cannot be interchanged.

Each `--inputs` accepts multiple measurement folders. To reuse the historical pilot/remainder measurements downloaded from the archive, pass both folders in source order:

```powershell
python estimate_speed.py --inputs "PATH_TO_PILOT" "PATH_TO_REMAINDER" --calibration calibrations/commercial_ii_01.json --output output/commercial/speed
```

## How it works

YOLO11s detects vehicles, ByteTrack supplies temporal identities, and the pinned UrbanOmniDetect checkpoint estimates projected car cuboids. Moving-car ground footprints calibrate each road region. Affine, projective and projective-with-metric-prior candidates are compared using held-out geometry and car-subset stability. Accepted mappings convert image ground points to experimental metres. Robust local trajectory fits then calculate speed, including turns and changes in speed.

The `.pt` files detect vehicles and their geometry. There is **no separately trained `speed.pt` or `calibration.pt`**. Calibration is JSON; speed is a geometric calculation. Exact checkpoint identities and notices are in [models/](models/README.md).

The fixed fleet prior is **4.5 m length × 1.8 m width**. Geometry/stability checks do not independently establish correct metres, and a decimal display does not imply 0.1 km/h accuracy. Speed accuracy on the supplied real CCTV recordings remains unverified because no independent passage-speed or measured road reference was provided. [Validation notes](docs/VALIDATION.md) describe the cleanup checks and link to the full studies.

## Results and tests

`estimate_speed.py` writes `speed_samples.csv`, `track_summary.csv`, compressed per-sample JSON and `speed_report.json`. Decimal speed is the primary value; secondary ranges describe sensitivity rather than a calibrated confidence interval. Only qualifying car footprints receive metric labels; other tracked classes remain tracking-only.

```powershell
python -m unittest discover -s tests -t . -v
```

To deploy, copy this feature folder, install its requirements, provide the model files, source recording and matching camera profile, then run the same commands. The runtime imports no archived experiment scripts or datasets.

Application code can call the CPU stages directly from this folder:

```python
from speed_estimation import calibrate, calculate

calibrate(["output/commercial/measurements"], "commercial_ii_01", "output/commercial/calibration")
calculate(["output/commercial/measurements"], "output/commercial/calibration/calibration.json", "output/commercial/speed")
```
