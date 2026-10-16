"""Experimental local road rectification from learned cuboids and explicit car-size priors.

Independent implementation of rectangle/aspect/rigidity fitting, inspired by
Sochor et al. (2017) and the UrbanOmniDetect (2026) ground-footprint approach.
Ranges are sensitivity envelopes, not confidence intervals or accuracy claims.
"""
from pathlib import Path
from collections import defaultdict
import csv
import json
import math
import os
import cv2
import numpy as np
from scipy.optimize import least_squares

ROOT = Path(os.environ.get('FYP_SPEED_ROOT',str(Path(__file__).resolve().parent)))
downloaded_geometry = ROOT / 'outputs' / 'geometry'
default_geometry = downloaded_geometry if downloaded_geometry.exists() else ROOT / 'output' / 'inputs' / 'geometry'
GEOMETRY = Path(os.environ.get('FYP_GEOMETRY_DIR', str(default_geometry)))
OUT = Path(os.environ.get('FYP_SPEED_OUTPUT',str(ROOT / 'outputs' / 'speed_experiment')))
LENGTH_M, WIDTH_M = 4.5, 1.8
DIMENSION_SCENARIOS = [(4.5,1.8),(3.2,1.45),(3.2,2.0),(5.2,1.45),(5.2,2.0)]


def project(points, H):
    p = np.asarray(points, dtype=float)
    flat = p.reshape(-1,2)
    result = np.c_[flat,np.ones(len(flat))] @ H.T
    denominator = result[:,2]
    safe = np.where(np.abs(denominator)<1e-8, np.where(denominator>=0,1e-8,-1e-8),denominator)
    return (result[:,:2]/safe[:,None]).reshape(p.shape)


def compose(theta, normalizer):
    p,q,a,b = theta
    return np.array([[np.exp(a),b,0],[0,1,0],[p,q,1]]) @ normalizer


def measures(quads):
    edges = np.roll(quads,-1,axis=1)-quads
    sizes = np.linalg.norm(edges,axis=2)+1e-9
    unit = edges/sizes[:,:,None]
    cosines = np.sum(unit*np.roll(unit,-1,axis=1),axis=2)
    opposite = unit[:,:2,0]*unit[:,2:,1]-unit[:,:2,1]*unit[:,2:,0]
    lengths=(sizes[:,0]+sizes[:,2])/2
    widths=(sizes[:,1]+sizes[:,3])/2
    return cosines,opposite,lengths,widths


