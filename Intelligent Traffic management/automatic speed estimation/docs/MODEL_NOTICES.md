# Model attribution and provenance

This runtime uses unchanged pretrained third-party checkpoints. They were not trained or fine-tuned by the FYP feature.

- **YOLO11s:** [Ultralytics assets v8.3.0](https://github.com/ultralytics/assets/releases/tag/v8.3.0), with implementation at [ultralytics/ultralytics](https://github.com/ultralytics/ultralytics). The upstream project identifies AGPL-3.0 and commercial licensing options.
- **UrbanOmniDetect:** [Mehmet Kerem Turkcan / UrbanOmniDetect](https://huggingface.co/mehmetkeremturkcan/UrbanOmniDetect), revision `2701a2eec9a73afb5ffd852740d125dfcd065ce5`, checkpoint `checkpoints/urbanomnidetect_yolo11x-p2_1920.pt`. The pinned model-card metadata identifies `agpl-3.0`. Its upstream repository supplies model source, data and notices.

[models/manifest.json](../models/manifest.json) records exact URLs, sizes and hashes. [LICENSES/AGPL-3.0.txt](../LICENSES/AGPL-3.0.txt) retains the upstream license text. Model binaries are downloaded and verified locally rather than committed.

The camera-specific geometry solver and speed calculation are application code. Their accuracy claims should not be attributed to the detector or cuboid-model authors.
