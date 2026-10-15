"""Reference-assisted road calibration and verified transfer between overlapping road views."""
from pathlib import Path
from types import SimpleNamespace
import cv2
import numpy as np
from scipy.optimize import least_squares,linprog

import calibrate_speed as geo
from benchmark_speed import target_records


def fit_motion(world,times):
    t=times-times.mean()
    initial=np.r_[np.polyfit(t,world[:,0],1),np.polyfit(t,world[:,1],1)]
    def residual(p):return np.r_[p[0]*t+p[1]-world[:,0],p[2]*t+p[3]-world[:,1]]
    # Use the same constant-velocity least-squares estimator for fitting and
    # evaluation. Switching estimators after calibration changes its scale.
    return SimpleNamespace(x=initial),residual(initial)


def refine_metric_scale(estimates,references):
    """Choose one physical distance-scale multiplier that minimizes worst pilot error."""
    estimates=np.asarray(estimates,dtype=float);references=np.asarray(references,dtype=float)
    A=np.vstack([np.c_[estimates,-np.ones(len(estimates))],np.c_[-estimates,-np.ones(len(estimates))]])
    b=np.r_[references,-references]
    result=linprog([0,1],A_ub=A,b_ub=b,bounds=[(.1,10),(0,None)],method='highs')
    if not result.success:raise ValueError('Pilot metric-scale refinement failed.')
    return float(result.x[0]),float(result.x[1])


def register_road(reference,current):
    """Find the ground-plane transform using foreground road texture, not speed labels."""
    reference=cv2.resize(reference,(960,540));current=cv2.resize(current,(960,540))
    if reference.ndim==3:reference=cv2.cvtColor(reference,cv2.COLOR_BGR2GRAY)
    if current.ndim==3:current=cv2.cvtColor(current,cv2.COLOR_BGR2GRAY)
    mask=np.zeros((540,960),np.uint8);mask[324:,240:941]=255
    detector=cv2.SIFT_create(nfeatures=8000,contrastThreshold=.01)
    kr,dr=detector.detectAndCompute(reference,mask);kc,dc=detector.detectAndCompute(current,mask)
    if dr is None or dc is None:return None,{'accepted':False,'reason':'no_road_features'}
    pairs=cv2.BFMatcher().knnMatch(dc,dr,k=2)
    matches=[a for pair in pairs if len(pair)==2 for a,b in [pair] if a.distance<.7*b.distance]
    if len(matches)<12:return None,{'accepted':False,'reason':'insufficient_road_matches','matches':len(matches)}
    source=np.float32([kc[m.queryIdx].pt for m in matches]);dest=np.float32([kr[m.trainIdx].pt for m in matches])
    H,inliers=cv2.findHomography(source,dest,cv2.RANSAC,2)
    if H is None or inliers is None:return None,{'accepted':False,'reason':'road_alignment_failed'}
    selected=inliers.ravel().astype(bool);count=int(selected.sum())
    coverage=min(abs(cv2.contourArea(cv2.convexHull(p[selected])))/(960*540) for p in [source,dest]) if count>=3 else 0
    predicted=geo.project(source[selected],H)
    rms=float(np.sqrt(np.mean(np.sum((predicted-dest[selected])**2,axis=1))))
    accepted=count>=12 and count/len(matches)>=.5 and coverage>=.015 and rms<=2
    evidence={'accepted':bool(accepted),'matches':len(matches),'inliers':count,'road_coverage':coverage,
              'alignment_rms_pixels_at_960':rms,'reason':'verified_road_overlap' if accepted else 'uncertain_road_alignment'}
    scale=np.diag([.5,.5,1])
    return (np.linalg.inv(scale)@H@scale if accepted else None),evidence


def trajectory_points(observations,report):
    rows=target_records(observations,report,80,500)
    if len(rows)<8:return None,None,rows
    quads=np.array([r['quad'] for r in rows])
    # Nearest face's ground midpoint avoids averaging unreliable hidden rear corners.
    points=(quads[:,0]+quads[:,3])/2
    times=np.array([r['time_s'] for r in rows])
    return points,times,rows


