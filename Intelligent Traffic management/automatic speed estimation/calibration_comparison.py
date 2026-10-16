"""Compare per-video calibration versions and evaluate a reference-library hybrid.

Every test fold excludes its own speed from calibration and model selection.
All clips were previously inspected; these are development cross-validation
results, not a newly collected independent accuracy benchmark.
"""
import argparse,csv,hashlib,json,shutil
from pathlib import Path
import cv2
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from reference_calibration import refine_metric_scale
from longitudinal_calibration import fit_longitudinal_reference
from scene_registration import register_scenes,reference_options

PILOTS=['MercedesAMG550_30','MercedesAMG550_60','MercedesAMG550_100']
FALLBACK='v2d_flow_vp_delay'
FUSIONS=[(mode,weight) for mode in ['best','median'] for weight in [0,.25,.5,.75,1]]
_SCALE_CACHE={}


def metric_scale(raw,labels,version,exclude=()):
    names=[n for n in PILOTS if n in labels and n not in exclude
           and raw[n].get(version,{}).get('available')]
    if not names:return None,[]
    values=[raw[n][version]['estimated_kmh'] for n in names]
    key=(version,tuple((name,value,labels[name]) for name,value in zip(names,values)))
    if key not in _SCALE_CACHE:_SCALE_CACHE[key]=refine_metric_scale(values,[labels[n] for n in names])[0]
    scale=_SCALE_CACHE[key]
    return scale,names


def predict_version(query,raw,labels,version):
    result=raw[query].get(version,{'available':False,'reason':'missing_version'})
    if not result.get('available'):return result
    scale,names=metric_scale(raw,labels,version,exclude=[query])
    if scale is None:return {'available':False,'reason':'no_metric_scale_reference'}
    copied={**result,'raw_estimated_kmh':result['estimated_kmh'],
        'estimated_kmh':result['estimated_kmh']*scale,'metric_scale_multiplier':scale,
        'metric_scale_reference_videos':names,'own_reference_speed_used':False}
    return copied


def predict_hybrid(query,raw,labels,options,mode,weight):
    fallback=predict_version(query,raw,labels,FALLBACK)
    choices=[o for o in options.get(query,[]) if o['reference'] in labels and o['reference']!=query]
    if not choices or weight==0:
        return {**fallback,'calibration_reused':False,'library_weight':0,'reference_videos':[],
                'calibration_lookup_reason':'no_eligible_matching_reference' if not choices else 'geometry_version_selected'}
    choices=sorted(choices,key=lambda o:o['score'],reverse=True)
    best=choices[0];values=[o['prediction']['estimated_kmh'] for o in choices]
    reference_estimate=values[0] if mode=='best' else float(np.median(values))
    if not fallback.get('available'):weight=1
    estimate=reference_estimate if weight==1 else weight*reference_estimate+(1-weight)*fallback['estimated_kmh']
    result={**fallback,**best['prediction'],'available':True,'estimated_kmh':float(estimate),
        'method':'reference_library_and_temporal_geometry','calibration_reused':True,
        'library_weight':weight,'library_aggregation':mode,'reference_component_kmh':reference_estimate,
        'geometry_component_kmh':fallback.get('estimated_kmh'),
        'reference_videos':[o['reference'] for o in choices],
        'individual_reference_predictions_kmh':values,'shown_reference_video':best['reference'],
        'registration_evidence':best['registration'],'own_reference_speed_used':False,
        'calibration_lookup_reason':'verified_scene_overlap_and_supported_longitudinal_path'}
    return result


def select_fold(query,raw,labels,options):
    # Remove the test reference before calibration or configuration selection.
    training={name:speed for name,speed in labels.items() if name!=query}
    scores=[]
    for mode,weight in FUSIONS:
        errors=[]
        for name,reference in training.items():
            prediction=predict_hybrid(name,raw,training,options,mode,weight)
            errors.append(abs(prediction['estimated_kmh']-reference) if prediction.get('available') else 50)
        scores.append((float(np.mean(errors)),weight,mode))
    score,weight,mode=min(scores)
    result=predict_hybrid(query,raw,training,options,mode,weight)
    result['selection']={'training_videos':sorted(training),'inner_mean_absolute_error_kmh':score,
        'library_weight':weight,'library_aggregation':mode,'test_reference_excluded':True}
    return result


