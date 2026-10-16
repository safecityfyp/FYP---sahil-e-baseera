"""Local road-plane speeds for CCTV, including turning and accelerating cars.

Speeds are robust local polynomial derivatives of projected ground-footprint
centers. Each track is split at long gaps and region changes. No constant-speed
assumption or expected-speed correction is applied.
"""
import argparse
from collections import Counter,defaultdict
import csv
import gzip
import json
from pathlib import Path

import cv2
import numpy as np

from calibrate_speed import project,measures
from cctv_calibration import footprints,read_rows
from camera_cache import compare_views


def local_velocity(times,centers,at,window_s=2.4,minimum_span_s=1.0,quadratic_minimum_span_s=1.5):
    times=np.asarray(times,float);centers=np.asarray(centers,float)
    mask=abs(times-at)<=window_s/2+1e-6
    t=times[mask]-at;p=centers[mask]
    if len(t)<4 or np.ptp(t)<minimum_span_s-.001:return None
    degree=2 if len(t)>=5 and np.ptp(t)>=quadratic_minimum_span_s-.001 else 1
    design=np.stack([t**j for j in range(degree+1)],axis=1)
    initial=np.exp(-.5*(t/(window_s/2))**2)
    weights=initial.copy()
    coefficients=None
    for _ in range(4):
        root=np.sqrt(weights)
        coefficients=np.linalg.lstsq(design*root[:,None],p*root[:,None],rcond=None)[0]
        error=np.linalg.norm(design@coefficients-p,axis=1)
        weights=initial*np.minimum(1,.25/np.maximum(error,1e-9))
    residual=float(np.sqrt(np.average(np.sum((design@coefficients-p)**2,axis=1),weights=weights)))
    return dict(speed_kmh=float(np.linalg.norm(coefficients[1])*3.6),
                velocity_m_s=coefficients[1].tolist(),rms_m=residual,n=len(t),span_s=float(np.ptp(t)),
                polynomial_degree=degree)


def split_segments(records,max_gap_s=1.25):
    result=[];segment=[]
    for r in sorted(records,key=lambda r:r['time_s']):
        if segment and (r['time_s']-segment[-1]['time_s']>max_gap_s or r['region']!=segment[-1]['region']):
            result.append(segment);segment=[]
        segment.append(r)
    if segment:result.append(segment)
    return result


def view_checks(inputs,calibration):
    reference=cv2.imread(str(Path(inputs[0])/'reference.jpg'),0)
    assert reference is not None
    reference=cv2.resize(reference,(960,round(reference.shape[0]*960/reference.shape[1])))
    rows=[]
    for folder in inputs:
        for path in sorted(Path(folder).glob('view_*.jpg')):
            frame=cv2.imread(str(path),0)
            frame=cv2.resize(frame,(reference.shape[1],reference.shape[0]))
            comparison=compare_views(reference,frame)
            rows.append(dict(time_s=int(path.stem.rsplit('_',1)[1]),comparison=comparison))
    rows.sort(key=lambda r:r['time_s'])
    return rows


