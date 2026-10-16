"""Physical checks for shared camera fitting and metric trajectory prediction."""
import unittest
import numpy as np
from shared_camera_calibration import fit_shared_camera, predict_shared_camera


def synthetic_pass(mps, radial_lambda=0, noise=0, seed=17):
    t=np.linspace(0,1,90);dt=1/30;depth=50+mps*.4-mps*t
    def points(z):
        xy=np.c_[5000/z,370+14000/z-540]/1920
        if radial_lambda:
            ru=np.linalg.norm(xy,axis=1)
            ratio=(1-np.sqrt(1-4*radial_lambda*ru**2))/(2*radial_lambda*ru**2)
            xy*=ratio[:,None]
        return xy*1920+[960,540]
    p=points(depth);q=points(depth-mps*dt)
    if noise:
        rng=np.random.default_rng(seed);p+=rng.normal(0,noise,p.shape);q+=rng.normal(0,noise,q.shape)
    return {'track_id':1,'measurements':[{'time_s':float(time),'dt_s':dt,
             'anchor':a.tolist(),'transported_anchor':b.tolist(),'inliers':30,
             'flow_rms_pixels':.15} for time,a,b in zip(t,p,q)]}


class SharedCameraTests(unittest.TestCase):
    def setUp(self):
        self.flows={str(v):synthetic_pass(v) for v in [10,16,23,30]}
        self.speeds={str(v):v*3.6 for v in [10,16,23,30]}
        self.transforms={name:np.eye(3) for name in self.flows}

    def test_shared_trajectory_and_flow_predict_unseen_speed(self):
        for family in ['trajectory','flow']:
            with self.subTest(family=family):
                model=fit_shared_camera(self.flows,self.speeds,self.transforms,family)
                self.assertTrue(model['available'])
                self.assertAlmostEqual(model['horizon_y'],370,places=2)
                result=predict_shared_camera(synthetic_pass(22),model,np.eye(3))
                self.assertTrue(result['available'])
                self.assertAlmostEqual(result['estimated_kmh'],79.2,places=3)

    def test_radial_trajectory_recovers_unseen_motion(self):
        flows={str(v):synthetic_pass(v,.3) for v in [10,16,23,30]}
        model=fit_shared_camera(flows,self.speeds,self.transforms,'trajectory_radial')
        self.assertTrue(model['available'])
        result=predict_shared_camera(synthetic_pass(22,.3),model,np.eye(3))
        self.assertLess(abs(result['estimated_kmh']-79.2),.1)

    def test_no_reference_support_returns_unavailable(self):
        model=fit_shared_camera(self.flows,{'10':36},self.transforms)
        self.assertFalse(model['available'])
        model=fit_shared_camera(self.flows,self.speeds,self.transforms)
        query=synthetic_pass(22)
        for row in query['measurements']:
            row['anchor'][1]+=2000;row['transported_anchor'][1]+=2000
        self.assertFalse(predict_shared_camera(query,model,np.eye(3))['available'])

    def test_query_annotations_do_not_enter_prediction(self):
        model=fit_shared_camera(self.flows,self.speeds,self.transforms)
        query=synthetic_pass(22)
        original=predict_shared_camera(query,model,np.eye(3))['estimated_kmh']
        query['filename']='KiaSportage_999';query['reference_speed']=999
        self.assertEqual(predict_shared_camera(query,model,np.eye(3))['estimated_kmh'],original)
        self.assertNotIn('KiaSportage_999',model['reference_videos'])

    def test_outer_reference_is_removed_before_camera_fit(self):
        from kia_validation import candidate
        flows={**self.flows,'query':synthetic_pass(22)}
        cache={'query|'+name:{'accepted':True,'query_to_template':np.eye(3).tolist()} for name in flows}
        baseline={'available':True,'estimated_kmh':1}
        original=candidate('query','shared_trajectory',{},flows,
                           {**self.speeds,'query':79.2},{},{},cache,baseline)
        poisoned=candidate('query','shared_trajectory',{},flows,
                           {**self.speeds,'query':999},{},{},cache,baseline)
        self.assertAlmostEqual(original['estimated_kmh'],79.2,places=3)
        self.assertEqual(original['estimated_kmh'],poisoned['estimated_kmh'])
        self.assertNotIn('query',poisoned['reference_videos'])

    def test_geometry_ensemble_uses_other_reference_scales_only(self):
        from kia_validation import candidate
        names=['KiaSportage_31','KiaSportage_55','KiaSportage_77']
        labels={name:float(name.rsplit('_',1)[1]) for name in names}
        def prediction(value):return {'available':True,'estimated_kmh':value,'time_interval_s':[0,1],'track_id':1}
        raw={name:{'v3b_rigid_distortion':prediction(speed/1.2),'suv_rigid_radial':prediction(speed/1.4)}
             for name,speed in labels.items()}
        query='KiaSportage_44'
        raw[query]={'v3b_rigid_distortion':prediction(40),'suv_rigid_radial':prediction(35)}
        results=[]
        for poison in [44,999]:
            results.append(candidate(query,'geometry_ensemble_50',raw,{},
                                     {**labels,query:poison},{},{},{},{'available':True,'estimated_kmh':1}))
        self.assertAlmostEqual(results[0]['estimated_kmh'],48.5)
        self.assertEqual(results[0]['estimated_kmh'],results[1]['estimated_kmh'])
        self.assertEqual(set(results[0]['reference_videos']),set(labels))


if __name__=='__main__':unittest.main()
