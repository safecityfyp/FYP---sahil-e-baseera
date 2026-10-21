"""Camera-specific multi-car calibration with explicit geometric stability checks.

Selects an affine or projective road map by held-out car geometry, then tests
subsets of independent tracks. These checks measure consistency, not speed
accuracy. A generic passenger-car dimension prior supplies the metric scale.
"""
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
from scipy.optimize import least_squares

from .geometry import fit_mapping, measures, project, sample_balanced,compose


def read_rows(folder, name):
    with gzip.open(Path(folder)/name, 'rt', encoding='utf-8') as stream:
        return [json.loads(line) for line in stream if line.strip()]


def region_for(point, profile, width, height):
    for name, polygon in profile['regions'].items():
        contour = (np.asarray(polygon)*[width,height]).astype(np.float32)
        if cv2.pointPolygonTest(contour, tuple(map(float, point)), False) >= 0:
            return name
    return None


def motion_qualified(group, minimum_observations=6, minimum_span_s=1.5):
    if len(group) < minimum_observations:
        return False
    times=np.array([r['time_s'] for r in group])
    centers=np.array([np.asarray(r['quad']).mean(axis=0) for r in group])
    extent=float(np.max(np.linalg.norm(centers-np.median(centers,axis=0),axis=1))*2)
    return bool(times.max()-times.min() >= minimum_span_s-.001 and extent >= 60)


def ground_order(observations):
    """The pinned checkpoint predates the current model card's corner convention.

    Its output is eight XY points, with ground corners 0:4 in these recordings.
    Select the lower projected face using one aggregate vote per moving track.
    Preserve edge topology within the selected face.
    """
    votes=defaultdict(list)
    for r in observations:
        p=np.asarray(r['keypoints'],float)
        if p.ndim==2 and p.shape[0]==8 and p.shape[1]>=2:
            votes[r['track_id']].append(bool(p[:4,1].mean()>p[4:,1].mean()))
    if not votes:return dict(indices=[],agreement=0.0,tracks=0)
    fraction=float(np.mean([np.mean(v)>=.5 for v in votes.values()]))
    return dict(indices=list(range(4)) if fraction>=.5 else list(range(4,8)),
                agreement=max(fraction,1-fraction),tracks=len(votes),
                method='Lower projected face, one aggregate vote per moving track; checkpoint edge topology retained')


def footprints(observations, profile, width, height, moving_only=True, ground_indices=None):
    if ground_indices is None:ground_indices=ground_order(observations)['indices']
    if len(ground_indices)!=4:return [],dict(no_ground_face=len(observations))
    groups=defaultdict(list); counts=Counter()
    for r in observations:
        p=np.asarray(r['keypoints'],float)[ground_indices]
        if p.shape[0]!=4 or p.shape[1] not in [2,3] or not np.isfinite(p).all():
            counts['nonfinite_or_wrong_shape']+=1;continue
        if (p.shape[1]==3 and p[:,2].min()<.30) or r['geometry_confidence']<.25 or r['association_iou']<.40:
            counts['low_confidence']+=1;continue
        quad=p[:,:2]; edges=np.linalg.norm(np.roll(quad,-1,axis=0)-quad,axis=1)
        if not cv2.isContourConvex(quad.astype(np.float32)) or abs(cv2.contourArea(quad.astype(np.float32)))<250 or edges.min()<7:
            counts['degenerate_quad']+=1;continue
        if quad[:,0].min()<4 or quad[:,0].max()>width-4 or quad[:,1].min()<4 or quad[:,1].max()>height-4:
            counts['clipped']+=1;continue
        region=region_for(quad.mean(axis=0),profile,width,height)
        if not region:
            counts['outside_road']+=1;continue
        row=dict(track_id=int(r['track_id']),time_s=r['time_s'],frame_index=r['frame_index'],
                 region=region,quad=quad.tolist(),confidence=float(p[:,2].min()) if p.shape[1]==3 else None)
        groups[(region,int(r['track_id']))].append(row)
    accepted=[]
    for group in groups.values():
        group.sort(key=lambda r:r['time_s'])
        if moving_only and not motion_qualified(group,profile.get('calibration_minimum_observations',6),
                                                 profile.get('calibration_minimum_span_s',1.5)):
            counts['stationary_or_short_track_observations']+=len(group);continue
        accepted.extend(group)
    counts['accepted_observations']=len(accepted)
    counts['accepted_tracks']=len(set(r['track_id'] for r in accepted))
    return accepted,dict(counts)


