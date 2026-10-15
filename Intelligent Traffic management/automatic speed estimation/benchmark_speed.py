"""Label-independent single-pass estimators; reference speeds are used only by evaluation/tuning."""
from collections import defaultdict
from pathlib import Path
import json
import math

import cv2
import numpy as np
from scipy.optimize import least_squares
import calibrate_speed as geometry


def target_records(observations, report, min_height=0, max_height=10000, corner_order='checkpoint'):
    prepared=geometry.prepare(observations,report['ground_indices'],report['width'],report['height'],corner_order)
    boxes={(r['track_id'],r['frame_index']):r['baseline_box'] for r in observations}
    groups=defaultdict(list)
    for row in prepared:
        box=boxes[row['track_id'],row['frame_index']]
        if min_height<=box[3]-box[1]<=max_height:groups[row['track_id']].append(row)
    if not groups:return []
    # The moving pass with the largest observed footprint is the target, independent of speed labels.
    target=max(groups.values(),key=lambda rows:max(abs(cv2.contourArea(np.array(r['quad'],np.float32))) for r in rows))
    return sorted(target,key=lambda r:r['time_s'])


def estimate_single_pass(observations, report, config):
    rows=target_records(observations,report,config.get('min_height',0),config.get('max_height',10000),config.get('corner_order','checkpoint'))
    if len(rows)<8 or rows[-1]['time_s']-rows[0]['time_s']<.25:
        return {'available':False,'reason':'insufficient_unclipped_ground_geometry','observations':len(rows)}
    length=config.get('length_m',4.5);width=config.get('width_m',1.8)
    H,diagnostics=geometry.fit_mapping(rows,report['width'],report['height'],length,width,
                                      legacy_normalization=config.get('legacy_normalization',False))
    calculated=geometry.estimate_track(rows,H)
    result={'available':True,'raw_kmh':calculated['experimental_kmh'],
            'estimated_kmh':calculated['experimental_kmh']*config.get('scale',1),
            'time_interval_s':[rows[0]['time_s'],rows[-1]['time_s']],
            'observations':len(rows),'track_id':rows[0]['track_id'],
            'mapping':H.tolist(),'diagnostics':diagnostics,'motion_diagnostics':calculated,
            'support_hull_image':cv2.convexHull(np.array([r['quad'] for r in rows],np.float32).reshape(-1,2)).reshape(-1,2).tolist(),
            'method':'single_pass_rectangle_calibration','reference_speed_used':False}
    if config.get('method')=='projective_delay':
        delay=projective_delay(rows,length)
        if not delay['available']:return delay
        result.update(delay)
        result['estimated_kmh']=result['raw_kmh']*config.get('scale',1)
    result['calibration_length_m']=length
    result['scale_correction']=config.get('scale',1)
    return result


def projective_delay(rows,length_m):
    """Match front/rear ground positions through a shared 1-D projective motion curve.

    For constant speed, the rear follows the front's path after a delay L/v.
    Fitting this delay estimates speed without reading a reference speed or clip filename.
    """
    quads=np.array([r['quad'] for r in rows]);centers=quads.mean(axis=1)
    direction=centers[-1]-centers[0];direction/=np.linalg.norm(direction)
    front=(quads[:,1]+quads[:,2])/2;rear=(quads[:,0]+quads[:,3])/2
    if np.median((front-rear)@direction)<0:front,rear=rear,front
    front=front@direction;rear=rear@direction
    times=np.array([r['time_s'] for r in rows]);span=times[-1]-times[0]
    t=(times-times[0])/span
    origin=np.mean(np.r_[front,rear]);normalizer=max(np.ptp(np.r_[front,rear]),1)
    front=(front-origin)/normalizer;rear=(rear-origin)/normalizer
    linear=np.polyfit(t,front,1)

    def residual(parameters):
        a,b,c,log_delay=parameters;delay=np.exp(log_delay)
        def prediction(s):
            den=1+c*s
            return (a+b*s)/np.maximum(den,.02),np.maximum(.03-den,0)*10
        f,fp=prediction(t);r,rp=prediction(t-delay)
        return np.r_[f-front,r-rear,fp,rp]
    fits=[]
    for c in [-.8,-.4,0,.5,1.5]:
        initial=[linear[1],linear[0],c,math.log(.25/span)]
        fit=least_squares(residual,initial,bounds=([-5,-20,-.95,math.log(.03/span)],
                                                 [5,20,4,math.log(4/span)]),loss='soft_l1',f_scale=.02,max_nfev=500)
        fits.append((np.mean(residual(fit.x)**2),fit))
    error,fit=min(fits,key=lambda pair:pair[0]);delay_s=float(np.exp(fit.x[3])*span)
    return {'available':True,'raw_kmh':length_m/delay_s*3.6,'method':'projective_delay',
            'projective_delay_s':delay_s,'projective_fit_rms_pixels':float(np.sqrt(error)*normalizer),
            'projective_parameters':fit.x.tolist()}


def load_clip(directory):
    directory=Path(directory)
    observations=json.loads((directory/'observations.json').read_text())
    report=json.loads((directory/'geometry_run_report.json').read_text())
    # Recompute corner-order voting from observations, including early pilot outputs.
    points=np.array([r['keypoints'] for r in observations])
    if len(points):
        vote=points[:,:4,1].mean(axis=1)>points[:,4:,1].mean(axis=1)
        report['ground_indices']=list(range(4)) if vote.mean()>=.5 else list(range(4,8))
        report['ground_order_vote_agreement']=float(max(vote.mean(),1-vote.mean()))
    return observations,report
