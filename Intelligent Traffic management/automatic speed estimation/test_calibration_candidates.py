"""Known-geometry and outlier checks for the calibration comparison."""
import unittest
import cv2
import numpy as np
from calibration_candidates import temporal_delay_2d,rigid_cuboid_bundle,vp_rigid_bundle
from flow_calibration import estimate_flow
from calibrate_speed import project
from lens_calibration import fit_motion_lens,distort_division
from longitudinal_calibration import fit_longitudinal_reference,predict_longitudinal
from calibration_comparison import select_fold,PILOTS


class CandidateTests(unittest.TestCase):
    def test_temporal_delay_recovers_metric_speed_under_perspective(self):
        camera=np.array([[1000,960,0],[0,540,1200],[0,1,0]],float)
        rows=[]
        for t in np.linspace(0,2,40):
            y=12+4*t
            q=np.array([[1-.9,y-2.45],[1-.9,y+2.45],[1+.9,y+2.45],[1+.9,y-2.45]])
            rows.append({'quad':project(q,camera).tolist(),'time_s':float(t),'track_id':1})
        result=temporal_delay_2d(rows)
        self.assertTrue(result['available'])
        self.assertAlmostEqual(result['estimated_kmh'],14.4,delta=.1)

    def test_rigid_bundle_recovers_constant_speed_from_known_3d_projection(self):
        L,W,H=4.9,1.87,1.45
        base=np.array([[-W/2,0,0],[-W/2,0,L],[W/2,0,L],[W/2,0,0]])
        points=np.r_[base,base+[0,-H,0]]
        R=cv2.Rodrigues(np.array([.05,.3,.01]))[0];observations=[]
        for index,t in enumerate(np.linspace(0,1,32)):
            XYZ=points@R.T+np.array([1,1.2,15])-(t-.5)*12*R[:,2]
            xy=XYZ[:,:2]/XYZ[:,2:]*1400+[960,540]
            box=np.r_[xy.min(axis=0),xy.max(axis=0)].tolist()
            observations.append({'track_id':1,'time_s':float(t),'frame_index':index,
                'baseline_box':box,'keypoints':xy.tolist(),'geometry_confidence':.9,'association_iou':.9})
        report={'width':1920,'height':1080,'ground_indices':[0,1,2,3]}
        result=rigid_cuboid_bundle(observations,report)
        self.assertTrue(result['available'])
        self.assertAlmostEqual(result['estimated_kmh'],43.2,delta=.5)
        renamed=rigid_cuboid_bundle(observations,{**report,'source_video':'MercedesAMG550_999.MP4'})
        self.assertAlmostEqual(renamed['estimated_kmh'],result['estimated_kmh'],places=6)
        direction=R[:,2];vp=direction[:2]/direction[2]*1400+[960,540]
        constrained=vp_rigid_bundle(observations,report,vp)
        self.assertAlmostEqual(constrained['estimated_kmh'],43.2,delta=.5)

    def test_flow_uses_actual_time_and_rejects_large_motion_outliers(self):
        mapping=np.diag([.02,.02,1]);measurements=[]
        for i in range(40):
            dt=1/29.97;anchor=np.array([300+i*3,600+i])
            velocity=np.array([10.,0.])
            if i%7==0:velocity*=8
            transported=anchor+velocity/.02*dt
            measurements.append({'time_s':i*dt,'dt_s':dt,'anchor':anchor.tolist(),
                                  'transported_anchor':transported.tolist()})
        result=estimate_flow({'track_id':1,'measurements':measurements},mapping)
        self.assertTrue(result['available'])
        self.assertAlmostEqual(result['estimated_kmh'],36,places=6)
        self.assertLess(result['observations'],len(measurements))

    def test_reference_road_calibration_predicts_a_different_speed(self):
        def make_flow(speed):
            rows=[];vp=np.array([960.,540.])
            for index,t in enumerate(np.linspace(0,1,40)):
                dt=1/29.97;z=12+speed*t
                point=vp+np.array([1000.,1200.])/z
                after=vp+np.array([1000.,1200.])/(z+speed*dt)
                scale=z/(z+speed*dt);A=np.c_[np.eye(2)*scale,(1-scale)*vp]
                rows.append({'time_s':float(t),'dt_s':dt,'anchor':point.tolist(),
                    'transported_anchor':after.tolist(),'affine':A.tolist(),'crop_origin':[0,0],'inliers':20})
            return {'track_id':1,'measurements':rows}
        calibration=fit_longitudinal_reference(make_flow(10),36)
        prediction=predict_longitudinal(make_flow(20),calibration,np.eye(3))
        self.assertTrue(prediction['available'])
        self.assertAlmostEqual(prediction['estimated_kmh'],72,delta=.1)

    def test_motion_lens_fit_recovers_known_radial_distortion_without_speed_labels(self):
        rng=np.random.default_rng(12);vp=np.array([-.25,.01]);rows=[]
        for i in range(20):
            a=rng.uniform([-.1,.03],[.4,.24],size=(30,2));b=vp+(a-vp)*(1.03+i*.001)
            p=distort_division(a,.3,[0,0],1)*1920+[960,540]
            q=distort_division(b,.3,[0,0],1)*1920+[960,540]
            A=np.c_[np.eye(2)*1.03,-.03*(vp*1920+[960,540])]
            rows.append({'matched_points_image':p.tolist(),'matched_next_points_image':q.tolist(),
                         'affine':A.tolist(),'crop_origin':[0,0],'inliers':30})
        result=fit_motion_lens({'measurements':rows},1920,1080)
        self.assertTrue(result['available'])
        self.assertAlmostEqual(result['division_coefficient'],.3,delta=.02)

    def test_outer_test_label_cannot_change_calibration_or_method_selection(self):
        names=PILOTS+['anonymous_test'];labels=dict(zip(names,[30.,60.,100.,80.]))
        raw={name:{'v2d_flow_vp_delay':{'available':True,'estimated_kmh':value/1.1}}
             for name,value in labels.items()}
        options={name:[{'reference':other,'score':10,'prediction':{'estimated_kmh':labels[name]},
                        'registration':{}} for other in names if other!=name] for name in names}
        first=select_fold('anonymous_test',raw,labels,options)
        second=select_fold('anonymous_test',raw,{**labels,'anonymous_test':999},options)
        self.assertEqual(first['estimated_kmh'],second['estimated_kmh'])
        self.assertEqual(first['selection'],second['selection'])
        self.assertNotIn('anonymous_test',first['reference_videos'])


if __name__=='__main__':unittest.main(verbosity=2)
