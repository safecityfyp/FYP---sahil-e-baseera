# Camera configuration and calibration reuse

The default [configs/cameras.json](../configs/cameras.json) contains two manually reviewed camera profiles:

| Camera ID | Supplied recording | Regions |
|---|---|---|
| `commercial_ii_01` | `NVR_ch6_main_20261009170002_20261009180000.mp4` | Left/right carriageways |
| `k_block_st20` | `D02_20261009160351.mp4` | Near approach/cross street |

These profiles identify exact source recordings by SHA-256. Extraction rejects a mismatched recording; speed calculation checks camera and recording identities against the calibration. This is a camera-configured prototype, rather than automatic discovery of arbitrary roads.

## Add another recording/camera

1. Copy `configs/cameras.json` to a local profile file and add a camera key under `cameras`. Set `display_name`, the source `video` filename, and the lowercase source SHA-256. On Windows, obtain the file hash with `Get-FileHash -Algorithm SHA256 -LiteralPath "C:\footage\recording.mp4"`.
2. Draw each usable road region as a polygon of normalized `[x/image_width, y/image_height]` points. Exclude parking, medians and areas where ground footprints cannot be measured. Use separate regions for surfaces/directions that need separate local planes.
3. Retain the default sampling/window settings initially. K Block demonstrates camera overrides for brief close passes: `geometry_hz`, calibration observation/span minimums, and local speed-window settings. The current solver uses a fixed 4.5 × 1.8 m nominal passenger-car prior; changing the descriptive `dimension_prior_m` entry alone does not change solver mathematics.
4. Pass the same profile to extraction and calibration:

```powershell
python extract_tracks.py --profiles configs/my_cameras.json --camera my_camera --video "C:\footage\recording.mp4" --output output/my_camera/measurements --device 0
python calibrate.py --profiles configs/my_cameras.json --camera my_camera --inputs output/my_camera/measurements --output output/my_camera/calibration
python estimate_speed.py --inputs output/my_camera/measurements --calibration output/my_camera/calibration/calibration.json --output output/my_camera/speed
```

The generated calibration includes its profile, source identity, candidate comparisons, accepted regions, support hulls, fitting car IDs and source-code hashes. Speed calculation reads the profile from that frozen JSON. It does not load unrelated benchmark scale corrections.

## What is saved and reused

The committed `calibrations/*.json` files are unmodified snapshots of the supplied-camera experiment at [commit 77d143b](https://github.com/safecityfyp/FYP---sahil-e-baseera/commit/77d143b56c352193aded1bbd1f42b6fec94d511f). Their old source-file names/hashes describe that provenance; the corresponding source remains on the experiments branch.

Reuse a mapping only for its supported road/view geometry. The current identity checks bind these supplied mappings to their original recording. A new recording needs its own profile and an explicitly checked calibration workflow; copying its hash into an old calibration is not a view-validation procedure. View checks sampled during a recording screen for shifts, zoom or uncertain matches, but cannot prove that the camera never moved.

Calibration considers 5-, 10- and 15-minute windows. It requires at least six independent moving-car tracks per region, prefers twelve with stable subsets, and can stop earlier than fifteen minutes. Parked cars are excluded. If a region fails the checks, `calibrate.py` exits with a diagnostic after writing its report; review that report rather than treating an unsupported region as calibrated.

For long jobs, `extract_tracks.py --duration 900` can produce an initial measurement segment. `--resume-s 900` starts another folder from that source time; combine both folders in `--inputs`. Use separate output folders for segments, because extraction writes new files. An existing model folder can be shared with `--models`.

Unknown vehicle dimensions, nonplanar/curving roads, lens distortion, hidden ground contacts, and camera movement remain limits of the inferred metric scale. Calibrating more cars reduces variability but does not replace independent scale evidence.