def fit_mapping(records, width, height, length_m=LENGTH_M, width_m=WIDTH_M, fast=False, legacy_normalization=False):
    quads=np.array([r['quad'] for r in records],dtype=float)
    ids=np.array([r['track_id'] for r in records])
    unique=np.unique(ids)
    center=np.median(quads.reshape(-1,2),axis=0)
    normalizer=np.array([[2/width,0,-2*center[0]/width],[0,2/width,-2*center[1]/width],[0,0,1]])
    if legacy_normalization:
        normalizer=np.array([[2/width,0,-1],[0,2/width,-height/width],[0,0,1]])
    weights=np.array([1/math.sqrt(np.sum(ids==i)) for i in ids])
    weights/=np.mean(weights)
    groups=[np.flatnonzero(ids==i) for i in unique]

    def residual(theta):
        H=compose(theta,normalizer)
        world=project(quads,H)
        angles,parallel,lengths,widths=measures(world)
        rigidity=np.zeros(len(records))
        for group in groups:
            rigidity[group]=np.log(lengths[group]/np.median(lengths[group]))
        shape=np.log((lengths/widths)/(length_m/width_m))
        geometric=np.c_[angles,parallel*0.5,shape*0.65,rigidity*0.5]*weights[:,None]
        den=(np.c_[quads.reshape(-1,2),np.ones(len(quads)*4)]@H.T)[:,2]
        pole=np.maximum(0,0.08-den)*15
        return np.r_[geometric.ravel(),pole]

    q_starts=([0,1,2] if not fast else [1,2]) if legacy_normalization else ([0,2,5,10,20] if not fast else [2,10])
    aspect_starts=([0,0.7] if not fast else [0]) if legacy_normalization else ([-3,0] if not fast else [-2])
    starts=[(0,q,a,0) for q in q_starts for a in aspect_starts]
    fits=[]
    for theta in starts:
        bound=4 if legacy_normalization else 100
        shape_bound=2.5 if legacy_normalization else 7
        shear_bound=4 if legacy_normalization else 30
        result=least_squares(residual,theta,bounds=([-bound,-bound,-shape_bound,-shear_bound],[bound,bound,shape_bound,shear_bound]),
                             loss='soft_l1',f_scale=0.12,max_nfev=500)
        fits.append((float(np.mean(residual(result.x)**2)),result))
    _,result=min(fits,key=lambda item:item[0])
    H=compose(result.x,normalizer)
    world=project(quads,H)
    _,_,lengths,_=measures(world)
    # Give each track one vote; correlated video frames do not count as independent cars.
    scale=length_m/np.median([np.median(lengths[g]) for g in groups])
    H=np.diag([scale,scale,1])@H
    world=project(quads,H)
    directions=world[:,1]-world[:,0]
    directions/=np.linalg.norm(directions,axis=1)[:,None]
    directions[directions[:,1]<0]*=-1
    direction=np.median(directions,axis=0)
    angle=math.pi/2-math.atan2(direction[1],direction[0])
    rotation=np.array([[math.cos(angle),-math.sin(angle),0],[math.sin(angle),math.cos(angle),0],[0,0,1]])
    H=rotation@H
    center=np.median(project(quads,H).mean(axis=1),axis=0)
    H=np.array([[1,0,-center[0]],[0,1,-center[1]],[0,0,1]])@H
    H/=np.linalg.norm(H[2,:2]) if np.linalg.norm(H[2,:2])>0 else H[2,2]
    angle_error,_,lengths,widths=measures(project(quads,H))
    singular=np.linalg.svd(result.jac,compute_uv=False)
    diagnostics={'fit_track_ids':[int(i) for i in unique],'fit_observations':len(records),
       'median_angle_error_deg':float(np.median(np.degrees(np.arcsin(np.clip(np.abs(angle_error),0,1))))),
       'median_length_m':float(np.median(lengths)),'median_width_m':float(np.median(widths)),
       'parameter_condition_number':float(singular[0]/max(singular[-1],1e-12)),
       'optimizer_success':bool(result.success),'theta':result.x.tolist(),
       'dimension_prior_length_m':length_m,'dimension_prior_width_m':width_m}
    return H,diagnostics


def prepare(observations, indices, width, height, longitudinal_order='checkpoint'):
    by_id=defaultdict(list)
    for r in observations:by_id[r['track_id']].append(r)
    records=[]
    for tid,group in by_id.items():
        group.sort(key=lambda r:r['time_s'])
        centers=np.array([[(r['baseline_box'][0]+r['baseline_box'][2])/2,
                           (r['baseline_box'][1]+r['baseline_box'][3])/2] for r in group])
        if len(group)<8 or np.linalg.norm(centers[-1]-centers[0])<80:continue
        side='left' if np.median(centers[:,0])<width/2 else 'right'
        for j,r in enumerate(group):
            p=np.array(r['keypoints'])[indices]
            if p.shape[1]>2 and np.min(p[:,2])<0.30:continue
            if r['geometry_confidence']<0.25 or r['association_iou']<0.40:continue
            quad=p[:,:2]
            if not np.isfinite(quad).all():continue
            if longitudinal_order=='motion':
                quad=quad[np.argsort(np.arctan2(*(quad-quad.mean(axis=0))[:,::-1].T))]
            if not cv2.isContourConvex(quad.astype(np.float32)):continue
            if abs(cv2.contourArea(quad.astype(np.float32)))<300:continue
            if np.min(np.linalg.norm(np.roll(quad,-1,axis=0)-quad,axis=1))<8:continue
            cx,cy=quad.mean(axis=0)
            if not (0.20*height<cy<0.82*height and 0.02*width<cx<0.98*width):continue
            if np.min(quad[:,0])<4 or np.max(quad[:,0])>width-4 or np.max(quad[:,1])>height-4:continue
            if longitudinal_order=='motion':
                lo=max(0,j-3);hi=min(len(group)-1,j+3)
                motion=centers[hi]-centers[lo]
                if np.linalg.norm(motion)<5:continue
                edge=np.roll(quad,-1,axis=0)-quad
                alignment=np.abs(edge@motion)/(np.linalg.norm(edge,axis=1)*np.linalg.norm(motion)+1e-9)
                scores=[np.mean(alignment[[0,2]]),np.mean(alignment[[1,3]])]
                if abs(scores[0]-scores[1])<0.08:continue
                if scores[1]>scores[0]:quad=np.roll(quad,-1,axis=0)
            elif longitudinal_order!='checkpoint':
                raise ValueError('Unknown longitudinal corner-order method.')
            records.append({'track_id':int(tid),'time_s':r['time_s'],'frame_index':r['frame_index'],
                            'side':side,'quad':quad.tolist()})
    return records


