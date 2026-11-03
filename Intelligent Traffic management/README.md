# Intelligent Traffic Management
Sahil-e-Baseera | Helmet Detection
Google Colab notebook for a two-stage CCTV helmet detection prototype. Stage 1 uses YOLO11s to detect motorcycles (COCO class 3). Stage 2 expands each motorcycle bounding box to include the rider and runs a fine-tuned YOLO helmet detector on the cropped ROI. Class-agnostic global NMS suppresses overlapping head detections. The notebook writes an annotated MP4, creates a 20-second preview, and supports download or copying to Google Drive.
Repository contents
- notebooks/helmet_detection.ipynb: original inference implementation, with Markdown section headings and cleared notebook outputs; no inference logic changed.
- requirements.txt: dependencies used by the notebook (Colab provides PyTorch, IPython and Google Colab utilities).
- models/README.md: model weight requirements and availability.
- samples/input/, samples/output/: optional small, authorized demonstration clips.
- .gitignore: excludes model binaries, video files, secrets and temporary files by default.
- TESTING.md: validation checklist and limitations.
Run in Google Colab
1. Open notebooks/helmet_detection.ipynb in Google Colab and select a GPU runtime if available.
2. Run the dependency installation cell and subsequent cells in order.
3. When prompted, upload your trained helmet detector .pt file. The notebook checks for the exact normalized class labels with_helmet and without_helmet.
4. The notebook uses its configured Google Drive video URL unless /content/input_video.mp4 already exists. Change VIDEO_URL or supply /content/input_video.mp4 to use your own permitted CCTV footage.
5. Run the inference cell. It writes /content/sahil_roi_helmet_output.mp4 and can generate /content/sahil_roi_preview.mp4.
6. Download the annotated output or use the optional Drive-copy cell.
Important: The notebook contains Colab-specific imports and paths, so pip install -r requirements.txt alone does not make it a standalone command-line application. The notebook installs its own dependencies as originally written.
Pipeline settings
The original code uses YOLO11s (yolo11s.pt) for motorcycle detection with confidence 0.25, image size 1280; the helmet model uses confidence 0.30, image size 640. Motorcycle ROI expansion is left/right 0.30, top 1.20, bottom 0.10; global helmet NMS IoU is 0.45. These are implementation settings, not verified accuracy claims.
Current limitations
- Stationary motorcycles are not filtered in this previous-version notebook. Parked motorcycles may therefore trigger helmet detections.
- There is no motion tracking or temporal confirmation in this notebook.
- CCTV angles, occlusion, image quality, and incorrect rider association can affect results.
- The fine-tuned model weights and any authorized example CCTV footage must be provided separately.
Reproducibility and privacy
Do not commit private CCTV footage, license plates, or model files you do not have permission to distribute. Add a downloadable model link and a small authorized sample if this feature needs to be independently demonstrated.
Project
Sahil-e-Baseera, Safe City FYP. This folder documents the working Colab inference prototype, not yet a production API or live multi-camera integration.