def calculate(inputs,calibration_file,output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    calibration=json.loads(Path(calibration_file).read_text())
    observations=[];inference=[]
    for folder in inputs:
        report=json.loads((Path(folder)/'inference_report.json').read_text());inference.append(report)
        assert report['camera_id']==calibration['camera_id'] and report['source_sha256']==calibration['source_sha256']
        observations.extend(read_rows(folder,'observations.jsonl.gz'))
    records,filters=footprints(observations,calibration['profile'],calibration['width'],calibration['height'],
                              moving_only=False,ground_indices=calibration['ground_order']['indices'])
    profile=calibration['profile']
    velocity_options=dict(window_s=profile.get('speed_window_s',2.4),minimum_span_s=profile.get('speed_minimum_span_s',1.0),
                          quadratic_minimum_span_s=profile.get('speed_quadratic_minimum_span_s',1.5))
    checks=view_checks(inputs,calibration)
    invalid_intervals=[(max(0,r['time_s']-300),r['time_s']+300) for r in checks if not r['comparison']['valid']]
    groups=defaultdict(list);counts=Counter();rows=[]
    for r in records:groups[r['track_id']].append(r)
    for tid,group in groups.items():
        for segment in split_segments(group):
            name=segment[0]['region'];mapping=calibration['regions'][name]
            if not mapping.get('accepted'):
                counts['unaccepted_region']+=len(segment);continue
            H=np.array(mapping['H_image_to_experimental_meters']);hull=np.array(mapping['support_hull_image'],np.float32)
            # Filtering can create gaps. Split again instead of fitting through missing support.
            supported=[]
            for r in segment:
                if any(lo<=r['time_s']<=hi for lo,hi in invalid_intervals):
                    counts['view_change']+=1;continue
                if not all(cv2.pointPolygonTest(hull,tuple(map(float,p)),True)>=-2 for p in r['quad']):
                    counts['outside_calibration_support']+=1;continue
                supported.append(r)
            for sub in split_segments(supported):
                if len(sub)<4:
                    counts['short_segment']+=len(sub);continue
                times=np.array([r['time_s'] for r in sub]);quads=np.array([r['quad'] for r in sub])
                world=project(quads,H);centers=world.mean(axis=1)
                angles,_,lengths,_=measures(world)
                angle_error=np.median(np.degrees(np.arcsin(np.clip(abs(angles),0,1))),axis=1)
                alternative_centers=[project(quads,np.array(a)).mean(axis=1) for a in mapping['alternative_mappings']]
                for i,r in enumerate(sub):
                    nominal=local_velocity(times,centers,times[i],**velocity_options)
                    if nominal is None:
                        counts['insufficient_local_window']+=1;continue
                    mask=abs(times-times[i])<=velocity_options['window_s']/2+1e-6
                    size_mad=float(1.4826*np.median(abs(lengths[mask]-np.median(lengths[mask])))/np.median(lengths[mask]))
                    reasons=[]
                    if nominal['rms_m']>.8:reasons.append('trajectory_residual')
                    if np.median(angle_error[mask])>25:reasons.append('quad_angle_error')
                    if size_mad>.25:reasons.append('unstable_footprint_length')
                    alternative=[local_velocity(times,p,times[i],**velocity_options) for p in alternative_centers]
                    values=[nominal['speed_kmh']]+[v['speed_kmh'] for v in alternative if v is not None]
                    low,high=min(values),max(values)
                    if (high-low)/max(nominal['speed_kmh'],2)>.85:reasons.append('excessive_mapping_sensitivity')
                    if reasons:
                        counts.update(reasons);continue
                    row=dict(camera_id=calibration['camera_id'],track_id=int(tid),region=name,
                             frame_index=r['frame_index'],time_s=r['time_s'],experimental_kmh=nominal['speed_kmh'],
                             sensitivity_low_kmh=low,sensitivity_high_kmh=high,
                             trajectory_rms_m=nominal['rms_m'],window_observations=nominal['n'],
                             window_span_s=nominal['span_s'],polynomial_degree=nominal['polynomial_degree'],
                             length_relative_mad=size_mad,ground_center_image=np.mean(r['quad'],axis=0).tolist(),
                             ground_center_world_m=centers[i].tolist(),quad=r['quad'])
                    rows.append(row);counts['accepted_speed_samples']+=1
    rows.sort(key=lambda r:(r['frame_index'],r['track_id']))
    with gzip.open(output/'speeds.jsonl.gz','wt',encoding='utf-8') as stream:
        for r in rows:stream.write(json.dumps(r,separators=(',',':'))+'\n')
    keys=['camera_id','track_id','region','frame_index','time_s','experimental_kmh','sensitivity_low_kmh',
          'sensitivity_high_kmh','trajectory_rms_m','window_observations','window_span_s','polynomial_degree','length_relative_mad']
    with (output/'speed_samples.csv').open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=keys);writer.writeheader()
        writer.writerows({k:r[k] for k in keys} for r in rows)
    track_summaries=[]
    by_id=defaultdict(list)
    for r in rows:by_id[r['track_id']].append(r)
    for tid,local in sorted(by_id.items()):
        speeds=np.array([r['experimental_kmh'] for r in local])
        track_summaries.append(dict(track_id=tid,start_s=local[0]['time_s'],end_s=local[-1]['time_s'],
                                    samples=len(local),median_experimental_kmh=float(np.median(speeds)),
                                    min_experimental_kmh=float(speeds.min()),max_experimental_kmh=float(speeds.max())))
    (output/'track_summary.json').write_text(json.dumps(track_summaries,indent=2)+'\n')
    report=dict(camera_id=calibration['camera_id'],source_sha256=calibration['source_sha256'],
                total_duration_s=max(r['stop_s'] for r in inference),inference_reports=inference,
                footprint_filters=filters,speed_counts=dict(counts),cars_with_speed_estimates=len(by_id),
                static_view_checks=checks,invalid_view_intervals_s=invalid_intervals,
                all_sampled_views_consistent=all(r['comparison']['valid'] for r in checks),
                method='Robust local polynomial derivative of 2D road-plane ground centroid',
                local_velocity_options=velocity_options,
                latency_note=f'Offline centered window uses future observations up to {velocity_options["window_s"]/2} seconds',
                display_note='Decimal experimental km/h; dimension and car-subset sensitivity range is secondary',
                motorcycle_bus_truck_policy='Tracked but no metric label: this checkpoint supplies car ground footprints only',
                accuracy_validated=False,known_speeds_used=False,
                count_note='Track IDs can fragment or restart at 900s; counts are tracks, not guaranteed unique vehicles')
    (output/'speed_report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('Speed complete:',calibration['camera_id'],'car tracks',len(by_id),'samples',len(rows),dict(counts),flush=True)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--inputs',nargs='+',required=True)
    p.add_argument('--calibration',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();calculate(a.inputs,a.calibration,a.output)
