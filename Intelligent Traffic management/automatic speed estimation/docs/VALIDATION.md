# Runtime cleanup and evidence

The deployment branch is based on `main`. The complete previous feature tree is preserved unchanged on [feature/experiments/speed-estimtaion](https://github.com/safecityfyp/FYP---sahil-e-baseera/tree/feature/experiments/speed-estimtaion), at snapshot `77d143b56c352193aded1bbd1f42b6fec94d511f`.

The runtime keeps the selected CCTV detector/cuboid, calibration, view-checking, speed and rendering paths. It removes dependencies on validation runners, notebook builders, report generators and the optional assistant screenshot experiment. Existing mathematical functions were transferred into the `speed_estimation` package; this cleanup does not introduce a new calibration technique or empirical speed correction.

The tests cover known metric geometry, source elapsed time, acceleration, turning, stationary-car exclusion, missing observations, region splitting, robust outlier handling, ground-face ordering and insufficient-car rejection. Additional interface checks cover saved camera mappings and command help without benchmark files. The cleanup verification summary is in [runtime_verification.json](runtime_verification.json).

All **14 tests passed**. Using the unchanged frozen mappings, both complete saved speed calculations reproduced their original sample identities and one-decimal displays: **306 track IDs / 3,195 samples** for Commercial II-01 and **355 track IDs / 3,739 samples** for K Block. Fresh extraction with pinned Ultralytics 8.4.175 decoded a three-second Commercial segment, and ten-second calibration/speed previews rendered for each camera. These smoke checks do not represent a new full-recording detector run.

Refitting the calibrations separately selected the same methods and fitting tracks. The maximum resulting speed difference was below 0.0001 km/h. One K Block sample crossed a one-decimal rounding boundary (42.1500305 versus 42.1499713 km/h); that is recorded rather than claiming bit-identical refits. Reuse of the frozen mappings gives all original one-decimal labels.

Both frozen camera mappings remain byte-identical to the archived artifacts. The reorganized runtime is checked against the original saved Commercial calibration and full speed samples; any tiny optimizer differences are reported alongside sample counts and one-decimal display agreement. This verification uses local archived inputs without copying those datasets into the deployment branch. It is software regression checking, not independent speed-accuracy validation.

Historical study files remain available:

- [Mercedes cruise-control tests](https://github.com/safecityfyp/FYP---sahil-e-baseera/tree/feature/experiments/speed-estimtaion/Intelligent%20Traffic%20management/automatic%20speed%20estimation/output/mercedes_validation)
- [Calibration-method comparisons](https://github.com/safecityfyp/FYP---sahil-e-baseera/tree/feature/experiments/speed-estimtaion/Intelligent%20Traffic%20management/automatic%20speed%20estimation/output/calibration_comparison)
- [Kia development/reserved tests](https://github.com/safecityfyp/FYP---sahil-e-baseera/tree/feature/experiments/speed-estimtaion/Intelligent%20Traffic%20management/automatic%20speed%20estimation/output/kia_validation)
- [Full CCTV results and video gallery](https://github.com/safecityfyp/FYP---sahil-e-baseera/tree/feature/experiments/speed-estimtaion/Intelligent%20Traffic%20management/automatic%20speed%20estimation/output/cctv_20261009)
- [Assistant screenshot trial, including failures](https://github.com/safecityfyp/FYP---sahil-e-baseera/tree/feature/experiments/speed-estimtaion/Intelligent%20Traffic%20management/automatic%20speed%20estimation/output/vision_assisted_trial)

The controlled reference speeds were user-confirmed cruise-control settings, with unknown independent measurement uncertainty. Some historical methods used other labelled passages for reference-assisted calibration. Their reported errors must not be presented as measured accuracy of this automatic CCTV runtime. Real CCTV passage-speed accuracy remains unverified, and the requested +/-1–2 km/h target has not been established on those cameras.
