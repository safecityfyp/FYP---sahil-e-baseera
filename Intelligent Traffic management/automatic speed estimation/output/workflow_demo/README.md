# Automatic workflow verification

The workflow checks this camera view for saved calibration, builds it when missing, and then estimates speeds. A second run reuses the calibration without fitting it again.

## Local test on the original CCTV interval

- [Verification summary](local_verification.json)
- [First run: calibration missing, new mapping fitted](local_cold_run.json)
- [Second run: saved mapping reused](local_warm_run.json)

Both runs use source seconds 150–210. Existing inference inputs were reused only after checking the exact source-video hash, interval, configuration and artifact hashes. The second run was tested with the road-calibration fitter disabled: calling it would fail the test. Both runs returned the same qualifying IDs and identical speed estimates.

Seven behavior tests cover camera changes, corrupt cache data, mismatched or altered inference inputs, reuse without fitting, unsupported road regions, stale outputs and within-clip view changes. Synthetic geometry checks also pass.

## Completed Kaggle GPU test

- [Verification summary](kaggle_verification.json)
- [First run: fresh tracking and geometry inference, then calibration and video rendering](kaggle_cold_run.json)
- [Second run: cached inference and saved calibration, without fitting](kaggle_warm_run.json)
- [Qualified experimental results](kaggle_qualified_speeds.csv)
- [Example road calibration: mappings, dimension priors and supported image nodes](calibration_example.json)
- [Private Kaggle workflow notebook](https://www.kaggle.com/code/hayyanfaisal/fyp-cctv-camera-calibration-workflow)

The Kaggle workflow completed on a Tesla T4. The first run performed both model-inference stages, fitted calibration, and rendered a 60-second H.264 preview with 1,500 frames at 25 FPS. It took approximately 337 seconds including that work. The second run reused the saved inputs and calibration, recalculated identical speed results in approximately 4.3 seconds, and intentionally skipped video rendering. Its calibration fitter was disabled to prove reuse. These timings cover different amounts of work and are not a general performance benchmark.

Both runs produced qualifying IDs 1, 115, 147 and 175. The fresh-run nominal speeds agreed with the original saved experiment within 0.000002 km/h. This establishes reproducibility, not speed accuracy. The calibration example is for inspection; a reusable cache also requires the matching camera-reference image, signature and integrity metadata, which the workflow saves in its runtime cache.

**All speeds remain experimental and unvalidated against measured ground truth.** See the [feature README](../../README.md) and [original output gallery](../README.md).
