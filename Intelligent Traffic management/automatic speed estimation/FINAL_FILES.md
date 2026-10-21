# Speed estimation and calibration handoff

The two main entry points are **`estimate_speed.py`** and **`calibrate.py`**. Keep their supporting modules together; the provided ZIP contains the dependencies, two verified model checkpoints, saved camera calibrations and the new screenshot trial.

## What is the model file?

| File | Purpose |
|---|---|
| `models/yolo11s.pt` | Detect vehicles; ByteTrack associates them between frames. |
| `models/urban_geometry.pt` | Estimate eight projected cuboid corners for car-ground geometry. |
| `saved_calibrations/commercial_ii_01.json` | Frozen road mapping for the supplied Commercial II-01 camera recording. |
| `saved_calibrations/k_block_st20.json` | Frozen road mapping for the supplied K Block recording. |
| `calibrate.py` | Stage 1: compare automatic road mappings, or calculate a mapping from assistant/manual image observations. |
| `estimate_speed.py` | Stage 2: load a calibration and calculate decimal km/h from tracked ground positions and source time. |

**There is no trained `speed.pt` or `calibration.pt`.** Speed is displacement in experimental metres divided by elapsed source-video time, multiplied by 3.6. The calibration is numerical geometry saved as JSON. No network weights were fine-tuned. [`model_manifest.json`](model_manifest.json) records the exact checkpoint URLs, revision, hashes and roles. The old local `vehicle_keypoints.pt` is not the current geometry model.

The local full ZIP includes both `.pt` files (about 199 MB combined). GitHub holds the downloader and manifest; model binaries remain outside Git. Run `python download_models.py --output models --verify-only` to check the included weights, or omit `--verify-only` to fetch missing ones from their pinned upstream sources.

## Does automatic calibration try multiple techniques?

Yes. For each configured road region it compares affine, projective, and projective-with-metric-prior mappings. It evaluates held-out car geometry, refits on qualifying moving cars, and checks six car subsets. It considers initial 5-, 10-, and 15-minute windows until the minimum car count and stability requirements are met. The two supplied cameras stopped after five or ten minutes depending on region.

The chosen method is the one supported by internal geometry/stability checks. These checks cannot independently prove the correct metre scale. The fleet prior is 4.5 m length and 1.8 m width. A measured road reference or confirmed vehicle dimensions would give stronger absolute scale evidence. JSON contains the selected methods, support area, car IDs, mappings and comparison diagnostics. It does not independently measure full road length, true camera height/pitch or lens parameters.

After calibration, reuse its JSON for speed estimation while the camera view and geometry remain valid. Do not refit the road from every passing car. The existing `workflow.py` remains the original A3 cache-checking workflow in the repository; the entry points here make the two stages explicit for the long CCTV experiments. Each supplied camera has a separate calibration; their maps cannot be interchanged.

## Install and use the two stages

Python 3.13 was used for the local handoff checks. The historical Kaggle inference dependencies are pinned in `requirements-inference.txt`. A GPU is recommended for fresh detector/cuboid extraction; calibration and speed from saved measurements run on CPU. The new image-assisted trial requires only the numerical libraries and saved images.

```powershell
python -m pip install -r requirements-inference.txt
python download_models.py --output models --verify-only
```

For a **fresh measurement run on the supplied Commercial recording**, choose a run directory and point extraction at the included models. This processes the source to locate vehicles; it does not change the road calibration:

```powershell
python cctv_inference.py --video "C:\Users\hayya\Videos\FYP\Speed\CCTV\NVR_ch6_main_20261009170002_20261009180000.mp4" --camera commercial_ii_01 --models models --output runs/commercial/measurements --device 0
python calibrate.py cctv --inputs runs/commercial/measurements --camera commercial_ii_01 --output runs/commercial/calibration
python estimate_speed.py cctv --inputs runs/commercial/measurements --calibration runs/commercial/calibration/calibration.json --output runs/commercial/speed
python cctv_render.py --video "C:\Users\hayya\Videos\FYP\Speed\CCTV\NVR_ch6_main_20261009170002_20261009180000.mp4" --inputs runs/commercial/measurements --calibration runs/commercial/calibration/calibration.json --speed runs/commercial/speed --output runs/commercial/videos
```

