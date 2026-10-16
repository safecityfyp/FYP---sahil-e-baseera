"""Publish verified complete CCTV runs, paired videos and reproducible measurements."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from cctv_calibration import read_rows
from cctv_speed import split_segments

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'output/cctv_20261009'


def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def copy(source,target):
    target=Path(target);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)


def clock(seconds):
    seconds=int(round(seconds));return f'{seconds//3600:02d}:{seconds//60%60:02d}:{seconds%60:02d}'


def copy_measurements(source,target):
    for pattern in ['*.json','*.gz','*.yaml','reference.jpg','view_*.jpg']:
        for path in Path(source).glob(pattern):copy(path,Path(target)/path.name)


def figures(camera,folder,calibration,speed):
    destination=folder/'figures';destination.mkdir(exist_ok=True)
    rows=read_rows(folder/'speed','speeds.jsonl.gz')
    names=list(calibration['regions']);colors=['#087e8b','#b56319']
    fig,ax=plt.subplots(figsize=(11,4.5),layout='constrained')
    for i,name in enumerate(names):
        local=[r for r in rows if r['region']==name]
        stride=max(1,len(local)//6000);sample=local[::stride]
        if sample:ax.scatter([r['time_s']/60 for r in sample],[r['experimental_kmh'] for r in sample],s=3,alpha=.45,color=colors[i],label=name.replace('_',' '))
    ax.set(xlabel='Recording time (minutes)',ylabel='Experimental km/h',
           title=calibration['profile']['display_name']+' — local car speed estimates')
    ax.grid(alpha=.2);ax.legend(loc='upper right');fig.savefig(destination/'speed_over_time.png',dpi=160);plt.close(fig)
    fig,axes=plt.subplots(1,len(names),figsize=(11,4.5),layout='constrained',squeeze=False)
    for i,name in enumerate(names):
        ax=axes[0,i];local=[r for r in rows if r['region']==name]
        ids=sorted(set(r['track_id'] for r in local));selected=ids[::max(1,len(ids)//40)][:40]
        for tid in selected:
            group=[r for r in local if r['track_id']==tid]
            for segment in split_segments(group):
                points=np.array([r['ground_center_world_m'] for r in segment])
                if len(points):ax.plot(points[:,0],points[:,1],linewidth=.8,alpha=.55)
        ax.set(xlabel='Local X (experimental m)',ylabel='Local Y (experimental m)',title=name.replace('_',' '))
        ax.set_aspect('equal',adjustable='datalim');ax.grid(alpha=.2)
    fig.suptitle('Sample car trajectories — independent local road coordinates')
    fig.savefig(destination/'trajectories.png',dpi=160);plt.close(fig)
    fig,axes=plt.subplots(1,len(names),figsize=(11,4),layout='constrained',squeeze=False)
    for i,name in enumerate(names):
        result=calibration['regions'][name];candidates=result.get('candidate_comparison',[]);ax=axes[0,i]
        labels=[r['method'].replace('projective_metric','projective + size prior') for r in candidates]
        ax.bar(labels,[r['score'] for r in candidates],color=[colors[i] if r['method']==result.get('method') else '#b5b9bd' for r in candidates])
        ax.set(title=name.replace('_',' '),ylabel='Internal consistency score (lower is better)');ax.tick_params(axis='x',labelrotation=15)
    fig.suptitle('Mapping selection uses held-out car geometry, not measured speed error')
    fig.savefig(destination/'calibration_methods.png',dpi=160);plt.close(fig)


def publish_camera(camera,run,pilot,remainder):
    run=Path(run);folder=OUT/camera;folder.mkdir(parents=True,exist_ok=True)
    calibration=json.loads((run/'calibration/calibration.json').read_text())
    speed=json.loads((run/'speed/speed_report.json').read_text())
    videos=json.loads((run/'videos/video_manifest.json').read_text())
    assert videos['video_covers_entire_source'] and videos['speed_rendered_frames']==videos['source_frames']
    assert calibration['all_regions_accepted'] and speed['all_sampled_views_consistent']
    assert calibration['source_sha256']==speed['source_sha256']==videos['source_sha256']
    for name in ['calibration','speed','videos']:
        for path in (run/name).iterdir():
            if path.is_file() and path.suffix in ['.json','.gz','.csv','.jpg','.mp4']:
                copy(path,folder/name/path.name)
    copy_measurements(pilot,folder/'measurements/pilot');copy_measurements(remainder,folder/'measurements/remainder')
    # Every reviewed video must be individually suitable for an ordinary Git commit.
    for path in (folder/'videos').glob('*.mp4'):
        assert path.stat().st_size<100*1024**2,f'Video exceeds GitHub file limit: {path.name}'
    summaries=json.loads((folder/'speed/track_summary.json').read_text())
    with (folder/'speed/track_summary.csv').open('w',newline='',encoding='utf-8') as stream:
        keys=['track_id','start_s','end_s','samples','median_experimental_kmh','min_experimental_kmh','max_experimental_kmh']
        writer=csv.DictWriter(stream,fieldnames=keys);writer.writeheader();writer.writerows(summaries)
    figures(camera,folder,calibration,speed)
    regions=[]
    for name,r in calibration['regions'].items():
        regions.append(f'| {name.replace("_"," ")} | {r["calibration_end_s"]/60:g} min | {len(r["track_ids"])} | {r["method"]} | {r["subset_scale_change_p90"]*100:.1f}% |')
    segments=[];cursor=0.0
    for r in [r for r in videos['files'] if r['file'].startswith('speed_')]:
        duration=float(r['duration']);end=cursor+duration
        segments.append(f'| {clock(cursor)}–{clock(end)} | [{r["file"]}](videos/{r["file"]}) | {int(r["nb_frames"]):,} |')
        cursor=end
    name=calibration['profile']['display_name'];total=videos['source_frames']/videos['source_fps']
    text=f'''# {name}: full CCTV experiment

Processed **{clock(total)}**, all **{videos['source_frames']:,} source frames**, at **{videos['source_fps']:g} FPS**. The annotated speed video covers the complete recording; its ordered parts are below. Resolution is 1280 × 720, H.264, without audio.

**Experimental speeds, not independently validated.** No measured speed or road-distance reference is available for this camera. MAE, accuracy improvement and ±1–2 km/h compliance cannot be calculated from these recordings. Decimal display precision does not establish measurement accuracy.

## Calibration video

[Open/download the separate calibration replay](videos/calibration.mp4) — {clock(videos['calibration_rendered_frames']/videos['source_fps'])}. It shows the final selected road grid and predicted ground nodes over the initial calibration interval. This is an offline replay, rather than a claim that the final mapping was known before collecting those cars.

| Road region | Initial interval | Qualifying car tracks | Selected fit | Car-subset scale change, 90th percentile |
|---|---:|---:|---|---:|
'''+ '\n'.join(regions)+f'''

Each region is selected independently from 5-, 10- and 15-minute candidates. Subset changes describe internal stability, not ground-truth speed error. A nominal 4.5 × 1.8 m car supplies the metre scale. Road polygons are selected manually. Only the calibrated local patch is mapped; physical camera pitch and the entire road length are not independently measured.

![Calibration replay](videos/calibration_example.jpg)

## Complete speed video

| Source-video interval | Ordered video part | Frames |
|---|---|---:|
'''+ '\n'.join(segments)+f'''

**{speed['cars_with_speed_estimates']} car track IDs** have **{speed['speed_counts'].get('accepted_speed_samples',0):,} qualified local speed samples**. Track IDs may fragment and reset at 15 minutes; this is not a verified unique-vehicle count. Turning and accelerating vehicles receive local estimates instead of one constant speed for their entire pass. Grey boxes have no qualified metric estimate. Motorcycles, buses and trucks remain tracking-only.

The secondary range tests car-subset mapping variation and ±20% scale changes. It is a sensitivity envelope, not a confidence interval or a guarantee that true speed falls inside it. Unknown vehicle dimensions, lens distortion, road slopes and ground-point errors remain unresolved absolute-accuracy limits.

![Decimal experimental speed example](videos/speed_example_00.jpg)

## Tables and checks

- [Every qualified speed sample](speed/speed_samples.csv) and [per-track summary](speed/track_summary.csv).
- [Calibration matrices, method comparison and window history](calibration/calibration.json).
- [Speed calculation, filters and periodic camera-view checks](speed/speed_report.json).
- [Complete video frame/duration manifest](videos/video_manifest.json).
- [Pilot measurements](measurements/pilot/) and [remaining-recording measurements](measurements/remainder/).

![Local speed samples across the complete recording](figures/speed_over_time.png)

![Calibration method selection](figures/calibration_methods.png)

![Mapped sample trajectories](figures/trajectories.png)

See [the two-camera report](../README.md) and [method/reproduction notes](../../../cctv_method.md). Camera-specific limitation: {calibration['profile']['limitations']}
'''
    (folder/'README.md').write_text(text,encoding='utf-8')
    return dict(camera_id=camera,display_name=name,duration_s=total,source_fps=videos['source_fps'],
                source_frames=videos['source_frames'],source_sha256=videos['source_sha256'],
                calibration_duration_s=calibration['calibration_duration_s'],regions=calibration['regions'],
                car_tracks_with_speed=speed['cars_with_speed_estimates'],speed_samples=speed['speed_counts'].get('accepted_speed_samples',0),
                speed_segments=len(segments),all_sampled_views_consistent=speed['all_sampled_views_consistent'])


def publish(commercial,commercial_pilot,k_block,k_block_pilot):
    OUT.mkdir(parents=True,exist_ok=True)
    items=[publish_camera('commercial_ii_01',commercial,commercial_pilot,Path(commercial)/'remainder'),
           publish_camera('k_block_st20',k_block,k_block_pilot,Path(k_block)/'remainder')]
    inventory=json.loads((ROOT/'outputs/cctv_20261009/source_inventory.json').read_text())
    save(OUT/'source_inventory.json',[{k:v for k,v in r.items() if k!='source_path'} for r in inventory])
    save(OUT/'experiment_summary.json',dict(cameras=items,total_frames=sum(i['source_frames'] for i in items),
                                           total_duration_s=sum(i['duration_s'] for i in items),accuracy_validated=False,
                                           known_speeds_used=False,benchmark_vehicle_corrections_used=False,
                                           source_recordings_included=False,model_weights_included=False))
    rows=[]
    for i in items:
        rows.append(f'| [{i["display_name"]}]({i["camera_id"]}/README.md) | {clock(i["duration_s"])} | {i["calibration_duration_s"]/60:g} min | {i["car_tracks_with_speed"]} | {i["speed_segments"]} |')
    text='''# Two real CCTV cameras: calibration and full speed videos

Both supplied recordings were processed independently, with multi-car camera calibration followed by local speed estimation. **All 187,641 frames across 141 minutes 22.05 seconds are covered by the annotated speed outputs.** Each camera also has its own separate calibration video.

| Camera and full report | Complete recording | Calibration replay | Car track IDs with qualified speeds | Ordered speed parts |
|---|---:|---:|---:|---:|
'''+ '\n'.join(rows)+'''

Open either camera report for its calibration video, every speed-video segment, tables, maps and diagnostics. The parts preserve full source frame rates and complete source coverage. Single full-length speed files are also exported locally under the supplied CCTV folder's `output` directory.

**Accuracy is unverified.** These cameras have no independently measured speeds or road dimensions. Multiple cars improve geometric consistency and sample stability; they do not remove the unknown absolute scale of monocular footage. A 4.5 × 1.8 m nominal car supplies the metric scale. No Mercedes/Kia empirical speed correction or expected traffic speed was used. The requested ±1–2 km/h accuracy cannot be established on this material.

## What changed for these angles

- Commercial uses separate carriageway maps. Its left mapping is supported by 14 qualifying car tracks in 5 minutes; the right uses 21 tracks in 10 minutes. Adding a soft fleet-size constraint improved internal calibration consistency and car-subset stability.
- K Block separates the near approach from the cross street. Its first 2.5 FPS geometry run missed most brief passes. The revised 10 FPS run provides 18 near-approach and 14 cross-street calibration tracks within 5 minutes. The ordinary projective fit scores better there than the metric-prior variant, so it is retained.
- The pinned cuboid checkpoint's actual XY/corner convention is handled explicitly. Parked cars are excluded from calibration. Later inference uses the fixed road map to locate vehicles; it does not fit a new camera from each passing car.
- Local 2D speed windows support turning, acceleration and braking. Grey tracks lack a qualified speed. Passenger cars receive decimal km/h labels plus a secondary sensitivity range; other vehicle classes remain tracking-only.

See [the detailed pattern and pilot history](PATTERNS.md), [method and reproduction steps](../../cctv_method.md), [experiment summary](experiment_summary.json), [source hashes](source_inventory.json), [Kaggle provenance](provenance/kaggle_jobs.json), and [verification](verification.json). Raw source footage, API credentials and model weights are excluded from Git.
'''
    (OUT/'README.md').write_text(text,encoding='utf-8')
    return items


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--commercial',required=True);p.add_argument('--commercial-pilot',required=True)
    p.add_argument('--k-block',required=True);p.add_argument('--k-block-pilot',required=True)
    a=p.parse_args();publish(a.commercial,a.commercial_pilot,a.k_block,a.k_block_pilot)