def estimate_track(records,H):
    times=np.array([r['time_s'] for r in records],dtype=float)
    quads=np.array([r['quad'] for r in records],dtype=float)
    world=project(quads,H)
    centers=world.mean(axis=1)
    t=times-times.mean()
    initial=np.r_[np.polyfit(t,centers[:,0],1),np.polyfit(t,centers[:,1],1)]
    def residual(p):return np.r_[(p[0]*t+p[1]-centers[:,0]),(p[2]*t+p[3]-centers[:,1])]
    fitted=least_squares(residual,initial,loss='soft_l1',f_scale=0.4)
    speed=float(np.hypot(fitted.x[0],fitted.x[2])*3.6)
    rms=float(np.sqrt(np.mean(residual(fitted.x)**2)))
    angles,_,lengths,widths=measures(world)
    length_cv=float(1.4826*np.median(np.abs(lengths-np.median(lengths)))/np.median(lengths))
    angle_error=float(np.median(np.degrees(np.arcsin(np.clip(np.abs(angles),0,1)))))
    midpoint=(times[0]+times[-1])/2
    half_speeds=[]
    for mask in [times<=midpoint,times>midpoint]:
        if mask.sum()>=4:
            velocity=np.array([np.polyfit(times[mask]-times[mask].mean(),centers[mask,k],1)[0] for k in [0,1]])
            half_speeds.append(float(np.linalg.norm(velocity)*3.6))
    drift=abs(half_speeds[0]-half_speeds[1])/max(speed,1) if len(half_speeds)==2 else None
    return {'experimental_kmh':speed,'trajectory_fit_rms_m':rms,'length_relative_mad':length_cv,
            'angle_error_deg':angle_error,'half_span_speed_relative_difference':drift,
            'median_inferred_length_m':float(np.median(lengths)),'median_inferred_width_m':float(np.median(widths))}


def sample_balanced(records, maximum=10):
    groups=defaultdict(list)
    for r in records:groups[r['track_id']].append(r)
    return [group[i] for group in groups.values() for i in np.unique(np.linspace(0,len(group)-1,min(len(group),maximum)).astype(int))]


