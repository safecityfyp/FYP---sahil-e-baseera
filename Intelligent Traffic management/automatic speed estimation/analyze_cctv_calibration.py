"""Speed-blind temporal and independent-car-count diagnostics for CCTV calibration."""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from cctv_calibration import read_rows,footprints,geometry_quality,fit_method,scale_change,sample_balanced


def analyze(pilot,calibration_file,output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    calibration=json.loads(Path(calibration_file).read_text())
    observations=read_rows(pilot,'observations.jsonl.gz')
    records,filters=footprints(observations,calibration['profile'],calibration['width'],calibration['height'],
                              ground_indices=calibration['ground_order']['indices'])
    report=dict(camera_id=calibration['camera_id'],interpretation='Unlabelled geometry consistency, not measured speed accuracy',regions={})
    fig,ax=plt.subplots(figsize=(8,4.5),layout='constrained')
    for name,mapping in calibration['regions'].items():
        if not mapping.get('accepted'):continue
        hull=np.array(mapping['support_hull_image'],np.float32);H=np.array(mapping['H_image_to_experimental_meters'])
        later=[r for r in records if r['region']==name and r['time_s']>=mapping['calibration_end_s']
               and r['track_id'] not in mapping['track_ids'] and all(cv2.pointPolygonTest(hull,tuple(map(float,p)),True)>=-2 for p in r['quad'])]
        fitting=sample_balanced([r for r in records if r['region']==name and r['time_s']<mapping['calibration_end_s'] and r['track_id'] in mapping['track_ids']])
        ids=sorted(mapping['track_ids'],key=lambda tid:min(r['time_s'] for r in fitting if r['track_id']==tid))
        curve=[]
        for count in sorted(set([6,8,12,len(ids)])):
            if count>len(ids):continue
            subset=[r for r in fitting if r['track_id'] in ids[:count]]
            alternative,diagnostics=fit_method(mapping['method'],subset,calibration['width'],calibration['height'],fast=False)
            change=scale_change(H,alternative,fitting)
            curve.append(dict(independent_cars=count,median_local_scale_difference_from_selected=change[0],
                              p90_local_scale_difference_from_selected=change[1],later_geometry_quality=geometry_quality(later,alternative)))
        report['regions'][name]=dict(calibration_end_s=mapping['calibration_end_s'],selected_method=mapping['method'],
                                    later_track_ids=sorted(set(r['track_id'] for r in later)),later_observations=len(later),
                                    later_geometry_quality=geometry_quality(later,H),car_count_curve=curve)
        ax.plot([r['independent_cars'] for r in curve],[r['median_local_scale_difference_from_selected']*100 for r in curve],marker='o',label=name.replace('_',' '))
    ax.set(xlabel='Independent moving car tracks (chronological)',ylabel='Median local scale difference from selected map (%)',
           title=calibration['profile']['display_name']+' — sample-size diagnostic')
    ax.grid(alpha=.2);ax.legend();fig.savefig(output/'car_count_stability.png',dpi=160);plt.close(fig)
    (output/'calibration_stability.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('Calibration diagnostics complete:',calibration['camera_id'],flush=True)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--pilot',required=True)
    p.add_argument('--calibration',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();analyze(a.pilot,a.calibration,a.output)
