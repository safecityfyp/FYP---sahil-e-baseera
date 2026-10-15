"""Meaningful mathematical and label-independence checks for the video benchmark."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from benchmark_speed import projective_delay,load_clip
from calibrate_speed import project
from reference_calibration import register_road,estimate_reference_speed,refine_metric_scale
from validation_experiment import predict,PILOT_NAMES

ROOT=Path(__file__).resolve().parent


class ValidationTests(unittest.TestCase):
    def test_projective_delay_recovers_known_constant_motion(self):
        image_from_world=np.array([[1000,960,0],[0,540,1200],[0,1,0]],dtype=float)
        rows=[]
        for time in np.linspace(0,2,30):
            x=1;y=12+4*time
            quad=np.array([[x-.9,y-2.25],[x-.9,y+2.25],[x+.9,y+2.25],[x+.9,y-2.25]])
            rows.append({'time_s':float(time),'quad':project(quad,image_from_world).tolist()})
        estimate=projective_delay(rows,4.5)
        self.assertAlmostEqual(estimate['raw_kmh'],14.4,delta=.1)

    def test_reference_speed_calculation_is_metric_distance_per_time(self):
        times=np.linspace(0,2,30)
        world=np.c_[np.ones(len(times))*2,10+4*times]
        camera=np.array([[1000,960,0],[0,540,1200],[0,1,0]],dtype=float)
        image=project(world,camera)
        result=estimate_reference_speed(image,times,{'H_image_to_meters':np.linalg.inv(camera).tolist()})
        self.assertAlmostEqual(result['estimated_kmh'],14.4,places=5)

    def test_road_registration_accepts_identity_and_rejects_missing_evidence(self):
        rng=np.random.default_rng(4)
        image=rng.integers(0,256,(540,960),dtype=np.uint8)
        H,evidence=register_road(image,image)
        self.assertTrue(evidence['accepted'])
        self.assertTrue(np.allclose(H,np.eye(3),atol=1e-4))
        H,evidence=register_road(np.zeros_like(image),image)
        self.assertIsNone(H)
        self.assertFalse(evidence['accepted'])

    def test_prediction_does_not_read_speed_from_video_name(self):
        folder=ROOT/'outputs/mercedes_pilot/validation_inference/MercedesAMG550_30'
        if not folder.exists():
            folder=ROOT/'output/mercedes_validation/inference/MercedesAMG550_30'
        if not folder.exists():self.skipTest('Run or download the pilot inference first.')
        observations,report=load_clip(folder)
        calibration=json.loads((ROOT/'output/mercedes_validation/pilot_frozen_calibration.json').read_text())['reference_calibration']
        image=cv2.imread(str(folder/'reference.jpg'))
        first=predict(observations,{**report,'source_video':'anonymous.MP4'},image,image,calibration)
        second=predict(observations,{**report,'source_video':'MercedesAMG550_999.MP4'},image,image,calibration)
        self.assertTrue(first['available'])
        self.assertEqual(first['estimated_kmh'],second['estimated_kmh'])

    def test_three_pilot_names_are_fixed(self):
        self.assertEqual(PILOT_NAMES,{'MercedesAMG550_30.MP4','MercedesAMG550_60.MP4','MercedesAMG550_100.MP4'})

    def test_metric_scale_is_one_multiplier_fitted_only_on_supplied_pilots(self):
        initial=np.array([30,57.0767,100.0056])
        reference=np.array([30,60,100])
        scale,maximum=refine_metric_scale(initial,reference)
        self.assertLess(maximum,2)
        self.assertAlmostEqual(np.max(np.abs(initial*scale-reference)),maximum,places=6)
        self.assertTrue(.99<scale<1.03)


if __name__=='__main__':unittest.main(verbosity=2)
