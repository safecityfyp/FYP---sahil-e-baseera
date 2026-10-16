# Long CCTV calibration and speed experiment

This experiment processes the two supplied 9 October 2026 recordings independently. Commercial II-01 is 60 minutes at 25 FPS. K Block St 20 opposite side is 81 minutes 22.05 seconds at 20 FPS. Source recordings and weights are kept out of Git; authorized source uploads and GPU notebooks are private on Kaggle.

## Workflow

1. Verify the recording hash and decode sequentially. Sample detections at 10 FPS, preserving source timestamps and recording decoded frame totals. ByteTrack identities reset explicitly at the pilot/remainder boundary.
2. Obtain moving-car ground footprints during the first 15 minutes. Commercial samples geometry at 2.5 FPS. K Block needs 10 FPS geometry because many cars cross its close view in less than two seconds. Parked cars and other vehicle classes cannot calibrate the camera.
3. Evaluate initial 5-, 10- and 15-minute windows. Fit a separate mapping for each selected road region. Commercial uses left/right carriageways; K Block separates the near approach and cross street. These polygons are manually selected, rather than automatically segmented.
4. Compare affine rectification, projective rectangle/rigidity fitting and projective fitting with a soft fleet-size prior. Select by held-out-track geometry, not by expected traffic speeds. Each independent car receives equal aggregate fitting weight. Refit the selected method on the calibration cars and compare six car subsets.
5. Freeze a region when sufficient independent cars and stable subsets support it. Later geometry inference locates cars under that fixed mapping; it does not repeatedly refit the road from each vehicle.
6. Map each car's ground corners into the road plane and average **after** projection. Estimate local 2D velocity with robust polynomial fits, using a 2.4-second window at Commercial or 1.2 seconds at K Block. Split tracks at region changes and long gaps. Quadratic derivatives require observations on both sides; endpoint windows use linear fits. Turning and slowing are supported without assuming a constant speed for an entire pass.
7. Check the view every five minutes, reject unsupported or inconsistent measurements, and render separate calibration replay and speed videos. Full source frame rates are retained; ten-minute speed segments preserve complete recording coverage on GitHub.

## What the calibration supplies

The mapping is an image-to-local-road homography, an approximate metre scale, supporting road region, predicted vehicle ground nodes, and geometric stability diagnostics. Its grid shows 5 m spacing under the dimension prior. It does not independently measure the entire road, camera height, focal length or physical camera pitch. The two road regions have independent arbitrary origins and orientations.

A nominal passenger-car length of 4.5 m and width of 1.8 m supplies scale. The additional metric fit applies those dimensions softly across multiple cars to reduce position-dependent scaling errors. This remains a fleet-size assumption: more cars reduce sampling variability, but cannot establish absolute scale without known dimensions or a measured road reference.

## Measurement screens and uncertainty

Cars receive decimal km/h labels only inside supported road areas. A local estimate needs at least four observations and adequate elapsed time, consistent footprint shape and size, limited trajectory residual, and tolerable calibration sensitivity. Broad car-size screens reject inferred lengths outside 2.5–6.5 m or widths outside 1.1–2.6 m. These are geometry screens, not limits on expected speed. Motorcycles, buses and trucks remain tracking-only because this checkpoint supplies passenger-car footprints.

The secondary range combines mapping changes from car subsets and uniform scale perturbations of 0.8 and 1.2. It is a sensitivity envelope, **not a confidence interval**, and does not cover every possible car-size, lens or road-surface error. A decimal display does not imply 0.1 km/h accuracy. These cameras have no independently measured speed references, so MAE and the requested ±1–2 km/h accuracy cannot be established here.

## Adaptations found during the pilot

- The pinned UrbanOmniDetect checkpoint returns eight XY points without per-keypoint confidence. In both recordings its lower ground face is corners 0–3. Current model documentation describes a different convention. The adapter determines the lower face from moving-track votes and retains native edge topology; it does not substitute roof corners or invent confidence values.
- K Block's first 2.5 FPS run captured too few points in brief passes. Increasing geometry to 10 FPS and using a shorter, movement-qualified calibration span supplied multiple independent cars in its first five minutes.
- The original projective objective fixes the overall median scale but can leave inferred car dimensions inconsistent with depth. The soft metric-prior candidate addresses this pattern; it is selected only where held-out geometry improves.
- Calibration support is clipped to road polygons for display. Curves, slopes, lens distortion, occlusion and camera movement remain material limits of local planar mapping.

## Research and implementation

[Sochor, Juranek and Herout (2017)](https://arxiv.org/abs/1702.06451) infer scene scale by aligning known rendered vehicle models. This implementation instead fits predicted footprint rectangles under an approximate fleet-size prior; it is not a reproduction of their model-specific alignment or their reported benchmark accuracy.

The pinned [UrbanOmniDetect checkpoint](https://huggingface.co/mehmetkeremturkcan/UrbanOmniDetect/tree/2701a2eec9a73afb5ffd852740d125dfcd065ce5) provides the projected cuboid corners. Its revision and SHA-256 are recorded with each run. The repository's current model card describes ground-contact homography mapping, but the pinned checkpoint's actual corner format is verified from saved observations. Ultralytics and the checkpoint retain their upstream license terms; weights are not redistributed here.

`build_cctv_notebooks.py` packages private pilot and full-stage jobs. `cctv_calibration.py` can reproduce fitting on CPU from saved pilot measurements. `cctv_speed.py` reproduces speed tables from those measurements and the remainder. `cctv_render.py` recreates the videos when the private source recording is available. `fetch_kaggle_outputs.py` downloads selected outputs without printing private artifact URLs.

```powershell
python -m unittest test_cctv -v
python cctv_calibration.py --input '<camera pilot folder>' --camera commercial_ii_01 --output outputs/cctv_reproduction/calibration
python cctv_speed.py --inputs '<pilot folder>' '<remainder folder>' --calibration outputs/cctv_reproduction/calibration/calibration.json --output outputs/cctv_reproduction/speed
python cctv_render.py --video '<original recording>' --inputs '<pilot folder>' '<remainder folder>' --calibration outputs/cctv_reproduction/calibration/calibration.json --speed outputs/cctv_reproduction/speed --output outputs/cctv_reproduction/videos
```

The [completed report](output/cctv_20261009/README.md) contains the full recordings, separate calibration replays, source measurements, method comparisons, pilot history and artifact verification. `build_cctv_report_notebook.py` independently reproduces the refined Commercial calibration and speed tables on Kaggle CPU with eleven tests. `cctv_render.py --encoder h264_nvenc` optionally uses a compatible local NVIDIA encoder; the default remains software H.264. Encoding does not change the frozen speed calculations.

Each region's selected track IDs and `calibration_end_s` define its fitting data. The saved calibration-footprint file covers the complete replay interval, which may include later observations from a region that froze earlier. Reproduction uses the per-region window/track filters in `cctv_calibration.py`.

Generated notebooks are templates for subsequent runs. The report provenance archives the exact source bundles used by each registered Kaggle version, including earlier pilots and the local final renderer.
