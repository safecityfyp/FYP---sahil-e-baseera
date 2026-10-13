"""
ANPR Pipeline v6 - Cropped Plate Snapshots + Forced Live Preview + OCR Verification
======================================================================================
Additions vs v4/v5:
  1. Every confirmed plate (any track that clears OCR_CONF_THRESHOLD and gets a
     best_text) has its best-quality crop saved to cropped_plates/ as
     "ID{track_id}_{plate_text}.jpg" - the crop is the RAW camera-cropped plate
     (not an enhanced/upscaled variant), so it visually matches what a human
     would judge the plate to say. This is the direct way to verify OCR
     correctness: open plate_summary.csv next to the cropped_plates folder and
     compare each row's plate_text against its matching image.
  2. Track now remembers whichever single OCR attempt had the highest
     confidence across its whole lifetime (best_crop / best_crop_score),
     independent of which text ultimately won the majority vote, so the saved
     image is always the clearest capture of that vehicle's plate.
  3. Live preview no longer self-disables after one cv2.error. A named,
     resizable window is created explicitly before the loop starts, which
     resolves most remote-desktop first-frame hiccups by itself. If imshow
     still errors, it's printed (throttled) but the loop keeps trying every
     frame instead of giving up - appropriate for AnyDesk sessions, which
     provide a real virtual display and don't need headless fallback logic.
  4. Retains v5's OCR error visibility (no silent except:pass) and
     plate_raw_reads.csv (every OCR attempt, accepted or not) for calibrating
     OCR_CONF_THRESHOLD from real data - directly relevant to verifying
     extraction quality.

Install requirements:
  pip install ultralytics fast-plate-ocr[onnx-gpu] opencv-python torch scipy
  # CPU-only instead of onnx-gpu:
  # pip install ultralytics fast-plate-ocr[onnx] opencv-python torch scipy
"""

import os
import cv2
import torch
import time
import re
import csv
from datetime import datetime
from typing import List, Tuple, Optional, Dict
import numpy as np
from ultralytics import YOLO
from fast_plate_ocr import LicensePlateRecognizer
from scipy.optimize import linear_sum_assignment

# =================== CONFIGURATION ===================
MODEL_PATH = "plate_detector_yolo11n.pt"
OCR_MODEL_NAME = "cct-s-v2-global-model"
VIDEO_PATH = os.environ.get("ANPR_VIDEO_PATH", "video.mp4")
OUTPUT_VIDEO = "output_annotated.mp4"
EVENT_CSV_LOG = "plate_log.csv"
RAW_READS_CSV_LOG = "plate_raw_reads.csv"
SUMMARY_CSV_LOG = "plate_summary.csv"
CROPPED_PLATES_DIR = "cropped_plates"      # NEW: one image per confirmed unique track/plate

SHOW_PREVIEW = os.environ.get("ANPR_SHOW_PREVIEW", "1") != "0"
FORCE_LIVE_PREVIEW = True                  # NEW: never auto-disable preview on transient errors
PREVIEW_WINDOW_NAME = "ANPR - Detection + Tracking + fast-plate-ocr"
PREVIEW_WINDOW_SIZE = (1280, 720)          # resize the display window; does not affect output video

CONFIDENCE = 0.25
SKIP_FRAMES = 1
OCR_CONF_THRESHOLD = 0.40                  # calibrate from plate_raw_reads.csv confidences
EARLY_STOP_CONF = 0.90
OCR_INTERVAL_ACTIVE = 1
OCR_INTERVAL_CONFIRMED = 8
DEVICE = 'cuda' if torch.cuda.is_available() else 'cpu'

MIN_PLATE_CHARS = 4
MAX_PLATE_CHARS = 10

UPSCALE_TARGET_HEIGHT = 80
IMAGE_INFERENCE_SIZE = 640

TRACK_IOU_THRESHOLD = 0.3
TRACK_MAX_AGE = 30
TRACK_DRAW_MAX_MISSED = 5

RIGHT_ROI_FRACTION = 0.25
RIGHT_ROI_UPSCALE = 1.8
RIGHT_ROI_CONF_SCALE = 0.65
MERGE_IOU_THRESH = 0.35
DISTANT_HEIGHT_PX = 32
OCR_ANGLE_RETRY_DEGREES = (8, 15)

