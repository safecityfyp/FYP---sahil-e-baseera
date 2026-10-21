"""Run frozen image-assisted predictions first; score references in a separate command."""
from pathlib import Path
from datetime import datetime,timezone
import argparse
import csv
import json
import numpy as np
from vision_calibration import fit,estimate,digest

ROOT=Path(__file__).resolve().parent
DEFAULT=ROOT/'output/vision_assisted_trial'
METHODS=('local_affine','projective_single','projective_consensus')


def predict(folder):
    folder=Path(folder)
    if (folder/'prediction_freeze.json').exists():
        raise ValueError('Frozen predictions exist. Use a new experiment folder for a new revision.')
    frozen={}
    for case in sorted(p for p in folder.iterdir() if p.is_dir() and (p/'annotations.json').exists()):
        for method in METHODS:
            mapping=case/f'calibration_{method}.json'
            prediction=case/f'prediction_{method}.json'
            fit(case/'annotations.json',mapping,method)
            estimate(case/'annotations.json',mapping,case/'frames.json',prediction)
            for path in [mapping,prediction,case/'annotations.json',case/'frames.json']:
                frozen[str(path.relative_to(folder)).replace('\\','/')]=digest(path)
        print('Frozen numerical predictions:',case.name,flush=True)
    # Images are transitively bound by annotation SHA; sources are evaluated later.
    result=dict(created_utc=datetime.now(timezone.utc).isoformat(),files_sha256=frozen,
        method_policy='Default projective_consensus: median independent snapshot scale, selected before errors. '
                      'local_affine is a control; projective_single uses only the middle screenshot for scale.',
        reference_files_read=False,neural_weights_changed=False,
        experiment='Initial six individually calibrated clips, selected to span low/mid/high settings in each vehicle.',
        independence='Previously studied clips, not a fresh blinded test. Assistant has prior conversation context. '
                     'No reference speed is an argument to calibration or prediction.')
    (folder/'prediction_freeze.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')


def evaluate(folder):
    folder=Path(folder)
    freeze=json.loads((folder/'prediction_freeze.json').read_text())
    for name,expected in freeze['files_sha256'].items():
        if digest(folder/name)!=expected:
            raise ValueError(f'Frozen file changed: {name}')
    sources=json.loads((folder/'evaluation_sources.json').read_text())
    baselines={}
    for path in [ROOT/'output/calibration_comparison/results.csv',ROOT/'output/kia_validation/results.csv']:
        with path.open(newline='',encoding='utf-8-sig') as stream:
            baselines.update({r['video']:float(r['estimated_kmh']) for r in csv.DictReader(stream)})
    rows=[]
    for source in sources:
        video=source['source_video']
        # Label reading occurs only in evaluation, after the prediction hash check.
        reference=float(Path(video).stem.rsplit('_',1)[1])
        for method in METHODS:
            result=json.loads((folder/source['case_id']/f'prediction_{method}.json').read_text())
            low,high=result['sensitivity_95_percentile_kmh'] or [None,None]
            predicted=result['estimated_kmh']
            rows.append(dict(case_id=source['case_id'],video=video,vehicle=source['vehicle'],method=method,
                reference_cruise_setting_kmh=reference,estimated_kmh=predicted,error_kmh=predicted-reference,
                absolute_error_kmh=abs(predicted-reference),within_2_kmh=abs(predicted-reference)<=2,
                conditional_sensitivity_low_kmh=low,conditional_sensitivity_high_kmh=high,
                start_s=result['time_interval_s'][0],end_s=result['time_interval_s'][1],
                geometry_consistency_pass=result['geometry_consistency_pass'],
                historical_pipeline_kmh=baselines[video],
                historical_absolute_error_kmh=abs(baselines[video]-reference)))
    with (folder/'results.csv').open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    summaries={}
    for method in METHODS:
        for vehicle in ['all','MercedesAMG550','KiaSportage']:
            subset=[r for r in rows if r['method']==method and (vehicle=='all' or r['vehicle']==vehicle)]
            errors=np.array([r['error_kmh'] for r in subset])
            summaries[method+'/'+vehicle]=dict(clips=len(subset),mae_kmh=float(np.mean(abs(errors))),
                bias_kmh=float(np.mean(errors)),rmse_kmh=float(np.sqrt(np.mean(errors**2))),
                maximum_absolute_error_kmh=float(np.max(abs(errors))),within_2_kmh=int(np.sum(abs(errors)<=2)))
    selected=[r for r in rows if r['method']=='projective_consensus']
    summaries['historical_pipeline/same_six_clips']=dict(clips=len(selected),
        mae_kmh=float(np.mean([r['historical_absolute_error_kmh'] for r in selected])),
        note='Historical pipelines use other known-speed passes; different evidence budget, not a pure method ablation.')
    report=dict(prediction_freeze_sha256=digest(folder/'prediction_freeze.json'),methods=summaries,
                default_method='projective_consensus',reference='Filename cruise-control setting, user confirmed.',
                reference_uncertainty='Unknown; no independent radar/GPS trace or calibrated speedometer supplied.',
                independence='All six are reused development/studied videos; results do not establish fresh generalization.',
                no_neural_training=True,external_llm_api_called=False)
    (folder/'metrics.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['predict','evaluate'])
    p.add_argument('--folder',default=str(DEFAULT))
    a=p.parse_args()
    (predict if a.command=='predict' else evaluate)(a.folder)