def fit_affine(records,width,height,length_m=4.5,width_m=1.8):
    quads=np.array([r['quad'] for r in records]);ids=np.array([r['track_id'] for r in records])
    groups=[np.flatnonzero(ids==i) for i in np.unique(ids)]
    center=np.median(quads.reshape(-1,2),axis=0)
    normalizer=np.array([[2/width,0,-2*center[0]/width],[0,2/width,-2*center[1]/width],[0,0,1]])
    weights=np.array([1/np.sqrt(np.sum(ids==i)) for i in ids]);weights/=weights.mean()
    def compose(theta):
        return np.array([[np.exp(theta[0]),theta[1],0],[0,1,0],[0,0,1]])@normalizer
    def residual(theta):
        angles,parallel,lengths,widths=measures(project(quads,compose(theta)))
        return (np.c_[angles,parallel*.5,np.log((lengths/widths)/(length_m/width_m))*.65]*weights[:,None]).ravel()
    result=least_squares(residual,[-1,0],bounds=([-7,-30],[7,30]),loss='soft_l1',f_scale=.12,max_nfev=500)
    H=compose(result.x)
    lengths=measures(project(quads,H))[2]
    scale=length_m/np.median([np.median(lengths[g]) for g in groups])
    H=np.diag([scale,scale,1])@H
    singular=np.linalg.svd(result.jac,compute_uv=False)
    return H,dict(optimizer_success=bool(result.success),parameter_condition_number=float(singular[0]/max(singular[-1],1e-12)))


def fit_metric_projective(records,width,height):
    """Robust fleet-size prior also constrains perspective scale with road depth.

    The original angle/rigidity fit fixes only the overall median length, which
    can leave large position-dependent size errors. This version adds soft
    length and width priors across independent cars. Unknown true car dimensions
    remain a source of systematic error.
    """
    quads=np.array([r['quad'] for r in records]);ids=np.array([r['track_id'] for r in records])
    unique=np.unique(ids);groups=[np.flatnonzero(ids==i) for i in unique]
    center=np.median(quads.reshape(-1,2),axis=0)
    normalizer=np.array([[2/width,0,-2*center[0]/width],[0,2/width,-2*center[1]/width],[0,0,1]])
    _,initial=fit_mapping(records,width,height,fast=True)
    theta=np.array(initial['theta']);H=compose(theta,normalizer)
    lengths=measures(project(quads,H))[2]
    scale=4.5/np.median([np.median(lengths[g]) for g in groups])
    weights=np.array([1/np.sqrt(np.sum(ids==i)) for i in ids]);weights/=weights.mean()
    def mapping(v):return np.diag([np.exp(v[4]),np.exp(v[4]),1])@compose(v[:4],normalizer)
    def residual(v):
        H=mapping(v);world=project(quads,H)
        angles,parallel,lengths,widths=measures(world)
        rigidity=np.zeros(len(records))
        for group in groups:rigidity[group]=np.log(lengths[group]/np.median(lengths[group]))
        geometric=np.c_[angles,parallel*.5,np.log((lengths/widths)/2.5)*.65,rigidity*.5,
                         np.log(lengths/4.5)*.40,np.log(widths/1.8)*.40]*weights[:,None]
        den=(np.c_[quads.reshape(-1,2),np.ones(len(quads)*4)]@H.T)[:,2]
        return np.r_[geometric.ravel(),np.maximum(0,.08-den)*15]
    result=least_squares(residual,np.r_[theta,np.log(scale)],bounds=([-100,-100,-7,-30,-12],[100,100,7,30,12]),
                         loss='soft_l1',f_scale=.12,max_nfev=500)
    singular=np.linalg.svd(result.jac,compute_uv=False)
    return mapping(result.x),dict(optimizer_success=bool(result.success),
                                 parameter_condition_number=float(singular[0]/max(singular[-1],1e-12)),
                                 soft_dimension_prior_m=dict(length=4.5,width=1.8),prior_weight=.40)


def fit_method(method,records,width,height,fast=False):
    if method=='affine':return fit_affine(records,width,height)
    if method=='projective_metric':return fit_metric_projective(records,width,height)
    return fit_mapping(records,width,height,fast=fast)