_OCR_ERROR_PRINTED = False
_PREVIEW_ERROR_COUNT = 0
# =====================================================


# ------------------------------------------------------------------------
# Image enhancement functions (unchanged)
# ------------------------------------------------------------------------
def upscale_if_small(crop: np.ndarray, target_height: int) -> np.ndarray:
    h, w = crop.shape[:2]
    if h == 0 or w == 0:
        return crop
    if h < target_height:
        scale = target_height / float(h)
        new_w = max(1, int(w * scale))
        interp = cv2.INTER_LANCZOS4 if scale > 1 else cv2.INTER_AREA
        crop = cv2.resize(crop, (new_w, target_height), interpolation=interp)
    return crop

def apply_clahe(gray: np.ndarray, clip_limit: float = 3.0) -> np.ndarray:
    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(8, 8))
    return clahe.apply(gray)

def unsharp_mask(img: np.ndarray, amount: float = 1.5, sigma: float = 1.0) -> np.ndarray:
    blurred = cv2.GaussianBlur(img, (0, 0), sigma)
    return cv2.addWeighted(img, 1 + amount, blurred, -amount, 0)

def denoise(img: np.ndarray) -> np.ndarray:
    if len(img.shape) == 3:
        return cv2.fastNlMeansDenoisingColored(img, None, 7, 7, 7, 21)
    return cv2.fastNlMeansDenoising(img, None, 7, 7, 21)

def gamma_correct(img: np.ndarray, gamma: float = 1.4) -> np.ndarray:
    inv_gamma = 1.0 / gamma
    table = np.array([((i / 255.0) ** inv_gamma) * 255 for i in range(256)]).astype("uint8")
    return cv2.LUT(img, table)

def is_low_quality(gray: np.ndarray) -> Tuple[bool, bool]:
    lap_var = cv2.Laplacian(gray, cv2.CV_64F).var()
    contrast = gray.std()
    return lap_var < 60.0, contrast < 40.0

def generate_enhanced_variants(crop_bgr: np.ndarray, is_distant: bool = False) -> List[np.ndarray]:
    variants = []
    target_h = UPSCALE_TARGET_HEIGHT * (2 if is_distant else 1)
    crop_up = upscale_if_small(crop_bgr, target_h)
    variants.append(crop_up)

    source_h, source_w = crop_bgr.shape[:2]
    if source_h > 0 and source_w > 0 and source_h < target_h:
        high_res_h = int(target_h * 1.5)
        high_res_w = max(1, int(source_w * high_res_h / source_h))
        variants.append(cv2.resize(
            crop_bgr,
            (high_res_w, high_res_h),
            interpolation=cv2.INTER_CUBIC,
        ))

    gray = cv2.cvtColor(crop_up, cv2.COLOR_BGR2GRAY)
    is_blurry, is_low_contrast = is_low_quality(gray)

    clahe_gray = apply_clahe(gray)
    clahe_sharp = unsharp_mask(clahe_gray, amount=1.2, sigma=1.0)
    variants.append(cv2.cvtColor(clahe_sharp, cv2.COLOR_GRAY2BGR))

    if is_low_contrast or is_blurry or is_distant:
        variants.append(gamma_correct(denoise(crop_up), gamma=1.5))

    if is_blurry or is_distant:
        variants.append(unsharp_mask(crop_up, amount=2.0, sigma=1.5))

    if is_distant:
        bilateral = cv2.bilateralFilter(crop_up, d=7, sigmaColor=50, sigmaSpace=50)
        strong_clahe = apply_clahe(cv2.cvtColor(bilateral, cv2.COLOR_BGR2GRAY), clip_limit=4.5)
        variants.append(cv2.cvtColor(strong_clahe, cv2.COLOR_GRAY2BGR))

    return variants