def metrics(rows):
    errors=np.array([r['error_kmh'] for r in rows if r.get('error_kmh') is not None])
    return {'clips':len(rows),'estimated':len(errors),
        'mae_kmh':float(np.mean(abs(errors))) if len(errors) else None,
        'rmse_kmh':float(np.sqrt(np.mean(errors**2))) if len(errors) else None,
        'bias_kmh':float(np.mean(errors)) if len(errors) else None,
        'maximum_absolute_error_kmh':float(np.max(abs(errors))) if len(errors) else None,
        'within_2_kmh':int((abs(errors)<=2).sum()),'errors_over_10_kmh':int((abs(errors)>10).sum())}


def run(args):
    inference=Path(args.inference_dir);first=Path(args.first_round);second=Path(args.second_round);out=Path(args.output)
    out.mkdir(parents=True,exist_ok=True);raw={};flows={};images={}
    for folder in sorted(first.iterdir()):
        if not (folder/'predictions.json').exists():continue
        name=folder.name;raw[name]=json.loads((folder/'predictions.json').read_text())
        raw[name].update(json.loads((second/name/'predictions.json').read_text()))
        flows[name]=json.loads((second/name/'adaptive_flow_features.json').read_text())
        images[name]=cv2.imread(str(inference/name/'reference.jpg'))
    assert len(raw)==30
    # Reference labels enter the experiment only after speed-blind inference.
    labels={name:float(name.rsplit('_',1)[1]) for name in raw}
    calibrations={name:fit_longitudinal_reference(flow,labels[name]) for name,flow in flows.items()}
    pairs_file=out/'scene_registrations.json'
    pairs=json.loads(pairs_file.read_text()) if pairs_file.exists() else register_scenes(images)
    pairs_file.write_text(json.dumps(pairs,indent=2),encoding='utf-8')
    options={name:reference_options(name,flows[name],calibrations,pairs) for name in raw}
    (out/'reference_calibrations.json').write_text(json.dumps(calibrations,indent=2),encoding='utf-8')
    (out/'reference_options.json').write_text(json.dumps(options,indent=2),encoding='utf-8')
    (out/'raw_predictions.json').write_text(json.dumps(raw,indent=2),encoding='utf-8')
    historical=json.loads(Path(args.historical_results).read_text()) if args.historical_results and Path(args.historical_results).exists() else []
    historical={Path(r['video']).stem:r for r in historical}
    rows=[];predictions={};version_rows=[]
    versions=sorted(set().union(*(p.keys() for p in raw.values())))
    for name in sorted(raw,key=lambda n:labels[n]):
        result=select_fold(name,raw,labels,options);predictions[name]=result
        value=result.get('estimated_kmh');error=None if value is None else value-labels[name]
        rows.append({'video':name+'.MP4','reference_kmh':labels[name],'estimated_kmh':value,
            'previous_estimated_kmh':historical.get(name,{}).get('estimated_kmh'),
            'previous_error_kmh':historical.get(name,{}).get('signed_error_kmh'),
            'error_kmh':error,'absolute_error_kmh':None if error is None else abs(error),
            'within_2_kmh':error is not None and abs(error)<=2,'method':result.get('method'),
            'calibration_reused':result.get('calibration_reused',False),
            'library_weight':result.get('library_weight',0),
            'reference_videos':';'.join(result.get('reference_videos',[])),
            'own_reference_excluded':True})
        for version in versions:
            p=predict_version(name,raw,labels,version);estimate=p.get('estimated_kmh') if p.get('available') else None
            version_rows.append({'video':name+'.MP4','version':version,'reference_kmh':labels[name],
                'estimated_kmh':estimate,'error_kmh':None if estimate is None else estimate-labels[name],
                'available':p.get('available',False)})
    summary={version:metrics([r for r in version_rows if r['version']==version]) for version in versions}
    raw_summary={version:metrics([{'error_kmh':raw[name][version]['estimated_kmh']-labels[name]
        if raw[name].get(version,{}).get('available') else None} for name in raw]) for version in versions}
    summary['selected_nested_hybrid']=metrics(rows)
    summary['selected_previous_27']=metrics([r for r in rows if Path(r['video']).stem not in PILOTS])
    fusion_summary={}
    for mode,weight in FUSIONS:
        values=[]
        for name in raw:
            p=predict_hybrid(name,raw,labels,options,mode,weight)
            values.append({'error_kmh':p['estimated_kmh']-labels[name] if p.get('available') else None})
        fusion_summary[f'{mode}_weight_{weight}']=metrics(values)
    best=min(fusion_summary,key=lambda key:fusion_summary[key]['mae_kmh'])
    source_names=['calibration_candidates.py','learned_calibration.py','flow_calibration.py','refine_flow.py',
        'lens_calibration.py','longitudinal_calibration.py','scene_registration.py','calibration_comparison.py']
    config={'method_family':'Reference library with optical-flow/vanishing-point temporal fallback',
        'selected_development_configuration':best,'fallback_version':FALLBACK,
        'fallback_metric_scale':metric_scale(raw,labels,FALLBACK)[0],'metric_scale_reference_videos':PILOTS,
        'scope':'This car and reference library; camera correspondence required for reuse',
        'own_reference_excluded_in_each_test':True,'fresh_independent_validation':False,
        'source_sha256':{name:hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest() for name in source_names}}
    for name,value in [('results.json',rows),('predictions.json',predictions),('metrics.json',summary),
        ('fusion_versions.json',fusion_summary),('selected_configuration.json',config),('raw_metrics.json',raw_summary)]:
        (out/name).write_text(json.dumps(value,indent=2),encoding='utf-8')
    for name,value in [('results.csv',rows),('version_results.csv',version_rows)]:
        with (out/name).open('w',newline='',encoding='utf-8') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(value[0]));writer.writeheader();writer.writerows(value)
    if args.archive_inputs:
        shutil.copytree(first,out/'inputs/round1',dirs_exist_ok=True)
        shutil.copytree(second,out/'inputs/round2',dirs_exist_ok=True)
    make_report(out,rows,summary,fusion_summary,config,raw_summary)
    if not args.no_render:
        from render_comparison import render_pair
        for row in rows:
            name=Path(row['video']).stem
            render_pair(Path(args.video_dir)/row['video'],out/'videos'/name,inference/name,
                predictions[name],row['reference_kmh'],flows[name])
    print('Selected nested per-video results:',summary['selected_nested_hybrid'],flush=True)
    print('Fixed deployment candidate:',best,fusion_summary[best],flush=True)


