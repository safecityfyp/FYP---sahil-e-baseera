
# Sahil-e-Baseera | Helmet Detection

### AI-Powered Motorcycle Helmet Compliance Detection

This module is part of **Sahil-e-Baseera**, an AI-powered Safe City surveillance system developed as a Final Year Project (FYP).

The Helmet Detection module analyzes CCTV footage to identify motorcycle riders wearing or not wearing helmets using deep learning and computer vision.

Two detection approaches have been developed and tested:

1. Head Localization-Based Helmet Detection
2. Motorcycle + Rider ROI-Based Helmet Detection

The second approach is the current working prototype.

---

## 1. Repository Structure

```text
model/
├── best.pt
├── bike_+_head_detection.ipynb
├── Sahil_e_Baseera_Helmet_Detection.ipynb
├── README.md
└── requirements.txt
```

### File Descriptions

| File | Description |
|------|-------------|
| `best.pt` | Fine-tuned YOLO helmet detection model |
| `bike_+_head_detection.ipynb` | Earlier head-localization-based approach |
| `Sahil_e_Baseera_Helmet_Detection.ipynb` | Current motorcycle + rider ROI detection pipeline |
| `README.md` | Module documentation |
| `requirements.txt` | Python dependencies |

---

## 2. Detection Approaches

### Approach 1: Head Localization-Based Detection

**Notebook:** `bike_+_head_detection.ipynb`

This approach uses motorcycle and rider detection followed by head localization to identify the region where helmet classification should be performed.

The notebook is retained to document the initial experiments and development process.

### Approach 2: Motorcycle + Rider ROI Detection

**Notebook:** `Sahil_e_Baseera_Helmet_Detection.ipynb`

This is the current working prototype.

The pipeline consists of the following stages:

1. **Motorcycle Detection:** YOLO11s detects motorcycles in CCTV frames.
2. **ROI Expansion:** Motorcycle bounding boxes are expanded to include the rider's upper body and head.
3. **Helmet Detection:** A fine-tuned YOLO model processes each expanded ROI.
4. **Non-Maximum Suppression:** Overlapping helmet detections are filtered.
5. **Visualization:** Helmet detections are drawn on video frames.
6. **Video Export:** The processed video is saved as an annotated MP4.

### Pipeline Architecture

```text
             CCTV Video Input
                    |
                    v
           Frame Extraction
                    |
                    v
          YOLO11s Detection
                    |
                    v
          Motorcycle Detection
                    |
                    v
         Motorcycle ROI Expansion
                    |
                    v
        Fine-Tuned Helmet Model
                    |
                    v
       Helmet / No Helmet Detection
                    |
                    v
       Non-Maximum Suppression
                    |
                    v
          Bounding Box Drawing
                    |
                    v
           Annotated MP4 Output
```

---

## 3. Technologies Used

| Technology | Purpose |
|------------|---------|
| Python | Main programming language |
| Ultralytics YOLO11s | Motorcycle detection |
| Fine-tuned YOLO | Helmet detection |
| OpenCV | Video processing and annotations |
| PyTorch | Deep learning inference |
| Google Colab | Notebook execution |
| NumPy | Numerical operations |
| FFmpeg | Optional video conversion |

---

## 4. Model Configuration

The current ROI-based notebook uses the following configuration:

| Parameter | Value |
|-----------|-------|
| Motorcycle Detection Model | YOLO11s |
| Helmet Detection Model | `best.pt` |
| Motorcycle Class ID | 3 |
| Motorcycle Confidence | 0.25 |
| Helmet Confidence | 0.30 |
| Motorcycle Image Size | 1280 |
| Helmet Image Size | 640 |
| Helmet NMS IoU | 0.45 |

### ROI Expansion Configuration

| Direction | Expansion |
|-----------|-----------|
| Left | 0.30 |
| Right | 0.30 |
| Top | 1.20 |
| Bottom | 0.10 |

ROI expansion is calculated relative to the detected motorcycle bounding box.

---

## 5. Installation

### Step 1: Clone the Repository

```bash
git clone https://github.com/safecityfyp/FYP---sahil-e-baseera.git
```

Navigate to the folder containing the helmet detection implementation.

### Step 2: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 3: Open the Notebook

Open the following notebook in Google Colab:

```text
Sahil_e_Baseera_Helmet_Detection.ipynb
```

Select a GPU runtime if available.

---

## 6. Running Helmet Detection

1. Open the ROI-based notebook in Google Colab.
2. Execute the dependency installation and inference cells.
3. Upload `best.pt` when prompted.
4. Provide an input CCTV video.
5. Execute the detection pipeline.
6. Wait for video processing to complete.
7. Preview or download the annotated output.

### Input Video

The current notebook uses:

```text
/content/input_video.mp4
```

If this file is unavailable, the notebook attempts to download the configured Google Drive video.

### Output Video

The annotated output is saved to:

```text
/content/sahil_roi_helmet_output.mp4
```

The notebook also includes functionality for video preview, download, and optional Google Drive export.

**Note:** The notebook currently requests a manual model upload. Keeping `best.pt` in the repository does not automatically load it into Google Colab.

---

## 7. Detection Classes

The helmet detection model uses two classes:

| Class | Description |
|-------|-------------|
| `with_helmet` | Helmet detected |
| `without_helmet` | No helmet detected |

The model produces bounding boxes and confidence scores for detected helmet classes.

---

## 8. Testing and Validation

The prototype is intended to be evaluated on CCTV footage containing motorcycle riders under different conditions.

Important test scenarios include:

- Riders wearing helmets
- Riders without helmets
- Multiple motorcycles in one frame
- Different camera viewpoints
- Low-resolution CCTV footage
- Partially occluded riders
- Parked motorcycles
- Overlapping motorcycles and riders

Testing should include manual inspection of annotated output videos to identify incorrect detections and missed riders.

---
## 09. Model Weights

The trained helmet detection model is stored as:

```text
best.pt
```

The motorcycle detection stage uses the Ultralytics YOLO11s model:

```text
yolo11s.pt
```

Ultralytics can automatically download the motorcycle detection weights when required.

The trained helmet model must be accessible during inference.

---

## 10. Project Information

**Project:** Sahil-e-Baseera

**Category:** AI-Powered Safe City Surveillance System

**Module:** Traffic Compliance - Helmet Detection

**Implementation:** Python, YOLO, OpenCV, PyTorch

**Current Status:** Working notebook-based video inference prototype

**Development:** Final Year Project

---

## 11. Conclusion

The Helmet Detection module demonstrates a two-stage computer vision pipeline for detecting motorcycle helmet compliance from CCTV footage.

The repository preserves both the earlier head-localization experiment and the current motorcycle-and-rider ROI implementation.

The current prototype provides a foundation for future integration with Sahil-e-Baseera's traffic compliance and incident monitoring system.
