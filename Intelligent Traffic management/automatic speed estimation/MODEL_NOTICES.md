# Third-party model checkpoints

The local handoff ZIP includes unchanged upstream checkpoints. These are pretrained third-party models; they were not trained or fine-tuned by this project. They retain their authors' terms and attribution.

- **Ultralytics YOLO11s:** vehicle detector from [Ultralytics assets v8.3.0](https://github.com/ultralytics/assets/releases/tag/v8.3.0), with source at [ultralytics/ultralytics](https://github.com/ultralytics/ultralytics). The project identifies AGPL-3.0 and commercial licensing options. The supplied `LICENSES/AGPL-3.0.txt` is the upstream license text.
- **UrbanOmniDetect:** cuboid keypoint model by [Mehmet Kerem Turkcan / UrbanOmniDetect](https://huggingface.co/mehmetkeremturkcan/UrbanOmniDetect). The pinned model-card metadata identifies `agpl-3.0`. Its revision is `2701a2eec9a73afb5ffd852740d125dfcd065ce5`, checkpoint `checkpoints/urbanomnidetect_yolo11x-p2_1920.pt`. See the upstream repository for its source, data and full notices.

`model_manifest.json` binds the exact bytes to SHA-256 hashes. Binary weights remain excluded from this Git branch; `download_models.py` retrieves and verifies the same files. The ZIP additionally includes the complete feature Python source as a source snapshot, with feature-branch provenance in `PACKAGE_MANIFEST.json`. Upstream source links and the license text are retained alongside the weights.

Speed and road calibration are numeric project code, not additional pretrained `.pt` checkpoints. Do not attribute their application-specific performance claims to the upstream authors.
