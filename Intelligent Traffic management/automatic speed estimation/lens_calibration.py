"""Division-model radial self-calibration from one rigid translation's optical flow.

Uses a standard division lens model and an independently implemented robust
epipole fit. It is not Fitzgibbon's two-view quadratic-eigenvalue algorithm.
"""
import numpy as np
from scipy.optimize import least_squares
from calibration_candidates import select_rows,shared_vp_delay
from refine_flow import flow_vanishing_point


def undistort_division(points,coefficient,center,scale):
    p=(np.asarray(points)-center)/scale
    return p/(1+coefficient*np.sum(p*p,axis=-1,keepdims=True))*scale+center


def distort_division(points,coefficient,center,scale):
    p=(np.asarray(points)-center)/scale;r2=np.sum(p*p,axis=-1,keepdims=True)
    return p*2/(1+np.sqrt(np.maximum(1-4*coefficient*r2,1e-8)))*scale+center


def fit_motion_lens(features,width,height):
    source=[];dest=[]
    for row in features.get('measurements',[]):
        p=np.asarray(row.get('matched_points_image',[]));q=np.asarray(row.get('matched_next_points_image',[]))
        if len(p):
            selected=np.unique(np.linspace(0,len(p)-1,min(30,len(p))).astype(int))
            source.extend(p[selected]);dest.extend(q[selected])
    if len(source)<100:return {'available':False,'reason':'insufficient_visual_correspondences'}
    center=np.array([width/2,height/2]);scale=max(width,height)
    a=(np.asarray(source)-center)/scale;b=(np.asarray(dest)-center)/scale
    weights=np.clip(np.linalg.norm(b-a,axis=1)*scale,1,20)
    initial_vp=(np.asarray(flow_vanishing_point(features)['point'])-center)/scale
    def convert(p,k):return p/np.maximum(1+k*np.sum(p*p,axis=1,keepdims=True),.1)
    def residual(parameters):
        vp=parameters[:2];k=parameters[2];p=convert(a,k);q=convert(b,k)
        ray=p-vp;motion=q-p
        cross=ray[:,0]*motion[:,1]-ray[:,1]*motion[:,0]
        sine=cross/(np.linalg.norm(ray,axis=1)*np.linalg.norm(motion,axis=1)+1e-12)
        den=np.r_[1+k*np.sum(a*a,axis=1),1+k*np.sum(b*b,axis=1)]
        return np.r_[sine*weights,np.maximum(.25-den,0)*20,parameters[2]*.01]
    fits=[]
    for k in [-1,0,1]:
        fit=least_squares(residual,np.r_[initial_vp,k],bounds=([-2,-2,-2],[2,2,2]),
                          loss='soft_l1',f_scale=.25,max_nfev=300)
        score=float(np.mean(np.minimum(residual(fit.x)**2,1)));fits.append((score,fit))
    score,fit=min(fits,key=lambda x:x[0]);k=float(fit.x[2])
    singular=np.linalg.svd(fit.jac,compute_uv=False)
    condition=float(singular[0]/max(singular[-1],1e-12))
    available=abs(k)<1.98 and condition<1e5
    return {'available':bool(available),'division_coefficient':k,'center':center.tolist(),'scale':scale,
        'vanishing_point_undistorted':(fit.x[:2]*scale+center).tolist(),
        'correspondences':len(a),'robust_normal_flow_score':score,'jacobian_condition':condition,
        'reason':'estimated_from_visual_motion' if available else 'distortion_fit_at_bound_or_ill_conditioned',
        'reference_label_used':False}


def distortion_aware_delay(observations,report,features):
    lens=fit_motion_lens(features,report['width'],report['height'])
    if not lens['available']:return {'available':False,'reason':lens['reason'],'lens_calibration':lens}
    corrected=[]
    for row in observations:
        points=np.asarray(row['keypoints']).copy()
        points[:,:2]=undistort_division(points[:,:2],lens['division_coefficient'],lens['center'],lens['scale'])
        corrected.append({**row,'keypoints':points.tolist()})
    result=shared_vp_delay(select_rows(corrected,report),vanishing_point=lens['vanishing_point_undistorted'],vp_weight=20)
    result.update(method='distortion_aware_flow_vp_temporal_calibration',lens_calibration=lens)
    for key in ['fitted_front_image','fitted_rear_image']:
        if key in result:
            result[key]=distort_division(result[key],lens['division_coefficient'],lens['center'],lens['scale']).tolist()
    return result
