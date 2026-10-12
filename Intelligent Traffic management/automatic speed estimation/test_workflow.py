"""Behavior checks for calibration reuse, invalidation and unavailable results."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

import calibrate_speed as speed
from camera_cache import CalibrationCache, compare_views
import workflow

ROOT = Path(__file__).resolve().parent


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        report = json.loads((ROOT / 'output/inputs/geometry/geometry_run_report.json').read_text())
        observations = json.loads((ROOT / 'output/inputs/geometry/observations.json').read_text())
        cls.records = speed.prepare(observations, report['ground_indices'], report['width'], report['height'])
        cls.calibration = speed.fit_road_mappings(cls.records, report)
        rng = np.random.default_rng(8)
        cls.view = rng.integers(0, 256, (540, 960), dtype=np.uint8)

    def test_cache_requires_identity_settings_integrity_and_view_match(self):
        with tempfile.TemporaryDirectory() as temporary:
            cache = CalibrationCache(temporary, 'A3/CH14')
            self.assertIsNone(cache.load({'width': 2560}, [self.view])[0])
            cache.save({'width': 2560}, self.view, self.calibration, {})
            self.assertIsNotNone(cache.load({'width': 2560}, [self.view])[0])
            self.assertIsNone(cache.load({'width': 1280}, [self.view])[0])
            other = CalibrationCache(temporary, 'another-camera')
            self.assertIsNone(other.load({'width': 2560}, [self.view])[0])
            moved = cv2.warpAffine(self.view, np.float32([[1, 0, 50], [0, 1, 0]]), (960, 540))
            self.assertIsNone(cache.load({'width': 2560}, [moved])[0])
            entry = json.loads(cache.path.read_text())
            entry['calibration']['left']['H_image_to_experimental_meters'][0][0] += 1
            cache.path.write_text(json.dumps(entry))
            self.assertIsNone(cache.load({'width': 2560}, [self.view])[0])
            cache.path.write_text('{broken')
            self.assertIsNone(cache.load({'width': 2560}, [self.view])[0])

    def test_zoom_resolution_and_textureless_views_are_rejected(self):
        transform = cv2.getRotationMatrix2D((480, 270), 0, 1.08)
        zoomed = cv2.warpAffine(self.view, transform, (960, 540))
        self.assertFalse(compare_views(self.view, zoomed)['valid'])
        self.assertFalse(compare_views(self.view, self.view[:, :-10])['valid'])
        self.assertFalse(compare_views(np.zeros_like(self.view), np.zeros_like(self.view))['valid'])

    def test_cached_mapping_produces_same_speeds_without_refitting(self):
        expected = json.loads((ROOT / 'output/vehicle_speed_estimates.json').read_text())
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(io.StringIO()):
            with patch.object(speed, 'fit_road_mappings', side_effect=AssertionError('Unexpected recalibration')):
                speed.run(calibration=self.calibration, geometry_dir=ROOT / 'output/inputs/geometry', output_dir=temporary)
            actual = json.loads((Path(temporary) / 'vehicle_speed_estimates.json').read_text())
        self.assertEqual({r['track_id'] for r in actual}, {1, 115, 147, 175})
        by_id = {r['track_id']: r for r in expected}
        for row in actual:
            self.assertAlmostEqual(row['experimental_kmh'], by_id[row['track_id']]['experimental_kmh'], places=4)

    def test_empty_calibration_clears_previous_results(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(io.StringIO()):
            path = Path(temporary)
            (path / 'experimental_speeds.csv').write_text('stale result')
            speed.run(calibration={}, geometry_dir=ROOT / 'output/inputs/geometry', output_dir=path)
            self.assertEqual(json.loads((path / 'vehicle_speed_estimates.json').read_text()), [])
            self.assertEqual(len((path / 'experimental_speeds.csv').read_text().splitlines()), 1)

    def test_no_speeds_outside_calibration_support(self):
        shifted = [{**r, 'quad': (np.array(r['quad']) + [10000, 0]).tolist()} for r in self.records]
        self.assertEqual(speed.calculate_speed_rows(shifted, self.calibration), [])

    def test_input_bundles_require_matching_video_and_untampered_artifacts(self):
        bundle = ROOT / 'output/inputs'
        identity = json.loads((bundle / 'input_manifest.json').read_text())['identity']
        self.assertTrue(workflow.verified_inputs(bundle, identity))
        self.assertFalse(workflow.verified_inputs(bundle, {**identity, 'source_sha256': 'different-video'}))
        with tempfile.TemporaryDirectory() as temporary:
            copy = Path(temporary)
            workflow.copy_inputs(bundle, copy)
            (copy / 'geometry/observations.json').write_text('[]')
            self.assertFalse(workflow.verified_inputs(copy, identity))

    def test_changed_view_stops_before_inference_or_speed_calculation(self):
        with tempfile.TemporaryDirectory() as temporary:
            video = Path(temporary) / 'test.mp4'
            video.write_bytes(b'stub')
            args = workflow.parser().parse_args(['--video', str(video), '--camera-id', 'test',
                                                 '--work-dir', temporary, '--no-render'])
            with patch.object(workflow, 'read_views', return_value=({}, [self.view, self.view])), \
                 patch.object(workflow, 'stable_view', return_value={'valid': False}), \
                 patch.object(workflow, 'inference_inputs', side_effect=AssertionError('Inference should not run')), \
                 contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code, folder = workflow.run_workflow(args)
            self.assertEqual(code, 2)
            self.assertEqual(json.loads((folder / 'workflow_report.json').read_text())['status'], 'failed')
            self.assertFalse((folder / 'speed').exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
