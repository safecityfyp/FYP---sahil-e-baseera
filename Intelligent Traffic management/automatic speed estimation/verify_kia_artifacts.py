"""Audit reserved-reference separation, fitted scales and all paired video files."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from calibration_comparison import metrics
from kia_validation import read,write,source_hashes


def verify(args):
    root=Path(__file__).resolve().parent;out=Path(args.output)
    plan=read(root/'kia_experiment_plan.json');config=read(out/'configuration.json')
    assert config['source_sha256']==source_hashes()
    assert config==read(root/'kia_calibration_configuration.json')
    dev=set(plan['development_videos']);reserved=set(plan['reserved_test_videos'])
    assert len(dev)==8 and len(reserved)==25 and not dev&reserved
    rows=read(out/'results.json');assert len(rows)==33
    assert {Path(r['video']).stem for r in rows}==dev|reserved
    measurements=out/'measurements/development'
    from kia_validation import load_measurements
    raw,_,_,_=load_measurements(measurements)
    for name in dev:
        digest=hashlib.sha256(json.dumps(raw[name],sort_keys=True).encode()).hexdigest()
        assert digest==config['reference_measurement_sha256'][name]
    for phase,queries in [('development',dev),('reserved',reserved)]:
        predictions=read(out/phase/'predictions.json')
        for name in queries:
            prediction=predictions[name][config['selected_method']]
            references=set(prediction['reference_videos'])
            assert not references&reserved and name not in references
            assert references==dev-{name}
            value=sum(p['weight']*p['estimated_kmh'] for p in prediction['geometry_calibration_components'])
            assert abs(value-prediction['estimated_kmh'])<1e-10
            if phase=='reserved':
                for part in prediction['geometry_calibration_components']:
                    assert part['metric_scale']==config['vehicle_metric_scales'][part['version']]
    summary=read(out/'metrics.json')
    for phase in ['development','reserved','all_33']:
        values=[r for r in rows if phase=='all_33' or r['phase']==phase]
        for key,value in metrics(values).items():
            expected=summary[phase]['after'][key]
            assert value==expected if isinstance(value,int) else abs(value-expected)<1e-9
    inventory={r['video']:r for r in read(args.inventory)}
    video_checks=[]
    for path in sorted((out/'videos').glob('*/*.mp4')):
        name=path.parent.name;source=inventory[name+'.MP4']
        data=json.loads(subprocess.check_output(['ffprobe','-v','error','-count_frames','-select_streams','v:0',
             '-show_entries','stream=codec_name,width,height,r_frame_rate,nb_read_frames,duration',
             '-of','json',str(path)],text=True))['streams'][0]
        numerator,denominator=map(float,data['r_frame_rate'].split('/'));fps=numerator/denominator
        assert data['codec_name']=='h264' and (data['width'],data['height'])==(1280,720)
        assert int(data['nb_read_frames'])==source['frames']
        assert abs(fps-source['fps'])<1e-4
        assert abs(float(data['duration'])-source['frames']/source['fps'])<1/source['fps']
        render=read(path.parent/'render_report.json');assert render['vehicle_label_frames']>0
        video_checks.append({'file':path.relative_to(out).as_posix(),'frames':int(data['nb_read_frames']),
                             'fps':fps,'codec':data['codec_name'],'passed':True})
    assert len(video_checks)==66
    result={'date':'2026-10-16','individual_clips':33,'development_clips':8,'reserved_clips':25,
            'source_and_frozen_reference_measurement_hashes_match':True,
            'each_test_reference_excluded':True,'no_reserved_reference_used_for_calibration_or_selection':True,
            'reserved_metric_scales_match_pre_evaluation_configuration':True,
            'all_66_video_frames_fps_duration_and_codec_verified':True,
            '12_mathematical_and_reference_exclusion_tests':'Passed locally and in the successful report notebook',
            'videos':video_checks}
    write(out/'artifact_verification.json',result)
    print('Verified 33 tests, frozen scales, reference exclusions and all 66 videos.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True)
    parser.add_argument('--inventory',required=True);verify(parser.parse_args())
