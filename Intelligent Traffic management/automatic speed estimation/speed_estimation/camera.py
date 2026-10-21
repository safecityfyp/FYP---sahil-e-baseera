"""Sampled checks for changes in a fixed camera view."""
import cv2
import numpy as np


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
