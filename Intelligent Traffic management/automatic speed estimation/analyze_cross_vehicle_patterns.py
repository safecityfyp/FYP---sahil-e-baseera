"""Describe calibration failures after evaluation, without changing predictions."""
import argparse
from pathlib import Path
import numpy as np
from benchmark_speed import load_clip
from calibration_candidates import select_rows
from calibration_comparison import metrics
from kia_validation import read,write,export_rows


def analyze(folder):
    out=Path(folder);configuration=read(out/'configuration.json');method=configuration['selected_method']
    rows=[]
    for result in read(out/'results.json'):
        name=Path(result['video']).stem;phase=result['phase']
        prediction=read(out/phase/'predictions.json')[name][method]
        observations,report=load_clip(out/'measurements'/phase/'inference'/name)
        usable=select_rows(observations,report)
        cache=read(out/phase/'foreground_scene_registrations.json')
        accepted=[key.split('|')[1] for key,value in cache.items() if key.startswith(name+'|') and value.get('accepted')]
        parts=prediction.get('geometry_calibration_components',[])
        rows.append({**result,'usable_ground_observations':len(usable),
                     'valid_geometry_duration_s':usable[-1]['time_s']-usable[0]['time_s'] if len(usable)>1 else 0,
                     'matched_geometry_observations':len(observations),
                     'native_fit_rms_weighted':parts[0]['prediction'].get('weighted_reprojection_rms') if parts else None,
                     'template_disagreement_kmh':prediction.get('template_disagreement_kmh'),
                     'any_radial_parameter_at_bound':any(abs(p['prediction'].get('radial_k1',0))>=.49 for p in parts),
                     'compatible_foreground_references':len(accepted),
                     'compatible_foreground_kia_references':sum(n.startswith('KiaSportage_') for n in accepted),
                     'reference_registration_used_by_selected_geometry':False})
    group={label:metrics([r for r in rows if predicate(r)]) for label,predicate in [
        ('fewer_than_20_usable_ground_observations',lambda r:r['usable_ground_observations']<20),
        ('at_least_20_usable_ground_observations',lambda r:r['usable_ground_observations']>=20),
        ('radial_fit_at_bound',lambda r:r['any_radial_parameter_at_bound']),
        ('radial_fit_inside_bounds',lambda r:not r['any_radial_parameter_at_bound'])]}
    summary={'groups':group,'clips_with_two_or_more_compatible_foreground_references':sum(r['compatible_foreground_references']>=2 for r in rows),
             'clips_without_compatible_foreground_references':sum(r['compatible_foreground_references']==0 for r in rows),
             'worst_new_tests':sorted(rows,key=lambda r:r['absolute_error_kmh'],reverse=True)[:5],
             'scope':'Post-evaluation descriptive analysis. No frozen parameter or test prediction was changed.'}
    write(out/'geometry_patterns.json',{'summary':summary,'per_video':rows});export_rows(out/'geometry_patterns.csv',rows)
    lines=['# Calibration patterns across vehicles','',
           'This analysis describes the completed tests. It does not retune the model or turn the reserved clips into calibration references.','',
           '## What the Kia tests establish','',
           '1. Camera compatibility must be checked per clip. One recording session does not imply one fixed view: the development contact sheet shows changes in direction and framing. Most attempted shared maps fell back to the baseline because they lacked sufficient compatible references.',
           '2. The strong motion vanishing-point constraint can amplify errors on short/noisy ground-corner tracks. On the 105 km/h development clip, it gives 136.7 km/h, while the unconstrained 2D temporal fit is about 106.1 km/h before transferred scale correction. The far-window fit is unstable on this clip, so a smaller window alone is not a reliable fix.',
           '3. Correcting two template scales and averaging their independently fitted cameras reduced reserved MAE from 3.81 to 2.36 km/h. This uses eight known-speed Kia calibration passes and does not demonstrate dimension-only automatic accuracy.',
           '4. The remaining worst error is 58 → 65.3 km/h. A fixed template correction does not resolve every view. When both templates share a bias, a small disagreement cannot certify accuracy. The disagreement field is a diagnostic, not an uncertainty bound.','',
           '| Geometry diagnostic (all 33; descriptive) | Clips | MAE | Worst error | Within ±2 |',
           '|---|---:|---:|---:|---:|']
    for label,m in group.items():
        lines.append(f"| {label} | {m['clips']} | {m['mae_kmh']:.2f} | {m['maximum_absolute_error_kmh']:.2f} | {m['within_2_kmh']} |")
    lines+=['','Counts alone do not establish why a particular estimate failed. Radial fits touching a bound can reflect an inadequate lens/shape model or an underconstrained fit; they are not measurements of true lens distortion.','',
            '## Remaining worst tests','',
            '| Clip | Group | Reference | Estimate | Error | Usable ground observations |',
            '|---|---|---:|---:|---:|---:|']
    for r in summary['worst_new_tests']:
        name=Path(r['video']).stem
        lines.append(f"| [{r['video']}](videos/{name}/speed.mp4) | {r['phase']} | {r['reference_kmh']:.1f} | {r['estimated_kmh']:.1f} | {r['error_kmh']:+.2f} | {r['usable_ground_observations']} |")
    regression=out/'mercedes_regression/metrics.json'
    if regression.exists():
        m=read(regression)
        lines+=['','## Cross-check on the previous Mercedes recordings','',
                'These are additional development reruns of the same Mercedes clips, each excluding itself. They use the other Mercedes references; Kia reserved speeds are absent. The published original Mercedes results are preserved.','',
                '| Mercedes version | MAE | Within ±2 / 30 |','|---|---:|---:|']
        for version,x in m.items():lines.append(f"| {version} | {x['mae_kmh']:.2f} | {x['within_2_kmh']} |")
        lines+=['','Shared lens-aware trajectory calibration gives a small Mercedes improvement; other shared maps are worse. This supports retaining version-specific evidence rather than replacing every camera with one calibration recipe.','']
    lines+=['## What remains to reach the tolerance','',
            'The next calibration version should fit only well-supported ground contacts, model lens/camera changes explicitly, and reuse a reference road map only where the correspondence is supported. Template-scale transfer should be tied to a recognized vehicle family. These tests do not yet demonstrate that those quality measures can guarantee ±2 km/h. More accurate ground-contact/keypoint evidence or independently measured road/camera references, followed by new reserved clips, are needed to verify that claim.','',
            'The current committed solution is the frozen geometry ensemble. No post-reserved correction, filename-speed shortcut or manual per-video adjustment was applied.','',
            '[Per-video geometry diagnostics](geometry_patterns.csv) · [Full report and all paired videos](README.md)','']
    (out/'PATTERNS.md').write_text('\n'.join(lines),encoding='utf-8')
    print('Published descriptive geometry/camera diagnostics without changing any prediction.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True)
    analyze(parser.parse_args().output)
