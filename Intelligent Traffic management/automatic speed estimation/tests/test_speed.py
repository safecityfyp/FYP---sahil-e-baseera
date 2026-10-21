"""Meaningful checks for long-video motion, region and local-speed behavior."""
import json
from pathlib import Path
import unittest

import numpy as np

from speed_estimation.geometry import project
from speed_estimation.calibration import motion_qualified,region_for,fit_region,ground_order,footprints
from speed_estimation.speed import local_velocity,split_segments
from tests.fixtures import synthetic


class CCTVTests(unittest.TestCase):
    def test_acceleration(self):
        times=np.arange(0,6.01,.4)
        centers=np.c_[2*times+.5*times**2,np.zeros(len(times))]
        result=local_velocity(times,centers,3.2)
        self.assertAlmostEqual(result['speed_kmh'],(2+3.2)*3.6,places=5)

    def test_turning(self):
        times=np.arange(0,8.01,.4)
        # Circular path at 5 m/s; its derivative must include both world axes.
        centers=np.c_[30*np.cos(times/6),30*np.sin(times/6)]
        result=local_velocity(times,centers,4)
        self.assertLess(abs(result['speed_kmh']-18),.12)

    def test_stationary_is_not_calibration_evidence(self):
        records=[dict(time_s=i*.4,quad=[[100,100],[200,100],[200,140],[100,140]]) for i in range(20)]
        self.assertFalse(motion_qualified(records))
        moving=[dict(time_s=i*.4,quad=(np.array(r['quad'])+[0,i*10]).tolist()) for i,r in enumerate(records)]
        self.assertTrue(motion_qualified(moving))

    def test_pinned_xy_checkpoint_ground_face(self):
        config=json.loads((Path(__file__).resolve().parents[1]/'configs'/'cameras.json').read_text())
        p=config['cameras']['commercial_ii_01']
        quad=np.array([[550,650],[580,550],[680,550],[650,650]])
        observations=[dict(track_id=1,time_s=i*.4,frame_index=i*10,geometry_confidence=.9,association_iou=.9,
                           keypoints=np.r_[quad+[0,i*8],quad+[0,i*8-80]].tolist()) for i in range(12)]
        self.assertEqual(ground_order(observations)['indices'],[0,1,2,3])
        records,counts=footprints(observations,p,1920,1080)
        self.assertEqual(len(records),12)
        self.assertIsNone(records[0]['confidence'])

    def test_gaps_and_region_changes_split_tracks(self):
        records=[dict(time_s=t,region=r) for t,r in [(0,'a'),(.4,'a'),(2,'a'),(2.4,'b'),(2.8,'b')]]
        self.assertEqual([len(s) for s in split_segments(records)],[2,1,2])

    def test_road_region_excludes_median_and_parking(self):
        config=json.loads((Path(__file__).resolve().parents[1]/'configs'/'cameras.json').read_text())
        p=config['cameras']['commercial_ii_01']
        self.assertIsNone(region_for([630,410],p,1280,720))
        self.assertEqual(region_for([400,460],p,1280,720),'left_carriageway')
        self.assertEqual(region_for([800,460],p,1280,720),'right_carriageway')

    def test_insufficient_independent_cars_rejects(self):
        records=[dict(track_id=1,time_s=i*.4,quad=[[0,0],[4.5,0],[4.5,1.8],[0,1.8]]) for i in range(100)]
        result=fit_region(records,1920,1080)
        self.assertFalse(result['accepted'])
        self.assertEqual(result['track_ids'],[1])

    def test_multi_car_projective_fit_recovers_known_metric_scale(self):
        records=synthetic()
        result=fit_region(records,2560,1440)
        self.assertTrue(result['accepted'])
        H=np.array(result['H_image_to_experimental_meters'])
        group=[r for r in records if r['track_id']==2]
        times=np.array([r['time_s'] for r in group])
        centers=project(np.array([r['quad'] for r in group]),H).mean(axis=1)
        speed=local_velocity(times,centers,1.5)
        self.assertLess(abs(speed['speed_kmh']-14.4),.1)

    def test_robust_local_fit_reduces_single_bad_footprint(self):
        times=np.arange(0,5.01,.2);centers=np.c_[3*times,np.zeros(len(times))]
        centers[12]+=[2,-2]
        result=local_velocity(times,centers,2.4)
        self.assertLess(abs(result['speed_kmh']-10.8),.4)

    def test_no_speed_from_too_short_time_span(self):
        times=np.arange(0,.81,.2)
        self.assertIsNone(local_velocity(times,np.c_[times,np.zeros(len(times))],.4))

    def test_close_view_short_pass_uses_actual_elapsed_time(self):
        times=np.arange(0,.61,.1)
        centers=np.c_[times*32.3/3.6,np.zeros(len(times))]
        result=local_velocity(times,centers,.3,window_s=1.2,minimum_span_s=.35,quadratic_minimum_span_s=.8)
        self.assertAlmostEqual(result['speed_kmh'],32.3,places=6)


if __name__=='__main__':unittest.main()
