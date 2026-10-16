"""Build the private CPU reproduction/report job after local reserved evaluation."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
NAMES=['calibrate_speed.py','benchmark_speed.py','reference_calibration.py','calibration_candidates.py',
       'flow_calibration.py','refine_flow.py','longitudinal_calibration.py','scene_registration.py',
       'calibration_comparison.py','shared_camera_calibration.py','vehicle_geometry_refinement.py',
       'kia_validation.py','render_comparison.py','render_cross_vehicle.py','publish_kia_report.py',
       'test_shared_camera_calibration.py','test_calibration_candidates.py','lens_calibration.py']


def build():
    folder=ROOT/'kia_report_notebook';folder.mkdir(exist_ok=True)
    sources={name:(ROOT/name).read_text(encoding='utf-8') for name in NAMES}
    plan=json.loads((ROOT/'kia_experiment_plan.json').read_text())
    configuration=json.loads((ROOT/'kia_calibration_configuration.json').read_text())
    code='from pathlib import Path\nimport json,subprocess,sys,shutil,hashlib\nsources='+repr(sources)+'\nplan='+repr(plan)+'\nconfiguration='+repr(configuration)+'''
root=Path('/kaggle/working/pipeline');root.mkdir(exist_ok=True)
for name,source in sources.items():(root/name).write_text(source,encoding='utf-8')
def write(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,indent=2),encoding='utf-8')
write(root/'kia_experiment_plan.json',plan);write(root/'kia_calibration_configuration.json',configuration)
input_root=Path('/kaggle/input')
def unique(pattern):
    values=list(input_root.rglob(pattern));assert len(values)==1,(pattern,values);return values[0]
mercedes=unique('calibration_comparison/raw_predictions.json').parent
old_inference=unique('validation_inference/MercedesAMG550_30/observations.json').parent.parent
(root/'output').mkdir(exist_ok=True)
(root/'output/calibration_comparison').symlink_to(mercedes,target_is_directory=True)
(root/'output/mercedes_validation').mkdir(exist_ok=True)
(root/'output/mercedes_validation/inference').symlink_to(old_inference,target_is_directory=True)
cache=unique('cache_manifest.json').parent
work=Path('/kaggle/working/evaluation');work.mkdir(exist_ok=True)
measurements={}
for phase,first in [('development','KiaSportage_31'),('reserved','KiaSportage_33')]:
    original=unique('kia_measurements/inference/'+first+'/observations.json').parent.parent.parent
    target=work/('measurements_'+phase);target.mkdir(exist_ok=True)
    shutil.copytree(original/'inference',target/'inference',ignore=shutil.ignore_patterns('geometry_*.jpg'))
    for directory in ['round1','round2']:shutil.copytree(original/directory,target/directory)
    shutil.copytree(cache/'geometry_refinement'/phase,target/'geometry_refinement')
    shutil.copytree(cache/(phase+'_evaluation'),work/(phase+'_evaluation'))
    measurements[phase]=target
def run(script,*args):subprocess.check_call([sys.executable,str(root/script),*map(str,args)],cwd=root)
subprocess.check_call([sys.executable,'-m','unittest','test_shared_camera_calibration','test_calibration_candidates','-v'],cwd=root)
run('kia_validation.py','--phase','development','--development-measurements',measurements['development'],
    '--output',work/'development_evaluation','--configuration',work/'recomputed_configuration.json')
recomputed=json.loads((work/'recomputed_configuration.json').read_text())
for key in ['selected_method','vehicle_metric_scales','reference_measurement_sha256','source_sha256']:
    assert recomputed[key]==configuration[key],key
run('kia_validation.py','--phase','reserved','--development-measurements',measurements['development'],
    '--reserved-measurements',measurements['reserved'],'--output',work/'reserved_evaluation',
    '--configuration',root/'kia_calibration_configuration.json')
max_difference=0
for phase in ['development','reserved']:
    before=json.loads((cache/(phase+'_evaluation')/'predictions.json').read_text())
    after=json.loads((work/(phase+'_evaluation')/'predictions.json').read_text())
    for name in before:
        for method in ['frozen_mercedes_baseline',configuration['selected_method']]:
            a=before[name][method].get('estimated_kmh');b=after[name][method].get('estimated_kmh')
            if a is not None and b is not None:max_difference=max(max_difference,abs(a-b))
assert max_difference<.001,max_difference
out=Path('/kaggle/working/kia_validation')
video_dir=unique('KiaSportage_31.MP4').parent
for item in plan['input_videos']:
    with (video_dir/item['video']).open('rb') as stream:
        assert hashlib.file_digest(stream,'sha256').hexdigest()==item['sha256'],item['video']
run('publish_kia_report.py','--development-evaluation',work/'development_evaluation',
    '--reserved-evaluation',work/'reserved_evaluation','--development-measurements',measurements['development'],
    '--reserved-measurements',measurements['reserved'],'--configuration',root/'kia_calibration_configuration.json',
    '--output',out,'--video-dir',video_dir,'--mercedes-comparison',cache/'mercedes_regression')
shutil.copytree(cache/'development_initial',out/'development_initial')
write(out/'reproduction_verification.json',{'maximum_local_vs_kaggle_difference_kmh':max_difference,
      'fixed_registration_caches_used':True,'configuration_frozen_before_reserved_errors':True,
      'all_33_input_video_hashes_match_original_plan':True,
      '12_mathematical_and_exclusion_tests_passed':True})
write(out/'runtime.json',{'python':sys.version,'source_sha256':{
    name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in sources}})
assert len(list((out/'videos').glob('*/calibration.mp4')))==33
assert len(list((out/'videos').glob('*/speed.mp4')))==33
print('Private Kia reproduction and all 66 videos completed.')
'''
    cells=[{'cell_type':'markdown','metadata':{},'source':
            '# Kia Sportage: reserved tests and paired videos\n'
            'Reproduces frozen local evaluation with saved speed-blind measurements and registration caches. '
            'Eight development references; 25 reserved tests. No test reference is used by calibration. '
            'Renders 33 calibration and 33 speed videos. Vehicle-template scale is reference-assisted.'},
           {'cell_type':'code','metadata':{},'execution_count':None,'outputs':[],'source':code}]
    for i,cell in enumerate(cells):cell['id']=f'kia-report-{i}'
    notebook={'cells':cells,'metadata':{'kernelspec':{'name':'python3','display_name':'Python 3','language':'python'},
                                      'language_info':{'name':'python'}},'nbformat':4,'nbformat_minor':5}
    (folder/'kia_report.ipynb').write_text(json.dumps(notebook,indent=2),encoding='utf-8')
    meta={'id':'hayyanfaisal/fyp-kia-calibration-validation-report','title':'FYP Kia Calibration Validation Report',
          'code_file':'kia_report.ipynb','language':'python','kernel_type':'notebook','is_private':True,
          'enable_gpu':False,'enable_internet':False,
          'dataset_sources':['hayyanfaisal/fyp-kia-sportage-speed-validation','hayyanfaisal/fyp-kia-calibration-evaluation-cache'],
          'kernel_sources':['hayyanfaisal/fyp-kia-development-calibration','hayyanfaisal/fyp-kia-reserved-calibration',
                            'hayyanfaisal/fyp-calibration-refinement-report','hayyanfaisal/fyp-mercedes-speed-validation'],
          'competition_sources':[]}
    (folder/'kernel-metadata.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
    print('Built private Kia reproduction and video report notebook.')


if __name__=='__main__':build()
