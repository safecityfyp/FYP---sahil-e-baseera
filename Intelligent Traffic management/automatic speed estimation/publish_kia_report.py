"""Package individual Kia tests, before/after evidence and paired output videos."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from calibration_comparison import metrics
from kia_validation import read,write,export_rows


def bands(rows):
    return {label:metrics([r for r in rows if low<=r['reference_kmh']<high])
            for label,low,high in [('below_50',0,50),('50_to_79',50,80),('80_plus',80,200)]}


def package(args):
    root=Path(__file__).resolve().parent;out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    dev=Path(args.development_evaluation);test=Path(args.reserved_evaluation)
    configuration=read(args.configuration);method=configuration['selected_method']
    assert read(test/'frozen_configuration_used.json')==configuration
    all_rows=read(dev/'results.json')+read(test/'results.json')
    baseline=[r for r in all_rows if r['version']=='frozen_mercedes_baseline']
    improved=[r for r in all_rows if r['version']==method]
    assert len(improved)==len(baseline)==33
    baseline_by_name={r['video']:r for r in baseline}
    for row in improved:
        before=baseline_by_name[row['video']]
        row.update(previous_estimated_kmh=before['estimated_kmh'],previous_error_kmh=before['error_kmh'])
    summary={phase:{'before':metrics([r for r in baseline if phase=='all_33' or r['phase']==phase]),
                    'after':metrics([r for r in improved if phase=='all_33' or r['phase']==phase])}
             for phase in ['development','reserved','all_33']}
    summary['reserved_accuracy_target_met']=summary['reserved']['after']['within_2_kmh']==25
    pattern={'before_by_speed':bands(baseline),'after_by_speed':bands(improved),
             'speed_absolute_error_correlation_before':float(np.corrcoef([r['reference_kmh'] for r in baseline],
                 [r['absolute_error_kmh'] for r in baseline])[0,1]),
             'speed_absolute_error_correlation_after':float(np.corrcoef([r['reference_kmh'] for r in improved],
                 [r['absolute_error_kmh'] for r in improved])[0,1]),
             'scope':'Descriptive diagnostics only. Reserved errors were not used to choose the frozen method.'}
    for phase,source in [('development',dev),('reserved',test)]:shutil.copytree(source,out/phase,dirs_exist_ok=True)
    write(out/'configuration.json',configuration);write(out/'metrics.json',summary)
    write(out/'patterns.json',pattern);write(out/'results.json',improved);export_rows(out/'results.csv',improved)
    for phase,measurements in [('development',args.development_measurements),('reserved',args.reserved_measurements)]:
        shutil.copytree(measurements,out/'measurements'/phase,dirs_exist_ok=True)
    if args.mercedes_comparison:
        shutil.copytree(args.mercedes_comparison,out/'mercedes_regression',dirs_exist_ok=True)
    fig,axes=plt.subplots(1,2,figsize=(13,5))
    speeds=np.array([r['reference_kmh'] for r in improved]);order=np.argsort(speeds)
    axes[0].plot([25,110],[25,110],color='gray',linestyle='--',label='Reference')
    axes[0].scatter(speeds,[r['estimated_kmh'] for r in baseline],label='Frozen Mercedes transfer',s=28)
    axes[0].scatter(speeds,[r['estimated_kmh'] for r in improved],label='Adapted camera calibration',s=28)
    axes[0].set(xlabel='Cruise-control reference (km/h)',ylabel='Estimated speed (km/h)',title='All 33 Kia clips')
    axes[0].legend(fontsize=8)
    for rows,label in [(baseline,'Before'),(improved,'After')]:
        axes[1].plot(speeds[order],np.array([r['absolute_error_kmh'] for r in rows])[order],'.-',label=label)
    axes[1].axhline(2,color='gray',linestyle='--',label='2 km/h tolerance')
    axes[1].set(xlabel='Reference (km/h)',ylabel='Absolute error (km/h)',title='Development and reserved tests combined')
    axes[1].legend(fontsize=8);fig.tight_layout();fig.savefig(out/'before_after.jpg',dpi=150);plt.close(fig)
    if not args.no_render:
        from render_cross_vehicle import render
        for row in improved:
            name=Path(row['video']).stem;phase=row['phase'];measurements=out/'measurements'/phase
            prediction=read(out/phase/'predictions.json')[name][method]
            render(Path(args.video_dir)/row['video'],out/'videos'/name,measurements/'inference'/name,
                   prediction,row['reference_kmh'],read(measurements/'round2'/name/'adaptive_flow_features.json'),phase)
            print('Rendered paired videos:',name,flush=True)
    m=summary['reserved'];d=summary['development'];a=summary['all_33']
    lines=['# Kia Sportage: cross-vehicle calibration tests','',
           'Run date: 2026-10-16 (Asia/Karachi). All 33 clips are separate tests. Filename speeds are constant cruise-control references, confirmed by the user. Text annotation files are ignored.','',
           '**Primary result: the 25 reserved clips, evaluated after the method was frozen.**','',
           '| Group | Before MAE | After MAE | After within ±2 km/h | Worst after error |',
           '|---|---:|---:|---:|---:|']
    for label,value in [('Eight development clips (leave-one-out calibration; used for method selection)',d),
                        ('25 reserved clips (not used for method selection)',m),('All 33 (mixed summary)',a)]:
        x=value['after'];lines.append(f"| {label} | {value['before']['mae_kmh']:.2f} | {x['mae_kmh']:.2f} | {x['within_2_kmh']}/{x['clips']} | {x['maximum_absolute_error_kmh']:.2f} |")
    lines+=['',f"Selected method: **{method}**. The ±2 km/h target across every reserved clip is **{'met' if summary['reserved_accuracy_target_met'] else 'not met'}**.",'',
            'The before result transfers the frozen Mercedes configuration and its 30-pass reference library to the Kia. The adapted result can use eight additional known-speed Kia reference passes. These are different calibration inputs: improvement must not be attributed solely to a better automatic model. The reserved clips share the same location and Kia recording session; they do not establish accuracy at a new camera or site.','',
            '![Before and after](before_after.jpg)','',
            '## Protocol and versions','',
            'The [experiment plan](../../kia_experiment_plan.json) declared the eight development clips and 25 reserved clips before Kia errors were examined. Every development test excludes its own speed and reference calibration. The selected method and source hashes were then frozen in [configuration.json](configuration.json), before the reserved errors were calculated. No reserved speed enters a calibration fit or method selection. No neural-network weights were fine-tuned.','',
            'New comparisons separate a vehicle-length prior, an expanded reference library using the previous model, lower-image scene registration, shared reciprocal camera maps from optical flow, shared trajectory fitting, a lens-aware trajectory fit, and quadratic/cubic local scale curves. The second round adds per-video SUV template/lens fits and native/SUV geometry ensembles. The ensemble corrects each template’s metric scale from other known-speed Kia passes, then combines their independent per-video camera fits. This empirical template correction is vehicle-specific and is not automatic identification of the true dimensions. Unavailable shared maps fall back explicitly to the frozen baseline. Such fallbacks remain in the error totals.','',
            'The approximate 4.485 m Kia length comes from a [2021 Kia specification](https://www.kia.com/content/dam/kwcms/kme/it/it/assets/contents/utility/price-list/2021/03/Listino_Kia_Sportage_Pubblico_01_03_2021.pdf). The exact year/trim is unconfirmed, so this is a dimension prior, not an identified vehicle measurement. The filenames and speeds match the [VS13 paper](https://slobodan.ucg.ac.me/science/vs13/paper.pdf), which describes one Kia and three Mercedes recording sessions. That match is supporting context, not a byte-level source-identification claim.','',
            '| Development version | MAE km/h | Within ±2 | Worst error |','|---|---:|---:|---:|']
    for version,value in read(dev/'metrics.json').items():
        lines.append(f"| {version} | {value['mae_kmh']:.2f} | {value['within_2_kmh']}/8 | {value['maximum_absolute_error_kmh']:.2f} |")
    lines+=['','All 18 previous physical/model versions and six new geometry ablations are retained per clip in each group’s `physical_version_results.csv`. Previous versions show their Mercedes-transferred scale; new ablations retain raw values and have no Mercedes scale if no corresponding pilot exists. These diagnostics were not used to change the chosen method after reserved evaluation.','',
            '## Patterns','',
            '| Speed band (all 33; descriptive) | Before MAE | After MAE | After within ±2 |',
            '|---|---:|---:|---:|']
    for label,old in pattern['before_by_speed'].items():
        new=pattern['after_by_speed'][label]
        lines.append(f"| {label} | {old['mae_kmh']:.2f} | {new['mae_kmh']:.2f} | {new['within_2_kmh']}/{new['clips']} |")
    lines+=['','Detailed signed errors, reference reuse, fallbacks and software/model provenance are retained. Correlation and band summaries describe patterns; they do not prove a cause.','',
            '## Each video and its calibration/speed outputs','',
            '| Clip / outputs | Group | Reference | Before | After | Signed error | Within ±2 |',
            '|---|---|---:|---:|---:|---:|---|']
    for row in sorted(improved,key=lambda r:r['reference_kmh']):
        name=Path(row['video']).stem
        lines.append(f"| [{row['video']}](videos/{name}/speed.mp4) · [calibration](videos/{name}/calibration.mp4) | {row['phase']} | {row['reference_kmh']:.1f} | {row['previous_estimated_kmh']:.1f} | {row['estimated_kmh']:.1f} | {row['error_kmh']:+.2f} | {'Yes' if row['within_2_kmh'] else 'No'} |")
    lines+=['','## Evidence and limits','',
            '- [Full numeric results](results.csv) and [group metrics](metrics.json).',
            '- [Development results](development/results.csv), [reserved results](reserved/results.csv), and their full predictions/reference lists.',
            '- [Speed-band diagnostics](patterns.json), [verification](artifact_verification.json), and [provenance](provenance.json).',
            '- The speed videos show an estimated constant pass speed to one decimal place. Calibration videos show predicted vehicle ground nodes and local distance marks; they are not a complete survey of the road.',
            '- Cruise-control settings are the evaluation reference. Results are reference-assisted research on these recordings, with a reserved same-session check.','']
    (out/'README.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps(summary,indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['development-evaluation','reserved-evaluation','development-measurements','reserved-measurements',
                 'configuration','output','video-dir']:parser.add_argument('--'+name,required=True)
    parser.add_argument('--mercedes-comparison');parser.add_argument('--no-render',action='store_true')
    package(parser.parse_args())