def fit_road_mappings(records, report):
    width,height=report['width'],report['height']
    calibration={}
    for side in ['left','right']:
        local=[r for r in records if r['side']==side]
        ids=sorted(set(r['track_id'] for r in local))
        if len(ids)<3:
            calibration[side]={'accepted':False,'reason':'Fewer than three qualifying car tracks','track_ids':ids}
            continue
        # Deterministic holdout by track identity; held-out predicted boxes are consistency evidence only.
        held_ids=ids[::3]
        fit_ids=[i for i in ids if i not in held_ids]
        if len(fit_ids)<3:fit_ids=ids;held_ids=[]
        fitting=sample_balanced([r for r in local if r['track_id'] in fit_ids])
        H,diagnostics=fit_mapping(fitting,width,height)
        alternatives=[]
        for length_m,width_m in DIMENSION_SCENARIOS[1:]:
            alternative,_=fit_mapping(fitting,width,height,length_m,width_m,fast=True)
            alternatives.append(alternative)
        rng=np.random.default_rng(42)
        for _ in range(10):
            selected=set(rng.choice(fit_ids,size=max(3,round(len(fit_ids)*0.75)),replace=False).tolist())
            subset=[r for r in fitting if r['track_id'] in selected]
            alternative,_=fit_mapping(subset,width,height,fast=True)
            alternatives.append(alternative)
        held=[r for r in local if r['track_id'] in held_ids]
        held_angle=None
        if held:
            angles,_,_,_=measures(project(np.array([r['quad'] for r in held]),H))
            held_angle=float(np.median(np.degrees(np.arcsin(np.clip(np.abs(angles),0,1)))))
        accepted=diagnostics['median_angle_error_deg']<20 and (held_angle is None or held_angle<25)
        accepted=accepted and report['ground_order_vote_agreement']>=0.8 and diagnostics['parameter_condition_number']<1e5
        diagnostics.update({'accepted':bool(accepted),'held_out_track_ids':held_ids,
          'held_out_median_angle_error_deg':held_angle,'H_image_to_experimental_meters':H.tolist(),
          'alternative_mappings':[a.tolist() for a in alternatives],
          'interpretation':'Approximate local plane and dimension-prior mapping; no measured accuracy.'})
        calibration[side]=diagnostics
        diagnostics['support_hull_image'] = cv2.convexHull(
            np.array([r['quad'] for r in local], dtype=np.float32).reshape(-1, 2)).reshape(-1, 2).tolist()
    return calibration


def calculate_speed_rows(records, calibration):
    speed_rows=[]
    for side in ['left','right']:
        diagnostics=calibration.get(side,{})
        if not diagnostics.get('accepted'):
            continue
        H=np.array(diagnostics['H_image_to_experimental_meters'])
        alternatives=[np.array(a) for a in diagnostics['alternative_mappings']]
        hull=np.array(diagnostics['support_hull_image'], dtype=np.float32)
        # Restrict reuse to the road region supported by the calibration footprints.
        local=[r for r in records if r['side']==side and all(
            cv2.pointPolygonTest(hull, (float(p[0]),float(p[1])), True)>=-0.01 for p in r['quad'])]
        ids=sorted(set(r['track_id'] for r in local))
        for tid in ids:
            group=sorted([r for r in local if r['track_id']==tid],key=lambda r:r['time_s'])
            if len(group)<8 or group[-1]['time_s']-group[0]['time_s']<1.2:continue
            nominal=estimate_track(group,H)
            values=[nominal['experimental_kmh']]+[estimate_track(group,a)['experimental_kmh'] for a in alternatives]
            low,high=float(min(values)),float(max(values))
            sensitivity=(high-low)/max(nominal['experimental_kmh'],1)
            reasons=[]
            if nominal['length_relative_mad']>0.25:reasons.append('predicted_size_inconsistent')
            if nominal['trajectory_fit_rms_m']>0.8:reasons.append('trajectory_not_consistent_with_local_plane')
            if nominal['angle_error_deg']>25:reasons.append('footprint_not_rectangular_after_mapping')
            if nominal['half_span_speed_relative_difference'] is not None and nominal['half_span_speed_relative_difference']>0.35:reasons.append('speed_changes_or_geometry_drift_across_span')
            if sensitivity>0.8:reasons.append('high_calibration_sensitivity')
            speed_rows.append({'track_id':tid,'side':side,'time_start_s':group[0]['time_s'],
              'time_end_s':group[-1]['time_s'],'geometry_observations':len(group),
              'quality_passed':not bool(reasons),'quality_reasons':';'.join(reasons),
              'dimension_and_fit_sensitivity_low_kmh':low,'dimension_and_fit_sensitivity_high_kmh':high,
              **nominal})
    return speed_rows