def fit_reference_mapping(clips):
    """Fit one local projective metric mapping using designated pilot speeds only.

    Each item has aligned points, times, quads and an explicitly supplied pilot reference.
    Results on these same pilots are fitting diagnostics, not independent accuracy evidence.
    """
    records=[row for clip in clips for row in clip['rows']]
    quads=np.array([r['quad'] for r in records]);center=np.median(quads.reshape(-1,2),axis=0)
    N=np.array([[2/1920,0,-2*center[0]/1920],[0,2/1920,-2*center[1]/1920],[0,0,1]])
    _,initial=geo.fit_mapping(records,1920,1080,4.9,1.87)

    def mapping(parameters):
        scale=np.exp(parameters[4])
        return np.diag([scale,scale,1])@geo.compose(parameters[:4],N)

    def residual(parameters):
        H=mapping(parameters);out=[]
        for clip in clips:
            world=geo.project(clip['points'],H);t=clip['times']-clip['times'].mean()
            motion,_=fit_motion(world,clip['times'])
            velocity=motion.x[[0,2]]
            prediction=world.mean(axis=0)+t[:,None]*velocity
            target=clip['reference_kmh']/3.6
            out.extend(((world-prediction)/max(target,1)*3).ravel())
            out.append((np.linalg.norm(velocity)-target)*50)
        angles,parallel,lengths,widths=geo.measures(geo.project(quads,H))
        # Predicted cuboids are approximate. Keep their shape as a weak regularizer.
        out.extend((angles*.1).ravel())
        out.extend((parallel*.1).ravel())
        den=(np.c_[quads.reshape(-1,2),np.ones(len(quads)*4)]@H.T)[:,2]
        out.extend(np.maximum(.03-den,0)*10)
        return np.array(out)

    fits=[]
    for scale in [1,3,10,30]:
        parameters=initial['theta']+[np.log(scale)]
        fit=least_squares(residual,parameters,bounds=([-100,-100,-7,-30,-5],[100,100,7,30,10]),
                          loss='soft_l1',f_scale=.1,max_nfev=1000)
        fits.append((float(np.mean(residual(fit.x)**2)),fit))
    error,fit=min(fits,key=lambda item:item[0]);H=mapping(fit.x)
    raw=[]
    for clip in clips:
        motion,_=fit_motion(geo.project(clip['points'],H),clip['times'])
        raw.append(float(np.hypot(motion.x[0],motion.x[2])*3.6))
    scale,max_error=refine_metric_scale(raw,[c['reference_kmh'] for c in clips])
    H=np.diag([scale,scale,1])@H
    support=cv2.convexHull(np.concatenate([c['points'] for c in clips]).astype(np.float32)).reshape(-1,2)
    return {'H_image_to_meters':H.tolist(),'support_hull_image':support.tolist(),
            'fit_rms':float(np.sqrt(error)),'parameters':fit.x.tolist(),
            'reference_videos':[c['video'] for c in clips],
            'reference_speeds_kmh':[c['reference_kmh'] for c in clips],
            'metric_scale_refinement':{'multiplier':scale,'objective':'minimum worst absolute pilot speed error',
                                       'maximum_pilot_error_kmh':max_error,'unrefined_pilot_estimates_kmh':raw},
            'method':'reference_assisted_local_projective_calibration',
            'physical_accuracy_verified':False,'scope':'Registered road region; this vehicle and recording setup.'}


def estimate_reference_speed(points,times,mapping):
    world=geo.project(points,np.array(mapping['H_image_to_meters']))
    fit,residual=fit_motion(world,times)
    return {'estimated_kmh':float(np.hypot(fit.x[0],fit.x[2])*3.6),
            'trajectory_rms_m':float(np.sqrt(np.mean(residual**2))),
            'time_interval_s':[float(times[0]),float(times[-1])],
            'estimator_reads_reference_label':False}
