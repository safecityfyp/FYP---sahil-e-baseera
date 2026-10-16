"""Conservative camera-view checks and a versioned, integrity-checked calibration cache."""
import hashlib
import json
import re
from pathlib import Path

import cv2
import numpy as np

SCHEMA_VERSION = 1


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def read_views(video, start_s, duration_s):
    capture = cv2.VideoCapture(str(video))
    try:
        if not capture.isOpened():
            raise ValueError('Cannot decode source video.')
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        if fps <= 0 or min(width, height, frames) <= 0:
            raise ValueError('Invalid video metadata.')
        start, end = round(start_s * fps), round((start_s + duration_s) * fps)
        if start < 0 or end <= start or end > frames:
            raise ValueError('Requested interval is outside the source video.')
        views = []
        indices = np.unique(np.linspace(start, end - 1, 5).astype(int))
        for index in indices:
            capture.set(cv2.CAP_PROP_POS_FRAMES, int(index))
            ok, frame = capture.read()
            if not ok:
                raise ValueError(f'Cannot decode view-check frame {index}.')
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            views.append(cv2.resize(gray, (960, round(height * 960 / width))))
        return {'width': width, 'height': height, 'fps': fps, 'frames': frames,
                'start_frame': start, 'end_frame': end,
                'view_check_frames': indices.tolist()}, views
    finally:
        capture.release()


def compare_views(reference, current):
    """Reject uncertain matches as well as sufficiently large shifts, zooms or rotations.

    This is a sampled visual consistency check, not proof that the camera never moved.
    Exclude timestamps, borders and foreground overlays; RANSAC discounts moving vehicles.
    """
    if reference is None or current is None or reference.shape != current.shape:
        return {'valid': False, 'reason': 'view_image_shape_changed'}
    height, width = reference.shape
    mask = np.zeros_like(reference, dtype=np.uint8)
    mask[round(.15 * height):round(.88 * height), round(.03 * width):round(.97 * width)] = 255
    detector = cv2.ORB_create(nfeatures=5000, fastThreshold=12)
    kp1, desc1 = detector.detectAndCompute(reference, mask)
    kp2, desc2 = detector.detectAndCompute(current, mask)
    if desc1 is None or desc2 is None:
        return {'valid': False, 'reason': 'insufficient_static_features'}
    pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(desc1, desc2, k=2)
    matches = [a for pair in pairs if len(pair) == 2 for a, b in [pair] if a.distance < .7 * b.distance]
    if len(matches) < 25:
        return {'valid': False, 'reason': 'insufficient_view_matches', 'matches': len(matches)}
    a = np.float32([kp1[m.queryIdx].pt for m in matches])
    b = np.float32([kp2[m.trainIdx].pt for m in matches])
    matrix, inliers = cv2.findHomography(a, b, cv2.RANSAC, 3.0)
    if matrix is None or inliers is None or not np.isfinite(matrix).all():
        return {'valid': False, 'reason': 'view_alignment_failed'}
    selected = inliers.ravel().astype(bool)
    count = int(selected.sum())
    coverage = min(abs(cv2.contourArea(cv2.convexHull(p[selected]))) / (width * height)
                   for p in [a, b]) if count >= 3 else 0
    corners = np.float32([[0, 0], [width, 0], [width, height], [0, height]])
    projected = cv2.perspectiveTransform(corners[None], matrix)[0]
    displacement = float(np.max(np.linalg.norm((projected - corners) / [width, height], axis=1)))
    valid = count >= 25 and count / len(matches) >= .5 and coverage >= .10 and displacement <= .012
    return {'valid': bool(valid), 'reason': 'consistent_view' if valid else 'view_changed_or_uncertain',
            'matches': len(matches), 'inliers': count, 'feature_coverage_fraction': coverage,
            'max_normalized_corner_displacement': displacement}


def stable_view(views):
    comparisons = [compare_views(views[0], view) for view in views[1:]]
    return {'valid': bool(comparisons) and all(item['valid'] for item in comparisons),
            'comparisons': comparisons,
            'limitation': 'Five sampled frames cannot exclude brief camera movement between samples.'}