def run(calibration=None, geometry_dir=None, output_dir=None, calibration_reused=None):
    geometry_dir=Path(geometry_dir) if geometry_dir is not None else GEOMETRY
    output_dir=Path(output_dir) if output_dir is not None else OUT
    output_dir.mkdir(parents=True,exist_ok=True)
    report=json.loads((geometry_dir/'geometry_run_report.json').read_text())
    observations=json.loads((geometry_dir/'observations.json').read_text())
    records=prepare(observations,report['ground_indices'],report['width'],report['height'])
    reused=(calibration is not None) if calibration_reused is None else calibration_reused
    if calibration is None:
        calibration=fit_road_mappings(records, report)
    before_support_filter=len(records)
    records=[r for r in records if calibration.get(r['side'],{}).get('accepted') and all(
        cv2.pointPolygonTest(np.array(calibration[r['side']]['support_hull_image'],dtype=np.float32),
                             (float(p[0]),float(p[1])),True)>=-0.01 for p in r['quad'])]
    speed_rows=calculate_speed_rows(records, calibration)
    (output_dir/'filtered_ground_footprints.json').write_text(json.dumps(records),encoding='utf-8')
    (output_dir/'calibration.json').write_text(json.dumps(calibration,indent=2),encoding='utf-8')
    fields=['track_id','side','time_start_s','time_end_s','geometry_observations',
            'quality_passed','quality_reasons','dimension_and_fit_sensitivity_low_kmh',
            'dimension_and_fit_sensitivity_high_kmh','experimental_kmh','trajectory_fit_rms_m',
            'length_relative_mad','angle_error_deg','half_span_speed_relative_difference',
            'median_inferred_length_m','median_inferred_width_m']
    for name, rows in [('experimental_speeds.csv',speed_rows),
                       ('qualified_experimental_speeds.csv',[r for r in speed_rows if r['quality_passed']])]:
        with (output_dir/name).open('w',newline='',encoding='utf-8') as f:
            writer=csv.DictWriter(f,fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    api_results=[{'track_id':r['track_id'],'carriageway':r['side'],
      'time_interval_s':[r['time_start_s'],r['time_end_s']],
      'experimental_kmh':r['experimental_kmh'],
      'estimated_kmh':r['experimental_kmh'],
      'sensitivity_range_kmh':[r['dimension_and_fit_sensitivity_low_kmh'],r['dimension_and_fit_sensitivity_high_kmh']],
      'range_type':'dimension_and_calibration_sensitivity','accuracy_validated':False,
      'method':'learned_3d_ground_footprints_with_assumed_vehicle_dimensions'}
      for r in speed_rows if r['quality_passed']]
    (output_dir/'vehicle_speed_estimates.json').write_text(json.dumps(api_results,indent=2),encoding='utf-8')
    result={'calibration_reused':reused,'source_geometry_observations':len(observations),'filtered_ground_footprints':len(records),
      'footprints_outside_usable_calibration':before_support_filter-len(records),
      'geometry_model_filename':report['model_filename'],'geometry_model_sha256':report['model_sha256'],
      'ground_corner_indices':report['ground_indices'],
      'experimental_track_estimates':len(speed_rows),'quality_passed_track_estimates':sum(r['quality_passed'] for r in speed_rows),
      'nominal_car_length_m':LENGTH_M,'nominal_car_width_m':WIDTH_M,'dimension_scenarios_m':DIMENSION_SCENARIOS,
      'range_type':'Dimension-prior and track-subset sensitivity envelope. Not a statistical confidence interval.',
      'scope':'Local visible road regions on each carriageway; passenger-car hypotheses only.',
      'accuracy_validated':False,'speed_units':'km/h under assumed vehicle dimensions',
      'limitations':['No independent speed or road-distance ground truth.',
        'Ground corners are model predictions; hidden corners can be wrong.',
        'A local planar road and approximately constant speed over each fitted span are assumed.',
        'Dimension priors are explicit analyst assumptions, not recognized make/model dimensions.',
        'Sensitivity range does not bound unmodelled errors such as lens distortion or road grade.']}
    (output_dir/'speed_run_report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))
    for r in speed_rows:print(r['track_id'],r['side'],round(r['experimental_kmh'],1),r['quality_passed'],r['quality_reasons'])
    return calibration,speed_rows,records


if __name__=='__main__':run()
