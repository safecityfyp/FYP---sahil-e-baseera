# Mercedes speed validation — pilot stage

Full 30-clip speed-blind inference is running on Kaggle. No held-out accuracy claim is made at this stage. The final report will replace this progress page.

The user requested that text label files be ignored. References come from filenames and were confirmed as cruise-control settings.

| Pilot reference | Initial legacy diagnostic | Corrected geometry | Reference-assisted fit |
|---:|---:|---:|---:|
| 30.0 | 12.25 | 28.76 | 30.00 |
| 60.0 | 11.97 | 42.71 | 57.08 |
| 100.0 | 19.73 | 81.96 | 100.01 |

These three clips were used for calibration development. Their fitted results are not independent validation. The remaining 27 clips are reserved for evaluation after the calibration is frozen.

[Initial pilot records](pilot_initial_results.json) · [Fitted pilot records](pilot_fitted_results.json) · [Frozen pilot calibration](pilot_frozen_calibration.json)

## Paired videos

- 30 km/h pilot: [calibration](videos/MercedesAMG550_30/calibration.mp4) · [speed](videos/MercedesAMG550_30/speed.mp4)
- 60 km/h pilot: [calibration](videos/MercedesAMG550_60/calibration.mp4) · [speed](videos/MercedesAMG550_60/speed.mp4)
- 100 km/h pilot: [calibration](videos/MercedesAMG550_100/calibration.mp4) · [speed](videos/MercedesAMG550_100/speed.mp4)
