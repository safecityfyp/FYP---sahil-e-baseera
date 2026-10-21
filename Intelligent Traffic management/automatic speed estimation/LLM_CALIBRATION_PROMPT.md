# Reviewable image observations for an LLM

The first trial used the current assistant's visual analysis. This file defines how to collect comparable proposals from another vision-capable model later; it does not claim that any external model has run.

Give the model original-resolution images with their pixel dimensions. Use anonymous case IDs and hide speed labels. Keep the unchanged `images` entries and their SHA-256 hashes from the input metadata. Use the actual source timestamps when calculating speed. Record provider/model/version, request text, response and any subsequent human corrections when a provider is used.

Suggested prompt:

> Inspect these original-resolution images of one vehicle passage from a fixed camera. Mark the same visible near-side front-tyre and rear-tyre ground contacts in each image. Return original-image XY pixel coordinates, not coordinates from a resized preview. Mark two visible straight road-edge segments believed parallel to the vehicle's direction. Describe the evidence for that assumption. Do not fabricate hidden wheel locations. If tyre-ground contacts or parallel edges cannot be resolved, state that this approach is unavailable. Propose a vehicle-family hypothesis and wheelbase prior with source/uncertainty; distinguish wheelbase from total vehicle length. Do not infer an exact camera pitch, road length, vehicle speed or measured physical dimension from appearance alone. Do not use filenames, speed labels or expected traffic speeds. Return observations and assumptions; the supplied numerical code will calculate calibration and speed.

`output/vision_assisted_trial/M01/annotations.json` is the complete example schema. Required fields include:

| Field | Meaning |
|---|---|
| `schema_version`, `case_id`, `image_size` | Version, anonymous view identity, original width/height. |
| `road_edge_segments_px` | Two arrays `[[x1,y1],[x2,y2]]` in original pixels. |
| `wheelbase_prior_m` | Axle separation in metres, supplied as an explicit assumption or independently measured fact. |
| `wheel_contacts` | In image order, each `{"front_xy":[x,y],"rear_xy":[x,y]}` for the same visible side. |
| `anchor_frame` | Zero-based list index of the one-screenshot scale image. |
| `images` | Image filenames, source frame indices and content hashes. |
| `uncertainty` | Wheel/road point standard deviations in pixels and relative wheelbase half-range. |
| `assumptions` | Camera stability, road plane, roll, path parallelism and unconfirmed vehicle identification. |

The `frames.json` companion records the source frame indices and timestamps in the same order. A screenshot alone supplies no elapsed time, so a temporal point sequence is required for speed. Three or more observations over at least 0.15 seconds are required here; the recorded trial uses five. No reference speed belongs in either the calibration input or prediction stage.

`calibrate.py vision` verifies image hashes and writes a frozen JSON. `estimate_speed.py vision` refuses changed annotations or mismatched frame identity. Three candidate methods are available: `local_affine`, `projective_single`, `projective_consensus`. Select the method policy before examining errors and retain failures. The consensus is a robustness experiment; multiple agreeing scales are not independent proof of correct metres.

This observation contract only supports the restricted straight-path experiment implemented in `vision_calibration.py`. For general turns or multi-lane road mapping use the automatic CCTV ground-plane workflow, or supply sufficient surveyed point correspondences for a different explicitly implemented mapping. Do not relabel the 1-D JSON as a full road homography.
