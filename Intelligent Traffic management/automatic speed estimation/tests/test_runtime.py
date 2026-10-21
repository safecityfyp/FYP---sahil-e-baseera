"""Deployment checks with synthetic input and committed configuration only."""
import gzip
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import numpy as np

from speed_estimation.calibration import calibrate
from tests.fixtures import synthetic

ROOT=Path(__file__).resolve().parents[1]


class RuntimeTests(unittest.TestCase):
    def test_committed_mappings_match_camera_profiles(self):
        config=json.loads((ROOT/'configs/cameras.json').read_text())
        for camera,profile in config['cameras'].items():
            saved=json.loads((ROOT/'calibrations'/f'{camera}.json').read_text())
            self.assertEqual(saved['camera_id'],camera)
            self.assertEqual(saved['source_sha256'],profile['sha256'])
            self.assertEqual(saved['profile'],profile)
            self.assertTrue(saved['all_regions_accepted'])

    def test_command_help_needs_no_model_library_or_weights(self):
        # Block neural libraries explicitly; CPU stages/help must stay usable.
        code='''
import importlib.abc,runpy,sys
class BlockNeural(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.split('.')[0] in {'ultralytics','torch'}:
            raise ImportError('Neural library was imported during command help')
sys.meta_path.insert(0,BlockNeural())
sys.argv=[sys.argv[1],'--help']
runpy.run_path(sys.argv[0],run_name='__main__')
'''
        for script in ['calibrate.py','estimate_speed.py','extract_tracks.py','render_video.py','download_models.py']:
            completed=subprocess.run([sys.executable,'-c',code,script],cwd=ROOT,capture_output=True,text=True)
            self.assertEqual(completed.returncode,0,script+'\n'+completed.stderr)
            self.assertIn('usage:',completed.stdout)

    def test_custom_profile_calibrates_synthetic_measurements(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            measured=folder/'measurements';measured.mkdir()
            profile=dict(display_name='Synthetic',video='synthetic.mp4',sha256='a'*64,
                         regions={'road':[[0,0],[1,0],[1,1],[0,1]]})
            config=dict(cameras={'synthetic':profile},calibration_windows_s=[3],
                        minimum_cars_per_region=6,preferred_cars_per_region=6)
            profiles=folder/'cameras.json';profiles.write_text(json.dumps(config))
            report=dict(camera_id='synthetic',source_sha256='a'*64,width=2560,height=1440,fps=30,stop_s=3)
            (measured/'inference_report.json').write_text(json.dumps(report))
            with gzip.open(measured/'observations.jsonl.gz','wt') as stream:
                for row in synthetic():
                    quad=np.array(row['quad'])
                    observation=dict(track_id=row['track_id'],time_s=row['time_s'],frame_index=round(row['time_s']*30),
                        geometry_confidence=.95,association_iou=.95,keypoints=np.r_[quad,quad-[0,80]].tolist())
                    stream.write(json.dumps(observation)+'\n')
            result=calibrate([measured],'synthetic',folder/'calibration',profiles)
            self.assertTrue(result['all_regions_accepted'])
            self.assertFalse(result['known_speeds_used'])
            self.assertEqual(result['camera_id'],'synthetic')
            self.assertEqual(len(result['regions']['road']['candidate_comparison']),3)
            self.assertTrue((folder/'calibration/calibration.json').is_file())


if __name__=='__main__':
    unittest.main()
