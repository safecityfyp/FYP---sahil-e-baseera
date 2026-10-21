"""Auditable image-assisted 1-D ground calibration; no language model or speed labels.

The assistant supplies image observations in JSON. Numerical geometry stays here.
Assumptions: a fixed camera, a locally planar road, near-zero camera roll and a car
travelling parallel to the two marked road edges. This is NOT a full 2-D road map.
"""
from pathlib import Path
import hashlib
import json
import numpy as np


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def road_vanishing_point(segments):
    points = np.asarray(segments, dtype=float)
    if points.shape != (2, 2, 2) or not np.isfinite(points).all():
        raise ValueError('Supply two finite road-edge segments, each with two XY points')
    lines = np.cross(np.c_[points[:,0], np.ones(2)], np.c_[points[:,1], np.ones(2)])
    norms = np.linalg.norm(lines[:,:2],axis=1)
    if np.min(norms) < 30:
        raise ValueError('Road-edge segments must span at least 30 pixels')
    lines /= norms[:,None]
    vp = np.cross(lines[0],lines[1])
    if abs(vp[2]) < .05:
        raise ValueError('Road edges have a poorly conditioned intersection')
    return vp[:2]/vp[2]


def depth_coordinate(points, horizon_y):
    points=np.asarray(points,dtype=float)
    denominator=points[...,1]-horizon_y
    if not np.isfinite(points).all() or np.any(denominator <= 15):
        raise ValueError('Ground contact is too near or above the assumed road horizon')
    return 1/denominator


def mapping_values(annotation, method):
    if method not in ('local_affine', 'projective_single', 'projective_consensus'):
        raise ValueError('Unknown vision calibration method')
    vp=road_vanishing_point(annotation['road_edge_segments_px'])
    wheelbase=float(annotation['wheelbase_prior_m'])
    if not .8 < wheelbase < 6:
        raise ValueError('Wheelbase must be a positive metre prior, not overall car length')
    pairs=annotation['wheel_contacts']
    front=np.array([p['front_xy'] for p in pairs],float)
    rear=np.array([p['rear_xy'] for p in pairs],float)
    if method=='local_affine':
        separation=np.linalg.norm(front-rear,axis=1)
    else:
        separation=np.abs(depth_coordinate(front,vp[1])-depth_coordinate(rear,vp[1]))
    if np.any(separation <= 1e-9):
        raise ValueError('Coincident wheel contacts cannot set metric scale')
    scales=wheelbase/separation
    anchor=int(annotation['anchor_frame'])
    scale=float(np.median(scales) if method=='projective_consensus' else scales[anchor])
    spread=float(np.median(np.abs(scales-np.median(scales)))/np.median(scales))
    return vp,scale,scales,spread


def fit(annotation_file, output_file, method='projective_consensus'):
    path=Path(annotation_file)
    annotation=json.loads(path.read_text(encoding='utf-8'))
    if annotation.get('schema_version') != 1:
        raise ValueError('Unsupported annotation schema')
    # Reference labels are neither required nor accepted in the geometry interface.
    if any(k in annotation for k in ('reference_kmh','expected_speed','reference_speed','speed_kmh')):
        raise ValueError('Remove reference speed labels from calibration inputs')
    vp,scale,scales,spread=mapping_values(annotation,method)
    for i,info in enumerate(annotation['images']):
        image=path.parent/info['file']
        if digest(image) != info['sha256']:
            raise ValueError(f'Calibration image {i} changed')
    result=dict(schema_version=1,kind='vision_assisted_1d',case_id=annotation['case_id'],method=method,
                road_vanishing_point_px=vp.tolist(),assumed_horizon_y_px=float(vp[1]),
                scale_m_per_coordinate=scale,per_snapshot_scales=scales.tolist(),
                relative_scale_mad=spread,geometry_consistency_pass=spread<=.20,
                wheelbase_prior_m=annotation['wheelbase_prior_m'],
                annotation_sha256=digest(path),image_size=annotation['image_size'],
                known_speeds_used=False,accuracy_validated=False,
                assumptions=annotation['assumptions'],uncertainty=annotation['uncertainty'],
                scope='One local longitudinal path, fixed camera; not a full metric road homography.')
    output=Path(output_file)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return result