def geometry_quality(records,H):
    if not records:
        return dict(angle_error_deg=None,shape_log_error=None,length_relative_mad=None,score=1e6)
    groups=defaultdict(list)
    for r in records:groups[r['track_id']].append(r)
    angles=[];shapes=[];rigidity=[];metric_error=[]
    for group in groups.values():
        a,_,lengths,widths=measures(project(np.array([r['quad'] for r in group]),H))
        angles.append(float(np.median(np.degrees(np.arcsin(np.clip(abs(a),0,1))))))
        shapes.append(float(np.median(abs(np.log((lengths/widths)/2.5)))))
        rigidity.append(float(1.4826*np.median(abs(lengths-np.median(lengths)))/np.median(lengths)))
        metric_error.append(float(np.median(abs(np.log(lengths/4.5))+abs(np.log(widths/1.8)))/2))
    angle,shape,rigid=map(lambda x:float(np.median(x)),[angles,shapes,rigidity])
    metric=float(np.median(metric_error))
    return dict(angle_error_deg=angle,shape_log_error=shape,length_relative_mad=rigid,
                typical_car_dimension_log_error=metric,score=angle+10*shape+20*rigid+10*metric)


def scale_change(H,alternative,records):
    """Compare local metric magnification; arbitrary map rotations do not matter."""
    centers=np.array([np.mean(r['quad'],axis=0) for r in records])
    ratios=[]
    for delta in [[3,0],[0,3]]:
        a=np.linalg.norm(project(centers+delta,H)-project(centers,H),axis=1)
        b=np.linalg.norm(project(centers+delta,alternative)-project(centers,alternative),axis=1)
        ratios.extend((abs(b/np.maximum(a,1e-9)-1)).tolist())
    return float(np.median(ratios)),float(np.quantile(ratios,.90))


def fit_region(records,width,height,minimum=6):
    ids=sorted(set(r['track_id'] for r in records))
    if len(ids)<minimum:
        return dict(accepted=False,reason=f'Only {len(ids)} independent moving car tracks; need {minimum}',track_ids=ids)
    held=ids[::4];fit_ids=[i for i in ids if i not in held]
    fitting=sample_balanced([r for r in records if r['track_id'] in fit_ids],maximum=10)
    testing=sample_balanced([r for r in records if r['track_id'] in held],maximum=10)
    candidates=[]
    for method in ['affine','projective','projective_metric']:
        H,diag=fit_method(method,fitting,width,height)
        fit_quality=geometry_quality(fitting,H);held_quality=geometry_quality(testing,H)
        candidates.append(dict(method=method,H=H,diagnostics=diag,fit_quality=fit_quality,held_quality=held_quality,
                               score=held_quality['score']+.1*fit_quality['score']))
    selected=min(candidates,key=lambda r:r['score'])
    method=selected['method']
    # Refit selected geometry on all qualifying calibration cars after model selection.
    fitting=sample_balanced(records,maximum=10)
    H,diag=fit_method(method,fitting,width,height)
    alternatives=[];rng=np.random.default_rng(20261009)
    subset_changes=[]
    for _ in range(6):
        chosen=set(rng.choice(ids,size=max(4,int(np.ceil(len(ids)*.75))),replace=False).tolist())
        subset=[r for r in fitting if r['track_id'] in chosen]
        alt,_=fit_method(method,subset,width,height,fast=True)
        alternatives.append(alt);subset_changes.append(scale_change(H,alt,fitting)[0])
    hull=cv2.convexHull(np.array([r['quad'] for r in records],np.float32).reshape(-1,2)).reshape(-1,2)
    den=np.c_[hull,np.ones(len(hull))]@H[2]
    finite_plane=bool(np.isfinite(H).all() and not (den.min()<=0<=den.max()))
    quality=geometry_quality(fitting,H)
    held_quality=selected['held_quality']
    bootstrap=float(np.quantile(subset_changes,.90))
    reasons=[]
    if not finite_plane:reasons.append('Projective pole intersects calibration support')
    if quality['angle_error_deg']>20 or held_quality['angle_error_deg']>25:reasons.append('Rectangle consistency is poor')
    if held_quality['length_relative_mad']>.30:reasons.append('Held-out footprint scale changes along tracks')
    if bootstrap>.35:reasons.append('Metric mapping changes by more than 35% between car subsets')
    if diag['parameter_condition_number']>1e5:reasons.append('Ill-conditioned geometric fit')
    # Scale uncertainty is explicit. This is a sensitivity envelope, not a confidence interval.
    alternatives.extend([np.diag([factor,factor,1])@H for factor in [.80,1.20]])
    candidate_report=[{k:v for k,v in r.items() if k!='H'} for r in candidates]
    return dict(accepted=not reasons,reason='; '.join(reasons) if reasons else 'Passed internal geometry and subset-stability checks',
                method=method,track_ids=ids,observations=len(records),held_out_track_ids=held,
                candidate_comparison=candidate_report,quality=quality,selected_held_quality=held_quality,
                subset_scale_changes=subset_changes,subset_scale_change_p90=bootstrap,
                H_image_to_experimental_meters=H.tolist(),alternative_mappings=[a.tolist() for a in alternatives],
                support_hull_image=hull.tolist(),diagnostics=diag,
                dimension_prior_m=dict(length=4.5,width=1.8),
                interpretation='Experimental metric scale from unknown passenger-car dimensions; accuracy unvalidated')