def valid_calibration(calibration):
    if not isinstance(calibration, dict):
        return False
    accepted = 0
    try:
        for side in ['left', 'right']:
            mapping = calibration.get(side, {})
            if not mapping.get('accepted'):
                continue
            accepted += 1
            matrices = [mapping['H_image_to_experimental_meters'], *mapping['alternative_mappings']]
            if len(matrices) < 2:
                return False
            for value in matrices:
                matrix = np.array(value, dtype=float)
                if matrix.shape != (3, 3) or not np.isfinite(matrix).all() or abs(np.linalg.det(matrix)) < 1e-12:
                    return False
            hull = np.array(mapping['support_hull_image'], dtype=np.float32)
            if hull.ndim != 2 or hull.shape[1] != 2 or len(hull) < 3 or not np.isfinite(hull).all():
                return False
            if not cv2.isContourConvex(hull) or abs(cv2.contourArea(hull)) < 300:
                return False
    except (KeyError, TypeError, ValueError, cv2.error):
        return False
    return accepted > 0


class CalibrationCache:
    def __init__(self, directory, camera_id):
        if not camera_id.strip():
            raise ValueError('A nonempty camera ID is required.')
        slug = re.sub(r'[^a-zA-Z0-9_-]+', '-', camera_id).strip('-')[:48] or 'camera'
        self.camera_id = camera_id
        self.directory = Path(directory) / (slug + '-' + canonical_hash(camera_id)[:12])
        self.path = self.directory / 'calibration_cache.json'

    def load(self, signature, views):
        if not self.path.exists():
            return None, {'status': 'miss', 'reason': 'no_saved_calibration'}
        try:
            entry = json.loads(self.path.read_text(encoding='utf-8'))
            if entry['schema_version'] != SCHEMA_VERSION or entry['camera_id'] != self.camera_id:
                return None, {'status': 'miss', 'reason': 'cache_schema_or_camera_changed'}
            if entry['signature'] != signature:
                return None, {'status': 'miss', 'reason': 'resolution_model_or_calibration_settings_changed'}
            if canonical_hash(entry['calibration']) != entry['calibration_sha256'] or not valid_calibration(entry['calibration']):
                return None, {'status': 'miss', 'reason': 'invalid_calibration_data'}
            view_path = self.directory / 'reference_view.png'
            if file_sha256(view_path) != entry['reference_sha256']:
                return None, {'status': 'miss', 'reason': 'invalid_reference_image'}
            reference = cv2.imread(str(view_path), cv2.IMREAD_GRAYSCALE)
            checks = [compare_views(reference, current) for current in views]
            if not all(check['valid'] for check in checks):
                return None, {'status': 'miss', 'reason': 'camera_view_changed_or_uncertain', 'view_checks': checks}
            return entry['calibration'], {'status': 'hit', 'reason': 'saved_calibration_matches_camera_view',
                                          'view_checks': checks}
        except (OSError, ValueError, KeyError, TypeError, cv2.error):
            return None, {'status': 'miss', 'reason': 'cache_unreadable_or_corrupt'}

    def save(self, signature, reference, calibration, provenance):
        if not valid_calibration(calibration):
            raise ValueError('No usable road mapping; calibration will not be cached.')
        self.directory.mkdir(parents=True, exist_ok=True)
        view_path = self.directory / 'reference_view.png'
        if not cv2.imwrite(str(view_path), reference):
            raise OSError('Could not save camera reference.')
        entry = {'schema_version': SCHEMA_VERSION, 'camera_id': self.camera_id,
                 'signature': signature, 'calibration': calibration,
                 'calibration_sha256': canonical_hash(calibration),
                 'reference_sha256': file_sha256(view_path), 'provenance': provenance,
                 'accuracy_validated': False}
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(entry, indent=2, allow_nan=False), encoding='utf-8')
        temporary.replace(self.path)