def rotate_bound(image: np.ndarray, angle: float) -> np.ndarray:
    height, width = image.shape[:2]
    center = (width / 2.0, height / 2.0)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    cosine = abs(matrix[0, 0])
    sine = abs(matrix[0, 1])
    output_width = int(height * sine + width * cosine)
    output_height = int(height * cosine + width * sine)
    matrix[0, 2] += output_width / 2.0 - center[0]
    matrix[1, 2] += output_height / 2.0 - center[1]
    return cv2.warpAffine(
        image,
        matrix,
        (output_width, output_height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


def generate_angle_variants(crop_bgr: np.ndarray, is_distant: bool = False) -> List[np.ndarray]:
    target_height = UPSCALE_TARGET_HEIGHT * (2 if is_distant else 1)
    crop_up = upscale_if_small(crop_bgr, target_height)
    return [
        rotate_bound(crop_up, angle * direction)
        for angle in OCR_ANGLE_RETRY_DEGREES
        for direction in (-1, 1)
    ]


# ------------------------------------------------------------------------
# Generic OCR text cleanup
# ------------------------------------------------------------------------
def clean_plate_text(raw_text: str) -> Optional[str]:
    if not raw_text:
        return None
    text = re.sub(r"[^A-Za-z0-9]", "", raw_text.upper().replace("_", ""))
    if not (MIN_PLATE_CHARS <= len(text) <= MAX_PLATE_CHARS):
        return None
    return text


def recognize_variants(
    recognizer: LicensePlateRecognizer,
    variants: List[np.ndarray],
    raw_writer,
    frame_idx: int,
    track_id: int,
) -> Tuple[Optional[str], float]:
    best_text = None
    best_score = 0.0
    for variant in variants:
        for raw_text, confidence in run_ocr_engine(recognizer, variant):
            cleaned = clean_plate_text(raw_text)
            accepted = bool(cleaned and confidence >= OCR_CONF_THRESHOLD)
            raw_writer.writerow([
                datetime.now().isoformat(timespec='seconds'),
                frame_idx,
                track_id,
                raw_text,
                cleaned or '',
                f"{confidence:.3f}",
                accepted,
            ])
            if cleaned and confidence > best_score:
                best_text, best_score = cleaned, confidence
    return best_text, best_score


def safe_filename_fragment(text: str) -> str:
    """Strips anything that isn't filesystem-safe from a plate string used in a filename."""
    return re.sub(r"[^A-Za-z0-9_-]", "", text) or "UNKNOWN"


# ------------------------------------------------------------------------
# fast-plate-ocr call wrapper - visible errors (unchanged from v5)
# ------------------------------------------------------------------------
def run_ocr_engine(recognizer: LicensePlateRecognizer, image_bgr: np.ndarray) -> List[Tuple[str, float]]:
    global _OCR_ERROR_PRINTED

    if image_bgr is None or not hasattr(image_bgr, "shape") or image_bgr.shape[0] < 10 or image_bgr.shape[1] < 10:
        return []

    def _predict(arr: np.ndarray) -> List[Tuple[str, float]]:
        results = []
        preds = recognizer.run(arr, return_confidence=True)
        for pred in preds:
            plate_text = getattr(pred, "plate", None)
            char_probs = getattr(pred, "char_probs", None)
            if not plate_text:
                continue
            conf = float(np.mean(char_probs)) if char_probs is not None and len(char_probs) > 0 else 0.0
            results.append((plate_text, conf))
        return results

    try:
        if len(image_bgr.shape) == 2:
            rgb = cv2.cvtColor(image_bgr, cv2.COLOR_GRAY2RGB)
        elif image_bgr.shape[2] == 4:
            rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGRA2RGB)
        else:
            rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        return _predict(rgb)
    except Exception as exc:
        if not _OCR_ERROR_PRINTED:
            _OCR_ERROR_PRINTED = True
            print(f"[OCR ERROR] fast-plate-ocr inference failed (printed once): {type(exc).__name__}: {exc}")
        return []


# ------------------------------------------------------------------------
# IoU helper
# ------------------------------------------------------------------------
def iou(box_a, box_b) -> float:
    xa = max(box_a[0], box_b[0])
    ya = max(box_a[1], box_b[1])
    xb = min(box_a[2], box_b[2])
    yb = min(box_a[3], box_b[3])
    inter = max(0.0, xb - xa) * max(0.0, yb - ya)
    area_a = max(0.0, box_a[2] - box_a[0]) * max(0.0, box_a[3] - box_a[1])
    area_b = max(0.0, box_b[2] - box_b[0]) * max(0.0, box_b[3] - box_b[1])
    denom = area_a + area_b - inter
    return inter / denom if denom > 0 else 0.0


# ------------------------------------------------------------------------
# Robust SORT-style Track + Hungarian Matching
# ------------------------------------------------------------------------
class Track:
    _next_id = 1

    def __init__(self, bbox: Tuple[float, float, float, float], frame_idx: int):
        self.id = Track._next_id
        Track._next_id += 1
        self.bbox = bbox
        self.time_since_update = 0
        self.hits = 1
        self.first_frame = frame_idx
        self.last_frame = frame_idx
        self.last_ocr_frame = -999

        self.text_conf_sum: Dict[str, float] = {}
        self.text_count: Dict[str, int] = {}
        self.best_text: Optional[str] = None
        self.best_score: float = 0.0

        self.last_raw_text: Optional[str] = None
        self.last_raw_score: float = 0.0

        # NEW: highest-confidence single OCR attempt this track has ever
        # produced, and the raw (non-enhanced) crop that produced it - this
        # is what gets saved to cropped_plates/ for visual OCR verification.
        self.best_crop: Optional[np.ndarray] = None
        self.best_crop_score: float = 0.0
        self.crop_saved_for_text: Optional[str] = None  # avoids redundant disk writes

        self.kf = cv2.KalmanFilter(8, 4)
        self.kf.transitionMatrix = np.eye(8, dtype=np.float32)
        for i in range(4):
            self.kf.transitionMatrix[i, i + 4] = 1.0
        self.kf.measurementMatrix = np.eye(4, 8, dtype=np.float32)
        self.kf.processNoiseCov = np.eye(8, dtype=np.float32) * 1e-2
        self.kf.measurementNoiseCov = np.eye(4, dtype=np.float32) * 1e-1
        cx, cy, w, h = self._to_cxcywh(bbox)
        self.kf.statePost = np.array([cx, cy, w, h, 0, 0, 0, 0], dtype=np.float32).reshape(8, 1)

    @staticmethod
    def _to_cxcywh(bbox):
        x1, y1, x2, y2 = bbox
        return (x1 + x2) / 2.0, (y1 + y2) / 2.0, x2 - x1, y2 - y1

    @staticmethod
    def _to_xyxy(cx, cy, w, h):
        return cx - w / 2.0, cy - h / 2.0, cx + w / 2.0, cy + h / 2.0

    def predict(self):
        pred = self.kf.predict()
        cx, cy, w, h = float(pred[0]), float(pred[1]), float(pred[2]), float(pred[3])
        self.bbox = self._to_xyxy(cx, cy, max(w, 1.0), max(h, 1.0))
        self.time_since_update += 1
        return self.bbox

    def update(self, bbox: Tuple[float, float, float, float], frame_idx: int):
        cx, cy, w, h = self._to_cxcywh(bbox)
        meas = np.array([[cx], [cy], [w], [h]], dtype=np.float32)
        self.kf.correct(meas)
        self.bbox = bbox
        self.time_since_update = 0
        self.hits += 1
        self.last_frame = frame_idx

    def register_ocr(self, text: str, score: float) -> bool:
        prev_best = self.best_text
        self.text_conf_sum[text] = self.text_conf_sum.get(text, 0.0) + score
        self.text_count[text] = self.text_count.get(text, 0) + 1
        best = max(self.text_conf_sum, key=lambda t: self.text_conf_sum[t])
        self.best_text = best
        self.best_score = self.text_conf_sum[best] / self.text_count[best]
        return self.best_text != prev_best

    def maybe_update_crop(self, raw_crop_bgr: np.ndarray, score: float):
        """Keeps the raw (unenhanced) crop from whichever OCR attempt had the
        highest single-frame confidence, for saving to cropped_plates/."""
        if score > self.best_crop_score:
            self.best_crop_score = score
            self.best_crop = raw_crop_bgr.copy()


class IoUTracker:
    def __init__(self, iou_threshold=TRACK_IOU_THRESHOLD, max_age=TRACK_MAX_AGE):
        self.tracks: List[Track] = []
        self.all_tracks: List[Track] = []
        self.iou_threshold = iou_threshold
        self.max_age = max_age

    def update(self, detections: List[Tuple[float, float, float, float]], frame_idx: int) -> List[Track]:
        for t in self.tracks:
            t.predict()

        if not self.tracks:
            for d in detections:
                self.tracks.append(Track(d, frame_idx))
            return self.tracks

        if not detections:
            active_tracks = []
            for t in self.tracks:
                if t.time_since_update <= self.max_age:
                    active_tracks.append(t)
                else:
                    self.all_tracks.append(t)
            self.tracks = active_tracks
            return self.tracks

        num_tracks = len(self.tracks)
        num_dets = len(detections)
        cost_matrix = np.zeros((num_tracks, num_dets), dtype=np.float32)

        for i, t in enumerate(self.tracks):
            for j, d in enumerate(detections):
                iou_val = iou(t.bbox, d)

                cx_t = (t.bbox[0] + t.bbox[2]) / 2.0
                cy_t = (t.bbox[1] + t.bbox[3]) / 2.0
                cx_d = (d[0] + d[2]) / 2.0
                cy_d = (d[1] + d[3]) / 2.0
                dist = np.sqrt((cx_t - cx_d)**2 + (cy_t - cy_d)**2)

                diag_t = np.sqrt((t.bbox[2]-t.bbox[0])**2 + (t.bbox[3]-t.bbox[1])**2)
                diag_d = np.sqrt((d[2]-d[0])**2 + (d[3]-d[1])**2)
                avg_diag = max((diag_t + diag_d) / 2.0, 1e-5)
                norm_dist = dist / avg_diag

                cost_matrix[i, j] = (1.0 - iou_val) + 0.4 * norm_dist

        row_ind, col_ind = linear_sum_assignment(cost_matrix)

        matched_tracks = set()
        matched_dets = set()

        MAX_MATCH_COST = 2.0

        for r, c in zip(row_ind, col_ind):
            if cost_matrix[r, c] <= MAX_MATCH_COST:
                self.tracks[r].update(detections[c], frame_idx)
                matched_tracks.add(r)
                matched_dets.add(c)

        for j, d in enumerate(detections):
            if j not in matched_dets:
                self.tracks.append(Track(d, frame_idx))

        active_tracks = []
        for t in self.tracks:
            if t.time_since_update <= self.max_age:
                active_tracks.append(t)
            else:
                self.all_tracks.append(t)
        self.tracks = active_tracks

        return self.tracks


# ------------------------------------------------------------------------
# Detection: main pass + right-lane (distant/small plate) boosted pass
# ------------------------------------------------------------------------
def detect_plates(model: YOLO, frame: np.ndarray, width: int, height: int):
    detections = []

    results = model(frame, conf=CONFIDENCE, device=DEVICE, imgsz=IMAGE_INFERENCE_SIZE,
                     half=(DEVICE == 'cuda'), verbose=False)
    if results[0].boxes is not None and len(results[0].boxes) > 0:
        boxes = results[0].boxes.xyxy.cpu().numpy()
        confs = results[0].boxes.conf.cpu().numpy()
        for (x1, y1, x2, y2), c in zip(boxes, confs):
            detections.append([float(x1), float(y1), float(x2), float(y2), float(c), 'main'])

    roi_x1 = int(width * (1 - RIGHT_ROI_FRACTION))
    roi = frame[0:height, roi_x1:width]
    if roi.size > 0:
        roi_h, roi_w = roi.shape[:2]
        roi_up = cv2.resize(
            roi, (int(roi_w * RIGHT_ROI_UPSCALE), int(roi_h * RIGHT_ROI_UPSCALE)),
            interpolation=cv2.INTER_CUBIC
        )
        roi_results = model(roi_up, conf=CONFIDENCE * RIGHT_ROI_CONF_SCALE, device=DEVICE,
                             imgsz=IMAGE_INFERENCE_SIZE, half=(DEVICE == 'cuda'), verbose=False)
        if roi_results[0].boxes is not None and len(roi_results[0].boxes) > 0:
            rboxes = roi_results[0].boxes.xyxy.cpu().numpy()
            rconfs = roi_results[0].boxes.conf.cpu().numpy()
            for (x1, y1, x2, y2), c in zip(rboxes, rconfs):
                fx1 = x1 / RIGHT_ROI_UPSCALE + roi_x1
                fy1 = y1 / RIGHT_ROI_UPSCALE
                fx2 = x2 / RIGHT_ROI_UPSCALE + roi_x1
                fy2 = y2 / RIGHT_ROI_UPSCALE
                dup = any(
                    d[5] == 'main' and iou((fx1, fy1, fx2, fy2), d[:4]) > MERGE_IOU_THRESH
                    for d in detections
                )
                if not dup:
                    detections.append([fx1, fy1, fx2, fy2, float(c), 'right_boost'])

    return detections


# ------------------------------------------------------------------------
# Preview window helpers (forced, AnyDesk-friendly)
# ------------------------------------------------------------------------
def init_preview_window():
    """Creates a resizable named window up front. Doing this once before the
    loop starts resolves most remote-desktop 'first imshow call fails'
    quirks by itself."""
    try:
        cv2.namedWindow(PREVIEW_WINDOW_NAME, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(PREVIEW_WINDOW_NAME, *PREVIEW_WINDOW_SIZE)
        return True
    except cv2.error as exc:
        print(f"[PREVIEW WARNING] Could not create preview window: {exc}")
        print("[PREVIEW WARNING] If running headless (no display/AnyDesk session "
              "attached), set SHOW_PREVIEW = False to suppress further attempts.")
        return False


def show_preview_frame(annotated: np.ndarray) -> bool:
    """Shows a frame. Returns False if 'q' was pressed (caller should stop).
    Does NOT permanently disable preview on error when FORCE_LIVE_PREVIEW is
    True - it just reports the error and keeps trying next frame, since a
    remote-desktop session's display can recover from a transient failure."""
    global _PREVIEW_ERROR_COUNT
    try:
        cv2.imshow(PREVIEW_WINDOW_NAME, annotated)
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            return False
    except cv2.error as exc:
        _PREVIEW_ERROR_COUNT += 1
        if _PREVIEW_ERROR_COUNT <= 5 or _PREVIEW_ERROR_COUNT % 100 == 0:
            print(f"[PREVIEW ERROR #{_PREVIEW_ERROR_COUNT}] {exc}")
        if not FORCE_LIVE_PREVIEW:
            return True  # caller may choose to disable SHOW_PREVIEW itself
    return True


# ------------------------------------------------------------------------
# Cropped plate saving
# ------------------------------------------------------------------------
def save_track_crop(track: Track, directory: str):
    """Saves this track's best (highest single-attempt confidence) raw crop
    to disk as ID{track_id}_{plate_text}.jpg. Skipped if best_text/best_crop
    aren't set yet, or if the current best_text was already saved (avoids
    rewriting the same file every frame once a track is stable)."""
    if track.best_text is None or track.best_crop is None:
        return
    if track.crop_saved_for_text == track.best_text:
        return
    filename = f"ID{track.id}_{safe_filename_fragment(track.best_text)}.jpg"
    path = os.path.join(directory, filename)
    try:
        cv2.imwrite(path, track.best_crop)
        track.crop_saved_for_text = track.best_text
    except Exception as exc:
        print(f"[WARNING] Failed to save cropped plate for track {track.id}: {exc}")


# ------------------------------------------------------------------------
# Main Pipeline
# ------------------------------------------------------------------------
def main():
    print(f"[INFO] Running pipeline on device: {DEVICE}")

    os.makedirs(CROPPED_PLATES_DIR, exist_ok=True)
    print(f"[INFO] Cropped plate images will be saved to: {os.path.abspath(CROPPED_PLATES_DIR)}")

    print(f"[INFO] Loading YOLO detector from: {MODEL_PATH}")
    model = YOLO(MODEL_PATH)

    print(f"[INFO] Initializing fast-plate-ocr engine: {OCR_MODEL_NAME}")
    ocr = LicensePlateRecognizer(OCR_MODEL_NAME)

    cap = cv2.VideoCapture(VIDEO_PATH)
    if not cap.isOpened():
        print(f"[ERROR] Cannot open video file: {VIDEO_PATH}")
        return

    fps = int(cap.get(cv2.CAP_PROP_FPS)) or 25
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"[INFO] Video Details: {width}x{height} @ {fps} FPS | Total Frames: {total_frames}")

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(OUTPUT_VIDEO, fourcc, fps, (width, height))
    if not out.isOpened():
        print("[WARNING] Could not initialize VideoWriter. Annotated video will not be saved.")
        out = None

    preview_ready = False
    if SHOW_PREVIEW:
        preview_ready = init_preview_window()

    event_file = open(EVENT_CSV_LOG, 'w', newline='', encoding='utf-8')
    event_writer = csv.writer(event_file)
    event_writer.writerow(['timestamp', 'frame', 'track_id', 'plate_text', 'confidence', 'zone'])

    raw_file = open(RAW_READS_CSV_LOG, 'w', newline='', encoding='utf-8')
    raw_writer = csv.writer(raw_file)
    raw_writer.writerow(['timestamp', 'frame', 'track_id', 'raw_text', 'cleaned_text', 'confidence', 'accepted'])

    tracker = IoUTracker()

    frame_count = 0
    processed = 0
    start_time = time.time()
    right_zone_x = int(width * (1 - RIGHT_ROI_FRACTION))

    print("[INFO] Processing active...")

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            frame_count += 1

            if SKIP_FRAMES > 0 and (frame_count % (SKIP_FRAMES + 1) != 0):
                if out is not None:
                    out.write(frame)
                continue

            processed += 1
            detections = detect_plates(model, frame, width, height)
            det_boxes = [(d[0], d[1], d[2], d[3]) for d in detections]
            active_tracks = tracker.update(det_boxes, frame_count)

            annotated = frame.copy()

            for t in active_tracks:
                if t.time_since_update > TRACK_DRAW_MAX_MISSED:
                    continue

                x1, y1, x2, y2 = [int(max(0, v)) for v in t.bbox]
                x2, y2 = min(width, x2), min(height, y2)
                if x2 <= x1 or y2 <= y1:
                    continue

                is_distant = (x1 >= right_zone_x) or ((y2 - y1) < DISTANT_HEIGHT_PX)

                should_ocr = (
                    t.time_since_update == 0 and (
                        (t.best_score < EARLY_STOP_CONF and frame_count - t.last_ocr_frame >= OCR_INTERVAL_ACTIVE)
                        or (t.best_score >= EARLY_STOP_CONF and frame_count - t.last_ocr_frame >= OCR_INTERVAL_CONFIRMED)
                    )
                )

                if should_ocr:
                    crop = frame[y1:y2, x1:x2]
                    if crop is not None and crop.size > 0 and crop.shape[0] >= 10 and crop.shape[1] >= 10:
                        t.last_ocr_frame = frame_count
                        variants = generate_enhanced_variants(crop, is_distant=is_distant)
                        frame_best_text, frame_best_score = recognize_variants(
                            ocr, variants, raw_writer, frame_count, t.id
                        )
                        if frame_best_score < OCR_CONF_THRESHOLD:
                            angle_text, angle_score = recognize_variants(
                                ocr,
                                generate_angle_variants(crop, is_distant=is_distant),
                                raw_writer,
                                frame_count,
                                t.id,
                            )
                            if angle_score > frame_best_score:
                                frame_best_text, frame_best_score = angle_text, angle_score
                        raw_file.flush()

                        if frame_best_text:
                            t.last_raw_text = frame_best_text
                            t.last_raw_score = frame_best_score
                            # NEW: remember the raw (unenhanced) crop for this
                            # attempt if it's this track's best one yet.
                            t.maybe_update_crop(crop, frame_best_score)

                        if frame_best_text and frame_best_score >= OCR_CONF_THRESHOLD:
                            changed = t.register_ocr(frame_best_text, frame_best_score)
                            if changed:
                                zone = 'right_boost' if is_distant else 'main'
                                event_writer.writerow([
                                    datetime.now().isoformat(timespec='seconds'),
                                    frame_count, t.id, t.best_text, f"{t.best_score:.3f}", zone
                                ])
                                event_file.flush()
                            # NEW: save/refresh this track's cropped plate image
                            # as soon as it's confirmed (live, during processing).
                            save_track_crop(t, CROPPED_PLATES_DIR)

                has_confirmed = t.best_text is not None
                has_provisional = (not has_confirmed) and t.last_raw_text is not None

                if has_confirmed:
                    color = (0, 255, 0)
                    label = t.best_text
                elif has_provisional:
                    color = (0, 165, 255)
                    label = f"{t.last_raw_text}?"
                else:
                    color = (0, 165, 255)
                    label = None

                cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)

                if label:
                    (tw, th), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
                    text_x = x1 + max(0, ((x2 - x1) - tw) // 2)
                    text_y = y1 + max(th, ((y2 - y1) + th) // 2)
                    cv2.putText(annotated, label, (text_x, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 4, cv2.LINE_AA)
                    cv2.putText(annotated, label, (text_x, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2, cv2.LINE_AA)
                else:
                    cv2.putText(annotated, f"ID {t.id}", (x1, max(15, y1 - 5)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1, cv2.LINE_AA)

            cv2.line(annotated, (right_zone_x, 0), (right_zone_x, height), (255, 200, 0), 1)

            info = f"Processed:{processed} | Active tracks:{len(active_tracks)}"
            cv2.putText(annotated, info, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 0), 2)

            if out is not None:
                out.write(annotated)

            if SHOW_PREVIEW and (preview_ready or FORCE_LIVE_PREVIEW):
                keep_going = show_preview_frame(annotated)
                if not keep_going:
                    break

            if processed % 50 == 0:
                elapsed = time.time() - start_time
                speed = processed / elapsed if elapsed > 0 else 0
                print(f"[PROGRESS] Frames: {processed}/{total_frames} | "
                      f"Active tracks: {len(active_tracks)} | Speed: {speed:.1f} FPS")

    finally:
        cap.release()
        if out is not None:
            out.release()
        event_file.close()
        raw_file.close()
        if SHOW_PREVIEW:
            cv2.destroyAllWindows()

        final_tracks = tracker.all_tracks + tracker.tracks
        valid_tracks = [t for t in final_tracks if t.best_text is not None]

        # Idempotent final pass: guarantees every track that ended up in the
        # summary CSV also has a saved cropped image, even if the loop was
        # interrupted (crash/Ctrl+C) before its live save happened.
        for t in valid_tracks:
            save_track_crop(t, CROPPED_PLATES_DIR)

        with open(SUMMARY_CSV_LOG, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['track_id', 'best_plate_text', 'confidence', 'first_frame', 'last_frame', 'cropped_image'])
            for t in sorted(valid_tracks, key=lambda t: t.id):
                image_name = f"ID{t.id}_{safe_filename_fragment(t.best_text)}.jpg" if t.best_crop is not None else ''
                writer.writerow([t.id, t.best_text, f"{t.best_score:.3f}", t.first_frame, t.last_frame, image_name])

        elapsed = time.time() - start_time
        print("\n" + "=" * 50)
        print("[SUCCESS] ANPR Pipeline Completed")
        print(f"[INFO] Processed Frames: {processed}")
        print(f"[INFO] Total Execution Time: {elapsed:.2f}s | Average Speed: {processed / max(elapsed, 1):.2f} FPS")
        print(f"[INFO] Saved Annotated Video: {OUTPUT_VIDEO}")
        print(f"[INFO] Saved Event Log: {EVENT_CSV_LOG}")
        print(f"[INFO] Saved Raw Reads Log: {RAW_READS_CSV_LOG} (inspect this to calibrate OCR_CONF_THRESHOLD)")
        print(f"[INFO] Saved Plate Summary: {SUMMARY_CSV_LOG} ({len(valid_tracks)} unique plates found)")
        print(f"[INFO] Saved Cropped Plate Images: {CROPPED_PLATES_DIR}/ "
              f"({sum(1 for t in valid_tracks if t.best_crop is not None)} images)")
        if DEVICE == 'cuda':
            print(f"[GPU] Peak VRAM Allocated: {torch.cuda.memory_allocated() / 1024**2:.2f} MB")
        print("=" * 50)


if __name__ == "__main__":
    main()