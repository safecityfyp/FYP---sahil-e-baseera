Sahil-e-Baseera | Helmet Detection
Helmet-compliance detection research and video-inference prototype for the Sahil-e-Baseera Safe City FYP. This folder retains two notebook-based approaches and the fine-tuned helmet model weights.
Repository structure
model/
├── best.pt
├── bike_+_head_detection.ipynb
├── Sahil_e_Baseera_Helmet_Detection.ipynb
├── README.md
└── requirements.txt
The notebook filenames above reflect the current folder naming. If your files use slightly different names, update the listing accordingly.

Implementations
1. Head-localization approach (earlier experiment)
Notebook: bike_+_head_detection.ipynb

This notebook is retained as an earlier experiment using head localization before helmet assessment. It is not the recommended entry point for the current ROI-based demo. Consult its own cells for its exact models, parameters, and execution requirements.
2. Motorcycle + rider ROI approach (current working prototype)
Notebook: Sahil_e_Baseera_Helmet_Detection.ipynb

This notebook implements a two-stage inference pipeline:
1. Motorcycle detection: YOLO11s (yolo11s.pt) detects motorcycles (COCO class ID 3).
2. ROI expansion: Each motorcycle box is expanded upward and sideways to include the rider's upper body and head.
3. Helmet detection: The fine-tuned best.pt YOLO model runs on each expanded ROI and predicts with_helmet or without_helmet.
4. Duplicate suppression: Global non-maximum suppression removes overlapping helmet detections.
5. Visualization: The notebook draws configured detection boxes and writes an annotated MP4.
Current ROI notebook configuration: motorcycle confidence 0.25; helmet confidence 0.30; motorcycle inference image size 1280; helmet inference image size 640; helmet NMS IoU 0.45. ROI expansion: left/right 0.30, top 1.20, bottom 0.10 relative to motorcycle box dimensions.
Requirements
- Python environment with the packages in [`requirements.txt`](requirements.txt).
- Google Colab is the intended execution environment for the current ROI notebook because it uses google.colab.files and Colab-specific /content/ paths.
- GPU runtime recommended for video inference.
- The trained model best.pt, with class names with_helmet and without_helmet.
- Accessible input CCTV footage, with permission to use and share it.
- FFmpeg for the optional preview conversion step (normally available in Colab).
Running the ROI notebook in Google Colab
1. Open Sahil_e_Baseera_Helmet_Detection.ipynb in Google Colab.
2. Select Runtime → Change runtime type → GPU, if available.
3. Install the dependencies when prompted by the notebook. Its main cell also installs ultralytics, gdown, opencv-python-headless, and tqdm.
4. Run the main cell. When the notebook prompts for a .pt file, upload the provided best.pt.
5. The notebook uses /content/input_video.mp4 if it exists; otherwise it tries to download its configured Google Drive video URL. Update that URL in the notebook or upload a video to the expected path if needed.
6. Allow the video inference to finish. The annotated output is written to /content/sahil_roi_helmet_output.mp4.
7. Use the notebook's preview, download, or optional Google Drive export cells to inspect the result.
Note: Keeping best.pt beside the notebook in GitHub does not automatically make it available in Colab. The existing notebook explicitly requests a model upload. This README does not change that behavior.
Known limitations
- Parked motorcycles: The previous working ROI notebook does not include stationary-motorcycle filtering. Parked bikes in CCTV views can therefore cause false positives.
- Image quality: Blurry, low-resolution, distant, or occluded riders can reduce detection reliability.
- Camera viewpoint: Poor side or rear angles can make the rider's head difficult to assess.
- ROI overlap: Overlapping riders and motorcycles may cause incorrect associations or duplicate candidates despite NMS.
- Scope: This is offline notebook-based video inference, not yet a live, integrated multi-camera service.
Validation before merging
- Confirm that best.pt loads and exposes exactly with_helmet and without_helmet classes.
- Test helmeted and non-helmeted riders across representative camera angles.
- Test parked motorcycles and document false positives.
- Inspect the generated MP4 for correct annotations and playback.
- Avoid committing sensitive or unauthorized CCTV footage.
Model weights and repository size
The best.pt weights are required for reproducible inference. If GitHub rejects the file due to size, use Git LFS or host the weights separately and document their location. The notebook also downloads yolo11s.pt automatically through Ultralytics when needed.
Project status
Status: Working Colab video-inference prototype. Full end-to-end execution has not been independently verified as part of this README update. The current ROI notebook does not implement motion-based parked-bike filtering.
