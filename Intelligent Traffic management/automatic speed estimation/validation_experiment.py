"""Evaluate a frozen pilot calibration on separate constant-speed clips and render paired videos."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import cv2
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from benchmark_speed import load_clip,estimate_single_pass,target_records
from camera_cache import file_sha256
from calibrate_speed import project
from reference_calibration import register_road,trajectory_points,estimate_reference_speed

PILOT_NAMES={f'MercedesAMG550_{value}.MP4' for value in [30,60,100]}
ROOT=Path(__file__).resolve().parent
AUTOMATIC_CONFIG={'length_m':4.9,'width_m':1.87,'min_height':100,'max_height':500,
                  'corner_order':'checkpoint','legacy_normalization':False}
LEGACY_CONFIG={'length_m':4.5,'width_m':1.8,'corner_order':'motion','legacy_normalization':True}


def predict(observations,report,image,reference,calibration):
    """No filename or reference speed is available to this function."""
    points,times,rows=trajectory_points(observations,report)
    transform,evidence=register_road(reference,image)
    if transform is not None and points is not None:
        aligned=project(points,transform)
        hull=np.array(calibration['support_hull_image'],np.float32)
        keep=np.array([cv2.pointPolygonTest(hull,tuple(map(float,p)),True)>=-10 for p in aligned])
        if keep.sum()>=8 and times[keep][-1]-times[keep][0]>=.25:
            result=estimate_reference_speed(aligned[keep],times[keep],calibration)
            result.update(available=True,method='reference_assisted_registered_road',
                          track_id=rows[0]['track_id'],mapping=(np.array(calibration['H_image_to_meters'])@transform).tolist(),
                          support_hull_image=project(calibration['support_hull_image'],np.linalg.inv(transform)).tolist(),
                          road_registration=evidence,observations=int(keep.sum()))
            return result
    result=estimate_single_pass(observations,report,AUTOMATIC_CONFIG)
    result['road_registration']=evidence
    result['method']='automatic_single_pass_geometry'
    if result.get('available'):
        result['trajectory_rms_m']=result['motion_diagnostics']['trajectory_fit_rms_m']
    return result


def statistics(rows,column):
    values=[r for r in rows if r.get(column) is not None and np.isfinite(r[column])]
    if not values:return {'clips':len(rows),'estimated':0,'coverage':0}
    errors=np.array([r[column]-r['reference_kmh'] for r in values]);absolute=np.abs(errors)
    return {'clips':len(rows),'estimated':len(values),'coverage':len(values)/max(len(rows),1),
            'mae_kmh':float(absolute.mean()),'rmse_kmh':float(np.sqrt(np.mean(errors**2))),
            'bias_kmh':float(errors.mean()),'median_absolute_error_kmh':float(np.median(absolute)),
            'maximum_absolute_error_kmh':float(absolute.max()),
            'mape_percent':float(np.mean([abs(r[column]-r['reference_kmh'])/r['reference_kmh']*100 for r in values])),
            'within_1_kmh':int((absolute<=1).sum()),'within_2_kmh':int((absolute<=2).sum()),
            'errors_over_10_kmh':int((absolute>10).sum())}


def grid(frame,H,hull):
    hull=np.array(hull,np.float32)
    if len(hull)<3:return frame
    world=project(hull,H)
    if not np.isfinite(world).all() or np.ptp(world,axis=0).max()>500:return frame
    low,high=np.percentile(world,[5,95],axis=0)
    mask=np.zeros(frame.shape[:2],np.uint8);cv2.fillConvexPoly(mask,hull.astype(int),255)
    overlay=np.zeros_like(frame);inverse=np.linalg.inv(H)
    for axis in [0,1]:
        for value in np.arange(np.floor(low[axis]/5)*5,high[axis]+5,5):
            segment=np.array([low-5,high+5]);segment[:,axis]=value
            points=project(segment,inverse)
            if np.isfinite(points).all() and abs(points).max()<100000:
                cv2.line(overlay,tuple(points[0].astype(int)),tuple(points[1].astype(int)),(0,220,255),2)
    selected=(mask>0)&np.any(overlay>0,axis=2);frame[selected]=overlay[selected]
    cv2.polylines(frame,[hull.astype(int)],True,(255,180,0),2)
    return frame


def render_pair(video,folder,observations,report,tracks,result,reference_kmh):
    folder.mkdir(parents=True,exist_ok=True)
    source=cv2.VideoCapture(str(video));assert source.isOpened()
    fps=float(source.get(cv2.CAP_PROP_FPS));width=int(source.get(3));height=int(source.get(4))
    size=(1280,720);scale=np.array([1280/width,720/height])
    by_frame={};box_frames={}
    for row in observations:by_frame.setdefault(row['frame_index'],[]).append(row)
    for row in tracks:box_frames.setdefault(row['frame_index'],[]).append(row)
    raw={name:folder/(name+'.avi') for name in ['calibration','speed']}
    writers={name:cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*'MJPG'),fps,size) for name,path in raw.items()}
    assert all(writer.isOpened() for writer in writers.values())
    retained=target_records(observations,report,80,500)
    hull=result.get('support_hull_image',[])
    H=np.array(result['mapping']) if result.get('available') else None
    frames=0;labelled=0
    estimate=result.get('estimated_kmh');interval=result.get('time_interval_s',[0,0])
    title=f'Estimated pass speed: {estimate:.1f} km/h' if estimate is not None else 'Speed unavailable: insufficient calibration geometry'
    try:
        while True:
            ok,frame=source.read()
            if not ok:break
            calibration_frame=frame.copy()
            if H is not None:calibration_frame=grid(calibration_frame,H,hull)
            for row in by_frame.get(frames,[]):
                points=np.array(row['keypoints'])[report['ground_indices'],:2].astype(int)
                cv2.polylines(calibration_frame,[points],True,(0,255,0),3)
                for node,point in enumerate(points):
                    cv2.circle(calibration_frame,tuple(point),6,(0,255,255),-1)
                    cv2.putText(calibration_frame,str(node),tuple(point+[8,-8]),cv2.FONT_HERSHEY_SIMPLEX,.6,(0,255,255),2)
            calibration_frame=cv2.resize(calibration_frame,size);speed_frame=cv2.resize(frame,size)
            timestamp=frames/fps
            for row in box_frames.get(frames,[]):
                p=np.array(row['box']).reshape(2,2)*scale
                active=result.get('available') and row['track_id']==result.get('track_id') and interval[0]<=timestamp<=interval[1]
                color=(0,255,255) if active else (160,160,160)
                cv2.rectangle(speed_frame,tuple(p[0].astype(int)),tuple(p[1].astype(int)),color,2)
                if active:
                    labelled+=1;text=f'{estimate:.1f} km/h'
                    pos=(max(5,int(p[0,0])),max(100,int(p[0,1])-8))
                    cv2.putText(speed_frame,text,pos,cv2.FONT_HERSHEY_SIMPLEX,.85,(0,0,0),4)
                    cv2.putText(speed_frame,text,pos,cv2.FONT_HERSHEY_SIMPLEX,.85,color,2)
            for image in [calibration_frame,speed_frame]:
                cv2.rectangle(image,(0,0),(1280,76),(20,20,20),-1)
                cv2.rectangle(image,(0,677),(1280,720),(20,20,20),-1)
            cv2.putText(calibration_frame,'CALIBRATION REVIEW | ground nodes + local 5 m grid',(15,29),cv2.FONT_HERSHEY_SIMPLEX,.7,(0,220,255),2)
            cv2.putText(calibration_frame,'Offline fitted mapping | '+result.get('method','unavailable'),(15,58),cv2.FONT_HERSHEY_SIMPLEX,.53,(230,230,230),1)
            cv2.putText(calibration_frame,'Vehicle geometry is predicted. This is a local mapping, not a measured survey.',(15,704),cv2.FONT_HERSHEY_SIMPLEX,.55,(230,230,230),1)
            cv2.putText(speed_frame,title,(15,31),cv2.FONT_HERSHEY_SIMPLEX,.82,(0,255,255),2)
            cv2.putText(speed_frame,f'Average over source t={interval[0]:.2f}-{interval[1]:.2f} s | Experimental estimate',(15,60),cv2.FONT_HERSHEY_SIMPLEX,.57,(230,230,230),1)
            evaluation=f'Cruise-control reference: {reference_kmh:.1f} km/h'
            if estimate is not None:evaluation+=f' | Signed error: {estimate-reference_kmh:+.1f} km/h'
            cv2.putText(speed_frame,evaluation,(15,704),cv2.FONT_HERSHEY_SIMPLEX,.62,(230,230,230),1)
            writers['calibration'].write(calibration_frame);writers['speed'].write(speed_frame)
            if frames==round(sum(interval)/2*fps):cv2.imwrite(str(folder/'speed_example.jpg'),speed_frame)
            frames+=1
    finally:
        source.release()
        for writer in writers.values():writer.release()
    for name,path in raw.items():
        subprocess.run(['ffmpeg','-y','-loglevel','error','-i',str(path),'-c:v','libx264','-crf','25',
                        '-pix_fmt','yuv420p','-movflags','+faststart',str(folder/(name+'.mp4'))],check=True)
        path.unlink()
    (folder/'render_report.json').write_text(json.dumps({'frames':frames,'fps':fps,'duration_s':frames/fps,
        'speed_display_decimal_places':1,'vehicle_label_frames':labelled,
        'files':['calibration.mp4','speed.mp4']},indent=2),encoding='utf-8')


def run(args):
    source=Path(args.inference_dir);videos=Path(args.video_dir);out=Path(args.output)
    out.mkdir(parents=True,exist_ok=True)
    calibration=json.loads(Path(args.calibration).read_text())
    reference=cv2.imread(str(source/'MercedesAMG550_30/reference.jpg'));assert reference is not None
    rows=[];predictions={}
    # Freeze all configuration before any held-out prediction is compared with its label.
    frozen={'pilot_videos':sorted(PILOT_NAMES),'reference_calibration':calibration,
            'automatic_config':AUTOMATIC_CONFIG,'legacy_config':LEGACY_CONFIG,
            'prediction_source_sha256':file_sha256(ROOT/'validation_experiment.py'),
            'reference_calibration_source_sha256':file_sha256(ROOT/'reference_calibration.py'),
            'geometry_source_sha256':file_sha256(ROOT/'calibrate_speed.py'),
            'benchmark_source_sha256':file_sha256(ROOT/'benchmark_speed.py'),
            'reference_type':'User-confirmed cruise control setting from filename; .txt files ignored',
            'network_fine_tuned':False}
    (out/'frozen_calibration.json').write_text(json.dumps(frozen,indent=2),encoding='utf-8')
    for folder in sorted(source.iterdir()):
        if not (folder/'observations.json').exists():continue
        video_name=folder.name+'.MP4';obs,report=load_clip(folder)
        image=cv2.imread(str(folder/'reference.jpg'))
        initial=estimate_single_pass(obs,report,LEGACY_CONFIG)
        automatic=estimate_single_pass(obs,report,AUTOMATIC_CONFIG)
        final=predict(obs,report,image,reference,calibration)
        predictions[video_name]=final
        # The reference enters only here, after predictions have been produced.
        reference_kmh=float(folder.name.rsplit('_',1)[1])
        row={'video':video_name,'split':'pilot' if video_name in PILOT_NAMES else 'holdout',
             'reference_kmh':reference_kmh,'legacy_diagnostic_kmh':initial.get('estimated_kmh'),
             'corrected_automatic_kmh':automatic.get('estimated_kmh'),'estimated_kmh':final.get('estimated_kmh'),
             'method':final.get('method'),'available':final.get('available',False),
             'reference_used_during_calibration':video_name in PILOT_NAMES,
             'trajectory_rms_m':final.get('trajectory_rms_m')}
        estimate=row['estimated_kmh'];error=None if estimate is None else estimate-reference_kmh
        row.update(signed_error_kmh=error,absolute_error_kmh=None if error is None else abs(error),
                   relative_error_percent=None if error is None else abs(error)/reference_kmh*100,
                   within_2_kmh=False if error is None else abs(error)<=2)
        rows.append(row)
        archive=out/'inference'/folder.name;archive.mkdir(parents=True,exist_ok=True)
        for name in ['observations.json','geometry_run_report.json','tracks.json','reference.jpg']:
            shutil.copy2(folder/name,archive/name)
        if not args.no_render:
            render_pair(videos/video_name,out/'videos'/folder.name,obs,report,
                        json.loads((folder/'tracks.json').read_text()),final,reference_kmh)
        print(video_name,'reference',reference_kmh,'estimate',None if estimate is None else round(estimate,2),
              'error',None if error is None else round(error,2),row['method'],flush=True)
    with (out/'results.csv').open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    (out/'results.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
    (out/'predictions.json').write_text(json.dumps(predictions,indent=2),encoding='utf-8')
    metrics={split:{column:statistics([r for r in rows if split=='all' or r['split']==split],column)
                    for column in ['legacy_diagnostic_kmh','corrected_automatic_kmh','estimated_kmh']}
             for split in ['pilot','holdout','all']}
    (out/'metrics.json').write_text(json.dumps(metrics,indent=2),encoding='utf-8')
    make_report(out,rows,metrics)


def make_report(out,rows,metrics):
    holdout=metrics['holdout']['estimated_kmh'];pilot=metrics['pilot']['estimated_kmh']
    def number(value):return 'unavailable' if value is None else f'{value:.2f}'
    lines=['# Mercedes speed validation report','',
        'Run date: 2026-10-16 (Asia/Karachi). References are the user-confirmed cruise-control settings in filenames. Text annotation files are ignored.',
        '',f"**Held-out result: MAE {number(holdout.get('mae_kmh'))} km/h; {holdout.get('within_2_kmh',0)}/{holdout['clips']} clips within ±2 km/h; {holdout['estimated']}/{holdout['clips']} estimated.**",'',
        '## Protocol','',
        'The first development clips were 30, 60 and 100 km/h. They were used to diagnose geometry and fit the reference-assisted calibration. The remaining 27 speeds were reserved for evaluation; their reference speeds are read only after each prediction is produced. Calibration, model hashes and configuration are saved in [frozen_calibration.json](frozen_calibration.json).',
        '', 'Pilot fitting results are not independent accuracy measurements. The held-out set still shares the same car and recording location, so it does not establish performance on other cars or the original CCTV camera.',
        '', '## What changed','',
        '1. The video now displays a single point estimate with one decimal place. Sensitivity ranges remain in the original CCTV data files.',
        '2. Separate calibration-review and speed-estimation videos are produced for each evaluated clip.',
        '3. Ground-corner ordering now follows the checkpoint topology instead of selecting length edges from image motion; that heuristic frequently selected width edges in the roadside view.',
        '4. Projective normalization is centred on observed footprints and the solver permits low-camera perspectives with a horizon near image centre. A synthetic regression test covers that case.',
        '5. Reference-assisted calibration uses only the three pilot speeds and constant-motion trajectories. It is transferred only through verified road-texture registration. Unmatched views use an explicitly labelled automatic single-pass geometry estimate.',
        '', 'No neural-network weights were fine-tuned. These are calibration and estimation changes. The single-pass fallback uses an assumed 4.9 m × 1.87 m vehicle prior; exact vehicle dimensions were not independently confirmed.',
        '', '## Before and after','',
        'The original production workflow cannot calibrate a clip containing only one car track: it requires three tracks. Legacy numbers below are explicitly **single-pass diagnostic estimates** made by relaxing that eligibility rule, not outputs that passed the old production checks.',
        '', '| Split | Legacy diagnostic MAE | Corrected geometry MAE | Final MAE | Final within ±2 km/h |',
        '|---|---:|---:|---:|---:|']
    for split in ['pilot','holdout','all']:
        m=metrics[split];f=m['estimated_kmh']
        lines.append(f"| {split} | {number(m['legacy_diagnostic_kmh'].get('mae_kmh'))} | {number(m['corrected_automatic_kmh'].get('mae_kmh'))} | {number(f.get('mae_kmh'))} | {f.get('within_2_kmh',0)}/{f['clips']} |")
    lines+=['','## Every clip','',
            '| Clip / videos | Split | Reference | Initial diagnostic | Corrected geometry | Final estimate | Signed error | Within ±2 |',
            '|---|---|---:|---:|---:|---:|---:|---|']
    for row in sorted(rows,key=lambda r:r['reference_kmh']):
        stem=Path(row['video']).stem
        link=f"[{row['video']}](videos/{stem}/speed.mp4) · [calibration](videos/{stem}/calibration.mp4)"
        lines.append(f"| {link} | {row['split']} | {row['reference_kmh']:.1f} | {number(row['legacy_diagnostic_kmh'])} | {number(row['corrected_automatic_kmh'])} | {number(row['estimated_kmh'])} | {number(row['signed_error_kmh'])} | {'Yes' if row['within_2_kmh'] else 'No'} |")
    lines+=['','## Error analysis','',
        f"Held-out RMSE: {number(holdout.get('rmse_kmh'))} km/h. Maximum absolute error: {number(holdout.get('maximum_absolute_error_kmh'))} km/h. Signed bias: {number(holdout.get('bias_kmh'))} km/h. Errors above 10 km/h: {holdout.get('errors_over_10_kmh',0)}.",
        '', 'All available point estimates are included in these metrics, including poor results. Missing estimates count against coverage and against the within-tolerance total. No clip is removed because its reference error is large.',
        '', '**The requested accuracy target is met only if the held-out errors support it.** Cruise control supplies a reference setting, not an independently measured radar speed. Camera perspective, lens distortion, incorrect hidden ground corners and uncertain vehicle dimensions can still cause substantial errors. A learned cuboid is not a measured ground survey.',
        '', '## Artifacts and reproduction','',
        '- [Detailed results CSV](results.csv), [metrics JSON](metrics.json), [prediction diagnostics](predictions.json).',
        '- [Frozen calibration and provenance](frozen_calibration.json); [saved speed-blind inference inputs](inference/).',
        '- All clips have a calibration video and a speed video under `videos/`. Speed videos show the cruise reference only as an evaluation overlay; it is not provided to the prediction function.',
        '- Reproduce with `python validation_experiment.py --inference-dir output/mercedes_validation/inference --video-dir <original-video-folder> --calibration output/mercedes_validation/frozen_calibration.json --output outputs/validation_reproduction` (use the `reference_calibration` object when loading a frozen bundle).',
        '', '## Research context','',
        'The filenames, speed list and scenes match the Mercedes subset of the [VS13 dataset](https://slobodan.ucg.ac.me/science/vs13/), whose authors describe cruise-control recordings from varied camera positions. The experiment uses the owner-provided clips and filename references. The approach uses the [UrbanOmniDetect checkpoint](https://github.com/mkturkcan/urbanomnidetect) and is inspired by [Sochor et al.](https://arxiv.org/abs/1702.06451).',
        '', '## Conclusion','']
    if holdout.get('maximum_absolute_error_kmh',float('inf'))<=2 and holdout['estimated']==holdout['clips']:
        lines.append('All held-out clips are within the requested ±2 km/h tolerance relative to the cruise-control references. Further tests across independent vehicles, camera sites and measured reference speeds are still required.')
    else:
        lines.append('The requested ±1–2 km/h accuracy has not been demonstrated across this held-out set. The report preserves failures as well as improvements. Further calibration work is required before treating these estimates as reliable: measured scene distances or independently verified vehicle geometry, lens calibration, and reference passes for unmatched camera setups would reduce the current ambiguity. This benchmark calibration must not be copied to the original CCTV camera.')
    (out/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    available=[r for r in rows if r['estimated_kmh'] is not None]
    fig,axes=plt.subplots(1,2,figsize=(13,5))
    for split,color in [('pilot','orange'),('holdout','steelblue')]:
        subset=[r for r in available if r['split']==split]
        axes[0].scatter([r['reference_kmh'] for r in subset],[r['estimated_kmh'] for r in subset],label=split,c=color)
        axes[1].scatter([r['reference_kmh'] for r in subset],[r['signed_error_kmh'] for r in subset],label=split,c=color)
    axes[0].plot([25,110],[25,110],'k--');axes[0].set(xlabel='Cruise reference km/h',ylabel='Estimated km/h',title='Point estimates against reference')
    axes[1].axhspan(-2,2,color='green',alpha=.15,label='±2 km/h');axes[1].axhline(0,color='black',lw=.5)
    axes[1].set(xlabel='Cruise reference km/h',ylabel='Signed error km/h',title='All errors retained')
    for axis in axes:axis.grid(alpha=.2);axis.legend()
    fig.tight_layout();fig.savefig(out/'validation_errors.jpg',dpi=150);plt.close(fig)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inference-dir',required=True);parser.add_argument('--video-dir',required=True)
    parser.add_argument('--calibration',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--no-render',action='store_true')
    args=parser.parse_args()
    # A frozen bundle can be supplied directly for reproduction.
    bundle=json.loads(Path(args.calibration).read_text())
    if 'reference_calibration' in bundle:
        temporary=Path(args.output)/'reference_calibration_reproduction.json';temporary.parent.mkdir(parents=True,exist_ok=True)
        temporary.write_text(json.dumps(bundle['reference_calibration']),encoding='utf-8');args.calibration=str(temporary)
    run(args)
