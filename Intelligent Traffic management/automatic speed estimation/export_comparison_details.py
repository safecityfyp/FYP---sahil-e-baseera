"""Export every fixed hybrid configuration's per-video result from a saved snapshot."""
import argparse,csv,json
from pathlib import Path
from calibration_comparison import FUSIONS,predict_hybrid,metrics


def export(snapshot):
    snapshot=Path(snapshot)
    raw=json.loads((snapshot/'raw_predictions.json').read_text())
    options=json.loads((snapshot/'reference_options.json').read_text())
    selected=json.loads((snapshot/'results.json').read_text())
    labels={Path(r['video']).stem:r['reference_kmh'] for r in selected}
    expected=json.loads((snapshot/'fusion_versions.json').read_text());rows=[]
    for mode,weight in FUSIONS:
        group=[]
        for name in sorted(labels,key=labels.get):
            prediction=predict_hybrid(name,raw,labels,options,mode,weight)
            value=prediction.get('estimated_kmh') if prediction.get('available') else None
            row={'video':name+'.MP4','version':f'{mode}_weight_{weight}',
                'reference_kmh':labels[name],'estimated_kmh':value,
                'error_kmh':None if value is None else value-labels[name],
                'calibration_reused':prediction.get('calibration_reused',False),
                'own_reference_excluded':name not in prediction.get('reference_videos',[])
                    and name not in prediction.get('metric_scale_reference_videos',[])}
            assert row['own_reference_excluded'];group.append(row);rows.append(row)
        measured=metrics(group);saved=expected[f'{mode}_weight_{weight}']
        assert measured['estimated']==saved['estimated'] and measured['within_2_kmh']==saved['within_2_kmh']
        assert abs(measured['mae_kmh']-saved['mae_kmh'])<1e-5
    with (snapshot/'fusion_version_results.csv').open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    (snapshot/'fusion_version_results.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
    breakdown={key:metrics([r for r in selected if r['calibration_reused']==value])
               for key,value in [('reference_reused',True),('new_geometry',False)]}
    (snapshot/'calibration_path_metrics.json').write_text(json.dumps(breakdown,indent=2),encoding='utf-8')
    print('Exported',len(rows),'fixed-configuration video results; summary metrics agree.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',default=str(Path(__file__).parent/'output/calibration_comparison'))
    export(parser.parse_args().snapshot)
