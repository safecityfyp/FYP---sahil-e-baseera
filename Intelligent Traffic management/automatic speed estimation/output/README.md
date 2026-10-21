# Generated output

Use this directory for local measurement, calibration, speed-table and video outputs. Generated files are ignored by Git, keeping the deployment branch small.

The complete previously generated videos, measurements, graphs, reports and individual Mercedes/Kia tests are preserved on [feature/experiments/speed-estimtaion](https://github.com/safecityfyp/FYP---sahil-e-baseera/tree/feature/experiments/speed-estimtaion/Intelligent%20Traffic%20management/automatic%20speed%20estimation/output).

Typical output from the four runtime commands:

```text
output/commercial/
  measurements/    # Detection tracks, ground corners, timing and view checks
  calibration/    # calibration.json, candidate diagnostics and accepted footprints
  speed/          # speed_samples.csv, track_summary.csv, speed_report.json, compressed samples
  videos/         # calibration.mp4 and ordered speed_XX.mp4 segments
```

Video rendering requires the original footage plus FFmpeg/FFprobe. Source footage and neural weights are not committed to this branch.