def slope_speed(times, positions):
    times=np.asarray(times,float)
    positions=np.asarray(positions,float)
    if len(times)<3 or not np.isfinite(times).all() or np.any(np.diff(times)<=0) or np.ptp(times)<.15:
        raise ValueError('At least three ordered timestamps spanning 0.15 seconds are needed')
    A=np.c_[np.ones(len(times)),times-times.mean()]
    weights=np.ones(len(times))
    for _ in range(4):
        coefficients=np.linalg.lstsq(A*weights[:,None]**.5,positions*weights**.5,rcond=None)[0]
        residual=positions-A@coefficients
        sigma=max(float(np.median(np.abs(residual)))*1.4826,.02)
        weights=np.minimum(1,1.5*sigma/np.maximum(np.abs(residual),1e-9))
    return dict(estimated_kmh=abs(float(coefficients[1]))*3.6,
                signed_m_per_s=float(coefficients[1]),fit_rms_m=float(np.sqrt(np.mean(residual**2))),
                observations=len(times),time_interval_s=[float(times[0]),float(times[-1])],
                fitted_position_m=(A@coefficients).tolist(),position_m=positions.tolist(),times_s=times.tolist())


def measure(annotation, calibration, timestamps):
    front=np.array([p['front_xy'] for p in annotation['wheel_contacts']],float)
    if calibration['method']=='local_affine':
        # Project onto the observed straight path; ignore perspective for the control.
        direction=front[-1]-front[0]
        direction/=np.linalg.norm(direction)
        coordinate=front@direction
    else:
        coordinate=depth_coordinate(front,calibration['assumed_horizon_y_px'])
    positions=(coordinate-coordinate[0])*calibration['scale_m_per_coordinate']
    return slope_speed(timestamps,positions)


def estimate(annotation_file, calibration_file, frames_file, output_file, draws=2000):
    annotation=json.loads(Path(annotation_file).read_text(encoding='utf-8'))
    calibration=json.loads(Path(calibration_file).read_text(encoding='utf-8'))
    frames=json.loads(Path(frames_file).read_text(encoding='utf-8'))
    if calibration.get('kind')!='vision_assisted_1d' or digest(annotation_file)!=calibration['annotation_sha256']:
        raise ValueError('Wrong mapping type or changed image observations; refit calibration')
    if not frames['case_id']==annotation['case_id']==calibration['case_id']:
        raise ValueError('Camera/clip identity mismatch')
    if [frames['width'],frames['height']]!=calibration['image_size']:
        raise ValueError('Image dimensions changed')
    if len(frames['frames']) != len(annotation['wheel_contacts']):
        raise ValueError('The image observations and timestamps differ')
    for measured,image in zip(frames['frames'],annotation['images']):
        if measured['frame_index']!=image['frame_index']:
            raise ValueError('Frame order changed')
    times=[r['time_s'] for r in frames['frames']]
    result=measure(annotation,calibration,times)
    # Conditional Monte Carlo sensitivity, not a calibrated confidence interval.
    rng=np.random.default_rng(20261021)
    uncertainty=annotation['uncertainty']
    samples=[]
    for _ in range(draws):
        perturbed=json.loads(json.dumps(annotation))
        perturbed['wheelbase_prior_m']*=rng.uniform(1-uncertainty['wheelbase_relative_half_range'],
                                                  1+uncertainty['wheelbase_relative_half_range'])
        perturbed['road_edge_segments_px']=(np.array(annotation['road_edge_segments_px'])+
                    rng.normal(0,uncertainty['road_point_sigma_px'],(2,2,2))).tolist()
        for p in perturbed['wheel_contacts']:
            for key in ('front_xy','rear_xy'):
                p[key]=(np.array(p[key])+rng.normal(0,uncertainty['wheel_point_sigma_px'],2)).tolist()
        try:
            vp,scale,_,_=mapping_values(perturbed,calibration['method'])
            changed={**calibration,'assumed_horizon_y_px':float(vp[1]),'scale_m_per_coordinate':scale}
            samples.append(measure(perturbed,changed,times)['estimated_kmh'])
        except ValueError:
            pass
    if len(samples)<draws*.8:
        sensitivity=None
    else:
        sensitivity=np.percentile(samples,[2.5,97.5]).tolist()
    result.update(schema_version=1,kind='vision_assisted_speed',case_id=annotation['case_id'],
                  method=calibration['method'],display_speed=f"{result['estimated_kmh']:.1f} km/h",
                  sensitivity_95_percentile_kmh=sensitivity,sensitivity_valid_draws=len(samples),
                  sensitivity_draws=draws,
                  uncertainty_note='Conditional image-point/dimension sensitivity; excludes cruise-reference error, '
                                   'camera motion, nonplanarity, lens bias and wrong vehicle identification.',
                  geometry_consistency_pass=calibration['geometry_consistency_pass'],
                  known_speeds_used=False,reference_speed_used=False,accuracy_validated=False,
                  calibration_sha256=digest(calibration_file),timestamps_sha256=digest(frames_file),
                  annotation_sha256=digest(annotation_file),
                  measurement='Assistant marked visible near-side front-tire ground contacts on five frames.')
    target=Path(output_file)
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return result