def calibrate(inputs,camera,output,profiles=None):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    config_path=Path(profiles) if profiles else Path(__file__).resolve().parents[1]/'configs'/'cameras.json'
    config=json.loads(config_path.read_text());profile=config['cameras'][camera]
    observations=[];reports=[]
    for folder in inputs:
        report=json.loads((Path(folder)/'inference_report.json').read_text());reports.append(report)
        assert report['source_sha256']==profile['sha256'] and report['camera_id']==camera
        observations.extend(read_rows(folder,'observations.jsonl.gz'))
    width,height=reports[0]['width'],reports[0]['height']
    order=ground_order([r for r in observations if r['time_s']<max(config['calibration_windows_s'])])
    assert order['agreement']>=.8,'Inconsistent projected ground-face ordering'
    regions={};windows=[];previous={}
    for end_s in config['calibration_windows_s']:
        if end_s>max(r['stop_s'] for r in reports):continue
        records,filters=footprints([r for r in observations if r['time_s']<end_s],profile,width,height,ground_indices=order['indices'])
        window=dict(end_s=end_s,filters=filters,regions={})
        for name in profile['regions']:
            if name in regions:continue
            local=[r for r in records if r['region']==name]
            result=fit_region(local,width,height,config['minimum_cars_per_region'])
            result['calibration_end_s']=end_s
            if result.get('accepted'):
                stability=None
                if name in previous and previous[name].get('accepted'):
                    stability=scale_change(np.array(previous[name]['H_image_to_experimental_meters']),
                                           np.array(result['H_image_to_experimental_meters']),sample_balanced(local))[0]
                result['scale_change_from_previous_window']=stability
                preferred=len(result['track_ids'])>=config['preferred_cars_per_region'] and result['subset_scale_change_p90']<=.20
                stable=stability is not None and stability<=.15 and result['subset_scale_change_p90']<=.25
                if preferred or stable or end_s==config['calibration_windows_s'][-1]:
                    result['selection_reason']='Enough independent cars and stable subsets' if preferred else 'Stable across calibration windows' if stable else 'Longest configured window; passed minimum consistency checks'
                    regions[name]=result
            previous[name]=result
            window['regions'][name]=result
            print(camera,name,end_s,'cars',len(result['track_ids']),'accepted',result.get('accepted'),result.get('reason'),flush=True)
        windows.append(window)
        if len(regions)==len(profile['regions']):break
    for name in profile['regions']:
        if name not in regions:
            regions[name]=previous.get(name,dict(accepted=False,reason='No calibration observations',track_ids=[]))
    chosen_end=max([r.get('calibration_end_s',0) for r in regions.values()]+[300])
    records,filters=footprints([r for r in observations if r['time_s']<chosen_end],profile,width,height,ground_indices=order['indices'])
    with gzip.open(output/'calibration_footprints.jsonl.gz','wt',encoding='utf-8') as stream:
        for r in records:stream.write(json.dumps(r,separators=(',',':'))+'\n')
    report=dict(schema_version=2,camera_id=camera,source_video=profile['video'],source_sha256=profile['sha256'],
                width=width,height=height,fps=reports[0]['fps'],profile=profile,
                profile_sha256=hashlib.sha256(config_path.read_bytes()).hexdigest(),
                regions=regions,window_comparison=windows,calibration_duration_s=chosen_end,
                ground_order=order,keypoint_confidence_available=bool(observations and len(observations[0]['keypoints'][0])==3),
                all_regions_accepted=all(r.get('accepted') for r in regions.values()),
                known_speeds_used=False,accuracy_validated=False,benchmark_vehicle_scales_used=False,
                cache_policy='Camera-specific mapping; profile, source hash and pipeline version must match. Reuse requires a consistent static view.',
                dimension_sensitivity='Uniform scale 0.8 to 1.2, plus independent-car subset variation; not a statistical confidence interval',
                source_sha256_by_file={name:hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest()
                                      for name in ['calibration.py','geometry.py']})
    (output/'calibration.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('Calibration complete:',camera,'seconds',chosen_end,'all regions accepted',report['all_regions_accepted'],flush=True)
    return report
