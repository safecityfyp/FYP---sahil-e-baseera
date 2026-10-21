"""Physical and input-integrity checks for assistant-supplied image observations."""
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from vision_calibration import fit,estimate,digest,road_vanishing_point,slope_speed


class VisionCalibrationTests(unittest.TestCase):
    def scene(self,folder):
        # Pinhole road with horizon y=300, inverse depth y=300+1000/Z.
        # Car approaches at exactly 10 m/s; its wheelbase is 3 metres.
        times=np.array([0,.1,.2,.3,.4])
        depths=16-10*times
        contacts=[]
        images=[]
        for i,z in enumerate(depths):
            front=[500+100/z,300+1000/z]
            rear=[500+100/(z+3),300+1000/(z+3)]
            contacts.append(dict(front_xy=front,rear_xy=rear))
            image=folder/f'image_{i}.jpg'
            image.write_bytes(b'synthetic-image-binding-'+str(i).encode())
            images.append(dict(file=image.name,frame_index=i,sha256=digest(image)))
        annotation=dict(schema_version=1,case_id='SYNTHETIC',image_size=[1920,1080],
            road_edge_segments_px=[[[400,400],[300,500]],[[600,400],[700,500]]],
            wheelbase_prior_m=3.,anchor_frame=2,wheel_contacts=contacts,images=images,
            assumptions=['Synthetic exact planar zero-roll pinhole scene.'],
            uncertainty=dict(wheel_point_sigma_px=0,road_point_sigma_px=0,wheelbase_relative_half_range=0))
        a=folder/'annotation.json';a.write_text(json.dumps(annotation))
        frames=dict(case_id='SYNTHETIC',width=1920,height=1080,
                    frames=[dict(frame_index=i,time_s=float(t)) for i,t in enumerate(times)])
        f=folder/'frames.json';f.write_text(json.dumps(frames))
        return a,f

    def test_exact_projective_recovery_of_36_kmh(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);a,f=self.scene(folder)
            for method in ['projective_single','projective_consensus']:
                mapping=folder/'calibration.json'
                fit(a,mapping,method)
                result=estimate(a,mapping,f,folder/'speed.json',draws=20)
                self.assertAlmostEqual(result['estimated_kmh'],36,places=8)

    def test_changed_image_refuses_calibration(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);a,_=self.scene(folder)
            (folder/'image_2.jpg').write_bytes(b'changed view')
            with self.assertRaisesRegex(ValueError,'image 2 changed'):
                fit(a,folder/'calibration.json')

    def test_changed_points_refuse_saved_calibration(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);a,f=self.scene(folder);mapping=folder/'calibration.json'
            fit(a,mapping)
            annotation=json.loads(a.read_text());annotation['wheelbase_prior_m']=4
            a.write_text(json.dumps(annotation))
            with self.assertRaisesRegex(ValueError,'changed image observations'):
                estimate(a,mapping,f,folder/'speed.json',draws=20)

    def test_label_is_rejected_by_calibration(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);a,_=self.scene(folder)
            annotation=json.loads(a.read_text());annotation['reference_kmh']=36
            a.write_text(json.dumps(annotation))
            with self.assertRaisesRegex(ValueError,'Remove reference speed'):
                fit(a,folder/'calibration.json')

    def test_frame_identity_mismatch_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);a,f=self.scene(folder);mapping=folder/'calibration.json'
            fit(a,mapping)
            frames=json.loads(f.read_text());frames['frames'][2]['frame_index']=999
            f.write_text(json.dumps(frames))
            with self.assertRaisesRegex(ValueError,'Frame order changed'):
                estimate(a,mapping,f,folder/'speed.json',draws=20)

    def test_duplicate_times_and_parallel_edges_refused(self):
        with self.assertRaises(ValueError):
            slope_speed([0,0,.3],[0,1,2])
        with self.assertRaises(ValueError):
            road_vanishing_point([[[0,0],[100,0]],[[0,10],[100,10]]])


if __name__=='__main__':
    unittest.main()