def make_report(out,rows,summary,fusions,config,raw_summary):
    m=summary['selected_nested_hybrid'];comparable=summary['selected_previous_27']
    lines=['# Calibration research and per-video tests','',
        'Run date: 2026-10-16 (Asia/Karachi). All 30 Mercedes clips are tested separately. Text annotations are ignored.',
        '',f"**Individual test result: MAE {m['mae_kmh']:.2f} km/h; {m['within_2_kmh']}/30 within ±2 km/h; worst error {m['maximum_absolute_error_kmh']:.2f} km/h.**",'',
        '**These are development reruns of previously inspected videos. They are not a fresh independent validation set. Each test reference is excluded from calibration and automated configuration selection.**','',
        '## Research and implementations','',
        '| Research | Used in this experiment | Scope |','|---|---|---|',
        '| [Revaud and Humenberger, ICCV 2021](https://github.com/naver/cctv) | Released learned mask-moment calibration network, direct and ensemble versions | Pinned upstream code/model; CC BY-NC-SA 3.0 retained; weights not redistributed |',
        '| [Kocur and Ftáčnik, 2021](https://arxiv.org/abs/2103.11438) | Vehicle motion vanishing points constrain new geometric fits | Own optical-flow/line estimator; their trained DeepVP network was not run |',
        '| [Su et al., 2026](https://arxiv.org/abs/2608.16785) | Compare optical flow with keypoint motion and update metric geometry | Inspired hybrid contact-anchor method; not a reproduction of their 36-keypoint network |',
        '| [Fitzgibbon, 2001](https://www.robots.ox.ac.uk/~vgg/publications/2001/Fitzgibbon01b/fitzgibbon01b.pdf) | Division-model radial correction estimated from visual motion | Own nonlinear motion fit; not the paper’s two-view eigenvalue algorithm |',
        '| [Vuong et al., WACV 2024](https://github.com/kvuong2711/OpenTrafficCam3D) | Considered scene-reconstruction calibration | Not run: required street-level/GPS imagery is absent |','',
        'Additional independently implemented candidates fit rigid cuboid motion, generic vehicle silhouettes, temporal front/rear delays, and reference-pass reciprocal road coordinates. No neural-network weights were fine-tuned. Vehicle dimensions remain priors, not a confirmed Mercedes CAD model.','',
        '## Pattern analysis','',
        'The historical 27-clip errors were not concentrated only at high speed: MAE was 7.49 km/h below 50, 11.64 at 50–79, and 8.17 at 80+. Correlation between reference speed and absolute error was approximately 0.086. These descriptive results do not establish causation. Unmatched camera views and inconsistent predicted hidden corners were stronger concerns.','',
        'The first GPU round compared ten versions on all 30 clips. Small image-fitting residuals did not guarantee accurate speed: the silhouette fits frequently selected incorrect focal lengths and scales. The learned network fitted the three pilots well after scale correction but transferred poorly to some other views. A two-dimensional projective time-delay method was more consistent. The second round added shared motion vanishing points, adaptive frame gaps, constant-motion rectification, a constrained 3D fit, and estimated radial distortion.','',
        '## Individual test protocol','',
        '1. Produce speed-blind geometry, mask moments and optical-flow measurements for every video.',
        '2. For each test, remove its reference speed before fitting metric scale or selecting a configuration. The fixed 30/60/100 calibration pilots are used only when they remain in that fold.',
        '3. Each eligible other video can supply a known-speed reference calibration. Scene matching and supported image locations decide whether it can be reused. A test is never its own reference.',
        '4. Select reference/geometry fusion using inner tests on the remaining 29 videos, excluding each inner test from its own references as well. Then predict the outer test.',
        '5. Read the outer reference only to calculate its error. Retain all failures and unavailable results. This is internal development cross-validation on one car and location.','',
        'Reference-library results benefit from additional labelled reference passes. They must not be attributed solely to a new automatic calibration model. Raw geometry/model predictions are reported separately from pilot scale correction and from reference-library assistance.','',
        '## Every geometric/model version','',
        'Each row uses reference scale fitted from the designated pilots with that test excluded. Missing estimates count against coverage and the tolerance total.','',
        '| Version | Estimated / 30 | Raw MAE | Scale-corrected MAE | Worst corrected error | Within ±2 | Errors >10 |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for version,result in summary.items():
        if version.startswith('selected_'):continue
        def fmt(x):return 'unavailable' if x is None else f'{x:.2f}'
        lines.append(f"| {version} | {result['estimated']}/30 | {fmt(raw_summary[version]['mae_kmh'])} | {fmt(result['mae_kmh'])} | {fmt(result['maximum_absolute_error_kmh'])} | {result['within_2_kmh']} | {result['errors_over_10_kmh']} |")
    lines+=['','## Hybrid versions','',
        'Weights are the contribution of the reference-library estimate when a compatible reference exists; otherwise the vanishing-point temporal estimate is used. These fixed-version rows are development comparisons. The final per-video predictions use the nested selection protocol above.','',
        '| Version | MAE km/h | Worst error | Within ±2 |','|---|---:|---:|---:|']
    for version,result in fusions.items():
        lines.append(f"| {version} | {result['mae_kmh']:.2f} | {result['maximum_absolute_error_kmh']:.2f} | {result['within_2_kmh']}/30 |")
    lines+=['',f"The frozen development configuration is **{config['selected_development_configuration']}**. Its settings are in [selected_configuration.json](selected_configuration.json).",'',
        '## Before and after','',
        f"On the same previous 27 test clips, historical MAE was 9.41 km/h and this development cross-validation gives {comparable['mae_kmh']:.2f} km/h. The new hybrid can use other labelled reference passes, while the historical run used only three pilots. The datasets and training information therefore differ; this is not a new independent head-to-head validation.",'',
        '![Historical and new individual errors](errors.jpg)','',
        '## Each video and its two outputs','',
        '| Video / calibration | Cruise reference | Previous estimate | New estimate | New signed error | Within ±2 | Calibration reused |',
        '|---|---:|---:|---:|---:|---|---|']
    for row in rows:
        stem=Path(row['video']).stem
        previous='unavailable' if row['previous_estimated_kmh'] is None else f"{row['previous_estimated_kmh']:.1f}"
        lines.append(f"| [{row['video']}](videos/{stem}/speed.mp4) · [calibration](videos/{stem}/calibration.mp4) | {row['reference_kmh']:.1f} | {previous} | {row['estimated_kmh']:.1f} | {row['error_kmh']:+.2f} | {'Yes' if row['within_2_kmh'] else 'No'} | {'Yes' if row['calibration_reused'] else 'No'} |")
    lines+=['','## Files and reproduction','',
        '- [Per-video CSV](results.csv), [all version results](version_results.csv), [metrics](metrics.json), [raw metrics before reference scaling](raw_metrics.json), [fold predictions and reference lists](predictions.json).',
        '- [Scene-registration evidence](scene_registrations.json), [reference calibrations](reference_calibrations.json), [reference options](reference_options.json), [raw version predictions](raw_predictions.json).',
        '- `inputs/round1` and `inputs/round2` preserve the model/motion outputs. Original videos and all downloaded weights are excluded.',
        '- Calibration videos review predicted nodes and the fitted longitudinal mapping. They do not claim a measured reconstruction of the entire road.',
        '- Reproduce from the feature folder using `python calibration_comparison.py --inference-dir output/mercedes_validation/inference --first-round output/calibration_comparison/inputs/round1 --second-round output/calibration_comparison/inputs/round2 --output outputs/comparison_reproduction --no-render`. Add `--video-dir <original-folder>` and omit `--no-render` to render videos.','',
        '## Accuracy limit','',
        'The requested ±1–2 km/h accuracy is achieved only if every individual error supports it. The report preserves the remaining large errors. Cruise-control settings are reference values, not independently measured radar speeds. Reference-library transfer assumes a compatible local road projection; full-scene matching can still contain ground parallax or lens effects. Unknown views rely on approximate vehicle geometry. The Mercedes calibration must not be copied to the original CCTV camera.']
    if m['maximum_absolute_error_kmh']>2:lines+=['','**The requested accuracy target is still not met across all videos.**']
    (out/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    fig,axes=plt.subplots(1,2,figsize=(13,5))
    refs=[r['reference_kmh'] for r in rows];values=[r['estimated_kmh'] for r in rows];errors=[r['error_kmh'] for r in rows]
    if all(r['previous_estimated_kmh'] is not None for r in rows):
        axes[0].scatter(refs,[r['previous_estimated_kmh'] for r in rows],c='grey',marker='x',label='Historical run')
        axes[1].scatter(refs,[r['previous_error_kmh'] for r in rows],c='grey',marker='x',label='Historical run')
    axes[0].scatter(refs,values,c=['steelblue' if r['calibration_reused'] else 'darkorange' for r in rows],label='New individual tests')
    axes[0].plot([25,110],[25,110],'k--');axes[0].set(xlabel='Cruise reference km/h',ylabel='Estimated km/h',title='Each video excluded from its own references')
    axes[1].axhspan(-2,2,color='green',alpha=.15);axes[1].scatter(refs,errors,label='New individual tests')
    axes[1].axhline(0,color='black',lw=.5);axes[1].set(xlabel='Cruise reference km/h',ylabel='Signed error km/h',title='All individual errors retained')
    for axis in axes:axis.grid(alpha=.2);axis.legend()
    fig.tight_layout();fig.savefig(out/'errors.jpg',dpi=150);plt.close(fig)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['inference-dir','first-round','second-round','output']:parser.add_argument('--'+name,required=True)
    parser.add_argument('--video-dir');parser.add_argument('--no-render',action='store_true')
    parser.add_argument('--historical-results',default=str(Path(__file__).parent/'output/mercedes_validation/results.json'))
    parser.add_argument('--archive-inputs',action='store_true');run(parser.parse_args())
