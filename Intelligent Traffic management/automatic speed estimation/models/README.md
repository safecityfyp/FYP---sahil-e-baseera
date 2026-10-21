# Model weights

```powershell
python download_models.py --output models
```

The downloader checks SHA-256 hashes against [manifest.json](manifest.json).

| Checkpoint | Role | Approximate size |
|---|---|---:|
| `yolo11s.pt` | Vehicle detector; ByteTrack supplies temporal identities | 19 MB |
| `urban_geometry.pt` | Eight projected vehicle-cuboid corners | 180 MB |

Weights are downloaded at runtime and excluded from Git. An existing model folder can be passed to `extract_tracks.py --models <folder>` without downloading another copy. `download_models.py --verify-only` checks an existing folder.

There is no separately trained `speed.pt` or `calibration.pt`: numerical road mappings are JSON files, and speed comes from ground displacement and elapsed source time. No upstream weights were fine-tuned. The pinned geometry checkpoint returns eight XY points without per-point confidence; the runtime checks the ground-face ordering.

The weights retain their upstream AGPL-3.0 terms and attribution. See [model notices](../docs/MODEL_NOTICES.md) and the supplied [license text](../LICENSES/AGPL-3.0.txt).
