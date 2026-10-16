"""Cross-vehicle development and a locked, reserved Kia speed evaluation.

Development reads eight Kia references. Reserved speed errors cannot be generated
until the chosen method and its source hashes have been frozen to configuration.
The previous Mercedes calibration is retained as a separate transfer baseline.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
from calibration_comparison import predict_hybrid, predict_version, metrics, FALLBACK
from longitudinal_calibration import fit_longitudinal_reference
from scene_registration import register_scenes, reference_options
from shared_camera_calibration import foreground_registration, fit_shared_camera, predict_shared_camera

ROOT=Path(__file__).resolve().parent
CANDIDATES=['vehicle_length_prior','expanded_reference_library','foreground_reference_library',
            'shared_flow','shared_trajectory','shared_trajectory_radial','shared_curve2','shared_curve3',
            'geometry_native','geometry_suv','geometry_temporal',
            'geometry_ensemble_25','geometry_ensemble_50','geometry_ensemble_75']
SOURCE_FILES=['kia_validation.py','shared_camera_calibration.py','calibration_comparison.py',
              'longitudinal_calibration.py','scene_registration.py','refine_flow.py','calibration_candidates.py',
              'vehicle_geometry_refinement.py']
KIA_LENGTH_PRIOR_M=4.485


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')


def source_hashes():return {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in SOURCE_FILES}


def load_measurements(folder):
    folder=Path(folder);raw={};flows={};images={};inference={}
    for clip in sorted((folder/'inference').iterdir()):
        if not (clip/'observations.json').exists():continue
        name=clip.name
        raw[name]={**read(folder/'round1'/name/'predictions.json'),**read(folder/'round2'/name/'predictions.json')}
        extra=folder/'geometry_refinement'/name/'predictions.json'
        if extra.exists():raw[name].update(read(extra))
        flows[name]=read(folder/'round2'/name/'adaptive_flow_features.json')
        images[name]=cv2.imread(str(clip/'reference.jpg'));assert images[name] is not None
        inference[name]=str(clip)
    return raw,flows,images,inference


def load_mercedes():
    saved=ROOT/'output/calibration_comparison'
    raw=read(saved/'raw_predictions.json')
    flows={name:read(saved/'inputs/round2'/name/'adaptive_flow_features.json') for name in raw}
    inference={name:str(ROOT/'output/mercedes_validation/inference'/name) for name in raw}
    images={name:cv2.imread(str(Path(inference[name])/'reference.jpg')) for name in raw}
    return raw,flows,images,inference


def foreground_pairs(images, queries, references, cache_file):
    cache=read(cache_file) if Path(cache_file).exists() else {}
    for query in sorted(queries):
        for reference in sorted(references):
            if query==reference:continue
            key=query+'|'+reference
            inverse=reference+'|'+query
            if key in cache:continue
            if inverse in cache and cache[inverse].get('accepted'):
                old=cache[inverse]
                cache[key]={**old,'query_to_template':np.linalg.inv(old['query_to_template']).tolist(),
                            'inverted_cached_registration':True}
            else:
                # The template is the query image. This transform maps reference pixels to it.
                cache[key]=foreground_registration(images[query],images[reference])
        write(cache_file,cache)
        print('Foreground registrations:',query,flush=True)
    return cache


def foreground_options(query, flow, calibrations, cache):
    from longitudinal_calibration import predict_longitudinal
    values=[]
    for reference,calibration in calibrations.items():
        if reference==query:continue
        evidence=cache.get(query+'|'+reference,{})
        if not evidence.get('accepted'):continue
        transform=np.linalg.inv(evidence['query_to_template'])
        prediction=predict_longitudinal(flow,calibration,transform)
        if prediction.get('available'):
            values.append({'reference':reference,'prediction':prediction,
                           'score':evidence['inliers']*evidence['coverage'],
                           'registration':evidence})
    return sorted(values,key=lambda r:r['score'],reverse=True)


def candidate(query, method, raw, flows, training, options, foreground, cache, baseline):
    allowed={name:speed for name,speed in training.items() if name!=query}
    if method.startswith('geometry_'):
        # Empirical template scale is vehicle-specific, not a camera homography.
        # It can transfer across viewpoints while each query fits its own camera.
        same_car={name:speed for name,speed in allowed.items() if name.rsplit('_',1)[0]==query.rsplit('_',1)[0]}
        families={'geometry_native':[('v3b_rigid_distortion',1)],
                  'geometry_suv':[('suv_rigid_radial',1)],
                  'geometry_temporal':[('v2b_delay_2d',1)],
                  'geometry_ensemble_25':[('v3b_rigid_distortion',.25),('suv_rigid_radial',.75)],
                  'geometry_ensemble_50':[('v3b_rigid_distortion',.5),('suv_rigid_radial',.5)],
                  'geometry_ensemble_75':[('v3b_rigid_distortion',.75),('suv_rigid_radial',.25)]}
        parts=[]
        for version,weight in families[method]:
            source=raw[query].get(version,{})
            references=[name for name in same_car if raw[name].get(version,{}).get('available')]
            if not source.get('available') or len(references)<2:continue
            ratios=[same_car[name]/raw[name][version]['estimated_kmh'] for name in references]
            scale=float(np.median(ratios))
            parts.append({'version':version,'weight':weight,'metric_scale':scale,
                          'prediction':source,'reference_videos':references,
                          'estimated_kmh':source['estimated_kmh']*scale})
        if not parts:return {**baseline,'adaptation':method,'used_frozen_baseline_fallback':True}
        denominator=sum(p['weight'] for p in parts)
        for part in parts:part['weight']/=denominator
        dominant=max(parts,key=lambda p:p['weight'])['prediction']
        estimate=float(sum(p['weight']*p['estimated_kmh'] for p in parts))
        disagreement=float(np.ptp([p['estimated_kmh'] for p in parts]))
        return {**dominant,'estimated_kmh':estimate,
                'method':'per_video_geometry_with_reference_template_scale','adaptation':method,
                'reference_videos':sorted(set(n for p in parts for n in p['reference_videos'])),
                'geometry_calibration_components':parts,'calibration_reused':False,
                'template_disagreement_kmh':disagreement,
                'calibration_review_required':disagreement>max(10,estimate*.15),
                'disagreement_is_accuracy_interval':False,
                'own_reference_excluded':True,'query_reference_speed_used':False,
                'scale_scope':'Empirical cuboid-template bias correction for this vehicle family; query camera fitted independently.'}
    if method=='vehicle_length_prior':
        result={**baseline}
        if not baseline.get('calibration_reused'):
            result['estimated_kmh']*=KIA_LENGTH_PRIOR_M/4.9
        else:
            result['estimated_kmh']=baseline['library_weight']*baseline['reference_component_kmh']+(1-baseline['library_weight'])*baseline['geometry_component_kmh']*KIA_LENGTH_PRIOR_M/4.9
            result['geometry_component_kmh']*=KIA_LENGTH_PRIOR_M/4.9
        return {**result,'method':'frozen_baseline_with_vehicle_length_prior','length_prior_m':KIA_LENGTH_PRIOR_M}
    if method in ['expanded_reference_library','foreground_reference_library']:
        choices=options if method=='expanded_reference_library' else foreground
        return {**predict_hybrid(query,raw,allowed,choices,'top3weighted',.75),'adaptation':method}
    transforms={name:evidence['query_to_template'] for name in allowed
                if (evidence:=cache.get(query+'|'+name,{})).get('accepted')}
    family={'shared_flow':'flow','shared_trajectory':'trajectory','shared_trajectory_radial':'trajectory_radial',
            'shared_curve2':'scale_curve','shared_curve3':'scale_curve'}[method]
    model=fit_shared_camera(flows,allowed,transforms,family,degree=3 if method.endswith('3') else 2)
    result=predict_shared_camera(flows[query],model,np.eye(3))
    if not result.get('available'):
        result={**baseline,'shared_camera_unavailable_reason':result.get('reason'),
                'shared_camera_attempt':model,'used_frozen_baseline_fallback':True}
    return {**result,'adaptation':method,'own_reference_excluded':True}


def row(name, result, speed, method, phase):
    estimate=result.get('estimated_kmh') if result.get('available') else None
    error=None if estimate is None else estimate-speed
    return {'video':name+'.MP4','phase':phase,'version':method,'reference_kmh':speed,'estimated_kmh':estimate,
            'error_kmh':error,'absolute_error_kmh':None if error is None else abs(error),
            'within_2_kmh':error is not None and abs(error)<=2,
            'reference_videos':';'.join(result.get('reference_videos',[])),
            'calibration_reused':result.get('calibration_reused',False),
            'baseline_fallback':result.get('used_frozen_baseline_fallback',False)}


def export_rows(path,rows):
    with Path(path).open('w',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)


def run(args):
    cv2.setNumThreads(4)
    plan=read(ROOT/'kia_experiment_plan.json')
    out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    config_path=Path(args.configuration)
    config=None
    if args.phase=='reserved':
        config=read(config_path)
        assert config['frozen_before_reserved_errors'] is True
        assert config['source_sha256']==source_hashes(),'Calibration code changed after configuration freeze.'
        assert config['calibration_kia_videos']==plan['development_videos']
    raw,flows,images,inference=load_mercedes()
    mercedes_labels={name:float(name.rsplit('_',1)[1]) for name in raw}
    for folder in [args.development_measurements]+([args.reserved_measurements] if args.phase=='reserved' else []):
        r,f,i,d=load_measurements(folder);raw.update(r);flows.update(f);images.update(i);inference.update(d)
    queries=plan['development_videos'] if args.phase=='development' else plan['reserved_test_videos']
    assert all(name in raw for name in queries)
    # Only designated development speeds enter the reference library.
    development_labels={name:float(name.rsplit('_',1)[1]) for name in plan['development_videos']}
    training={**mercedes_labels,**development_labels}
    calibrations={name:fit_longitudinal_reference(flows[name],speed) for name,speed in training.items()}
    global_file=out/'global_scene_registrations.json'
    pairs=read(global_file) if global_file.exists() else register_scenes(images)
    write(global_file,pairs)
    options={name:reference_options(name,flows[name],calibrations,pairs) for name in queries}
    cache=foreground_pairs(images,queries,training,out/'foreground_scene_registrations.json')
    foreground={name:foreground_options(name,flows[name],calibrations,cache) for name in queries}
    rows=[];predictions={};physical_rows=[]
    all_versions=['frozen_mercedes_baseline']+(CANDIDATES if args.phase=='development' else [config['selected_method']])
    for name in queries:
        baseline=predict_hybrid(name,raw,mercedes_labels,options,'top3weighted',.75)
        results={'frozen_mercedes_baseline':baseline}
        for method in all_versions[1:]:results[method]=candidate(name,method,raw,flows,training,options,foreground,cache,baseline)
        for result in results.values():
            assert name not in result.get('reference_videos',[]),'A test became its own reference.'
            assert not set(plan['reserved_test_videos'])&set(result.get('reference_videos',[]))
        if config and config['selected_method'].startswith('geometry_'):
            for part in results[config['selected_method']].get('geometry_calibration_components',[]):
                assert abs(part['metric_scale']-config['vehicle_metric_scales'][part['version']])<1e-12
        predictions[name]=results
        # Test reference is read only after every prediction for that test has been produced.
        reference=float(name.rsplit('_',1)[1])
        rows.extend(row(name,result,reference,method,args.phase) for method,result in results.items())
        for version in sorted(raw[name]):
            physical=predict_version(name,raw,mercedes_labels,version)
            physical_rows.append({**row(name,physical,reference,version,args.phase),
                                  'raw_estimated_kmh':raw[name][version].get('estimated_kmh'),
                                  'raw_error_kmh':raw[name][version].get('estimated_kmh',reference)-reference if raw[name][version].get('available') else None})
        print(name,{method:round(result['estimated_kmh'],3) if result.get('available') else None for method,result in results.items()},flush=True)
    summary={method:metrics([r for r in rows if r['version']==method]) for method in all_versions}
    write(out/'results.json',rows);export_rows(out/'results.csv',rows)
    write(out/'predictions.json',predictions);write(out/'metrics.json',summary)
    write(out/'physical_version_results.json',physical_rows);export_rows(out/'physical_version_results.csv',physical_rows)
    write(out/'inference_locations.json',inference)
    write(out/'protocol.json',{'phase':args.phase,'calibration_references':sorted(training),
          'reserved_test_references_used_for_training':False,'own_reference_exclusion_verified':True,
          'query_to_reference_registration_speed_blind':True,'source_sha256':source_hashes(),
          'vehicle_length_prior_m':KIA_LENGTH_PRIOR_M,
          'vehicle_prior_source':'https://www.kia.com/content/dam/kwcms/kme/it/it/assets/contents/utility/price-list/2021/03/Listino_Kia_Sportage_Pubblico_01_03_2021.pdf',
          'vehicle_prior_scope':'Approximate 2021 European Sportage specification; exact trim unconfirmed.'})
    if args.phase=='development':
        selected=min(CANDIDATES,key=lambda method:sum(r['absolute_error_kmh'] if r['absolute_error_kmh'] is not None else 50
                      for r in rows if r['version']==method)/len(queries))
        config={'selected_method':selected,'selection':'Minimum 8-clip leave-one-out development MAE; unavailable prediction costs 50 km/h.',
                'frozen_before_reserved_errors':True,'calibration_kia_videos':plan['development_videos'],
                'calibration_mercedes_videos':sorted(mercedes_labels),'development_metrics':summary,
                'source_sha256':source_hashes(),'baseline_commit':plan['frozen_baseline']['source_commit'],
                'scope':'Reference-assisted camera calibration. Eight known-speed Kia passes are extra calibration information.',
                'reserved_test_count':25}
        config['vehicle_metric_scales']={version:float(np.median([development_labels[name]/raw[name][version]['estimated_kmh']
             for name in development_labels if raw[name].get(version,{}).get('available')]))
             for version in ['v3b_rigid_distortion','suv_rigid_radial','v2b_delay_2d']}
        config['reference_measurement_sha256']={name:hashlib.sha256(json.dumps(raw[name],sort_keys=True).encode()).hexdigest()
                                                for name in development_labels}
        write(config_path,config)
        print('FROZEN METHOD:',selected,flush=True)
    else:
        write(out/'frozen_configuration_used.json',config)
    print(json.dumps(summary,indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase',choices=['development','reserved'],required=True)
    parser.add_argument('--development-measurements',required=True)
    parser.add_argument('--reserved-measurements')
    parser.add_argument('--output',required=True)
    parser.add_argument('--configuration',required=True)
    run(parser.parse_args())
