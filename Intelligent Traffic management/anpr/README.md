# Automatic Number Plate Recognition (ANPR)

This module provides detection, tracking, and optical character recognition (OCR) of license plates for the **Sahil-e-Baseera** Intelligent Safe City / Traffic Management platform.

## Features

- **License Plate Detection**: Powered by YOLOv11 (`plate_detector_yolo11n.pt` and ONNX runtime variant).
- **Plate Recognition**: Integrated with `fast-plate-ocr` (`cct-s-v2-global-model`) for real-time license plate reading.
- **Multi-Frame Tracking & Voting**: Association across consecutive frames with majority-voting OCR and highest-confidence snapshot logging.
- **Verification Outputs**: Saves cropped plate snapshots into `cropped_plates/` alongside detailed CSV reports (`plate_summary.csv`, `plate_raw_reads.csv`).

## Directory Structure

- `detect_plate.py`: Production pipeline with tracking, OCR voting, live preview, and CSV logging.
- `anpr.ipynb`: Interactive Jupyter notebook for step-by-step plate detection and OCR experiments.
- `kaggle_anpr_detection.ipynb`: Ready-to-run notebook tailored for Kaggle GPU environments.
- `experiment.ipynb`: Google Colab compatible evaluation notebook.
- `plate_detector_yolo11n.pt`: Fine-tuned YOLOv11 nano model weights for license plate detection (~5.5 MB).
- `plate_detector_yolo11n.onnx`: ONNX exported version of the detector (~10.6 MB).
- `requirements.txt`: Python package requirements.

## Quick Start

1. Install requirements:
   ```bash
   pip install -r requirements.txt
   ```

2. Run detection on a video stream or file:
   ```bash
   python detect_plate.py
   ```
   Or specify an input video:
   ```bash
   python detect_plate.py --video path/to/video.mp4
   ```