If using the frozen mapping, use `saved_calibrations/commercial_ii_01.json` in the speed/render commands and skip fitting. The ZIP supplies that path; in the repository the same artifact is `output/cctv_20261009/commercial_ii_01/calibration/calibration.json`. For K Block, use camera `k_block_st20`, its own source `D02_20261009160351.mp4`, and its own mapping. `--device cpu` is supported for extraction but can be slow. FFmpeg and FFprobe must be on PATH to render videos.

With the repository's existing measurements, no fresh GPU work is required:

```powershell
python estimate_speed.py cctv --inputs output/cctv_20261009/commercial_ii_01/measurements/pilot output/cctv_20261009/commercial_ii_01/measurements/remainder --calibration output/cctv_20261009/commercial_ii_01/calibration/calibration.json --output outputs/commercial_speed
```

The automatic extraction profiles intentionally bind to the supplied source recordings and manually reviewed road polygons in `cctv_camera_profiles.json`. A different camera/source needs its own reviewed profile and calibration; these examples do not claim generic camera discovery. Source footage is not included in the ZIP.

## Assistant/LLM screenshot calibration: implemented and tested

The first authorized trial used this assistant to inspect the actual car/road screenshots. It marked visible tyre-ground contacts and road edges, supplied approximate wheelbase priors, and ran numerical calibration followed by speed estimation. No external GPT/Claude service was called. See [`LLM_CALIBRATION_PROMPT.md`](LLM_CALIBRATION_PROMPT.md) for the reviewable observation contract and [`output/vision_assisted_trial/README.md`](output/vision_assisted_trial/README.md) for all six individual results, images and graphs.

Three versions were frozen before scoring: a local affine control, one-screenshot projective scale, and five-screenshot projective consensus. **The preselected consensus did not improve accuracy: 6.85 km/h MAE versus 2.68 km/h for the historical pipeline on the same six clips.** The historical pipeline has extra assistance from other labelled passages and different observation intervals, so this is not an equal-input ablation. The screenshot trial is retained as an optional experiment, not promoted as the default calibration.

Reproduce its two stages without footage, `.pt` files or an external LLM account:

```powershell
python calibrate.py vision --annotations output/vision_assisted_trial/M01/annotations.json --method projective_consensus --output runs/manual_M01/calibration.json
python estimate_speed.py vision --annotations output/vision_assisted_trial/M01/annotations.json --frames output/vision_assisted_trial/M01/frames.json --calibration runs/manual_M01/calibration.json --output runs/manual_M01/speed.json
```

This produces **40.6 km/h** for M01 against its **30 km/h** cruise setting: a failed test, preserved openly. It is a restricted 1-D calculation along the car's path, under a planar/zero-roll assumption, not a recovered 2-D map of the whole road. Conditional sensitivity is stored separately from the decimal estimate. A single screenshot cannot determine speed without temporal observations, and uncertain vehicle dimensions do not establish exact metres.

## Validation and practical limits

Seventeen numerical/behavior checks pass, including exact 36 km/h recovery on a synthetic projective scene, changed-image/point/frame rejection, reference-label rejection and the existing CCTV tests. Both downloaded checkpoints were loaded and ran on one actual Mercedes frame. Commercial calibration was reproduced through the new entry point and its full speed calculation reproduced **306 tracks and 3,195 local speed samples** from the saved measurements. This handoff did not rerun full CCTV detection or all 63 controlled clips.

```powershell
python -m unittest test_vision_calibration test_cctv
python vision_trial.py evaluate
```

Existing Kia reserved testing reported 2.36 km/h MAE and 13/25 within +/-2; Mercedes development testing reported 2.38 km/h MAE and 19/30 within +/-2. These are cruise-control studies within their documented limits. The requested target is not met on every clip. Real CCTV speed accuracy remains unverified because independent passage speed/distance references have not been supplied. Decimal display is not a claim of 0.1 km/h accuracy. Earlier videos and full reports remain in the feature branch; no video files are duplicated in the handoff ZIP.
