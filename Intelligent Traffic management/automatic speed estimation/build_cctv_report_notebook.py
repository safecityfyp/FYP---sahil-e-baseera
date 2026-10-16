"""Build a private CPU reproduction of the refined Commercial calibration."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent


def build():
    names=['calibrate_speed.py','cctv_camera_profiles.json','cctv_calibration.py','cctv_speed.py',
           'cctv_render.py','camera_cache.py','test_cctv.py','test_calibration_math.py']
    sources={name:(ROOT/name).read_text(encoding='utf-8') for name in names}
    code='from pathlib import Path\nimport hashlib,json,subprocess,sys,shutil,platform\nsources='+repr(sources)+'''
root=Path('/kaggle/working/pipeline');root.mkdir(exist_ok=True)
for name,source in sources.items():(root/name).write_text(source,encoding='utf-8')
out=Path('/kaggle/working/cctv_outputs/commercial_ii_01');out.mkdir(parents=True,exist_ok=True)
pilot_matches=list(Path('/kaggle/input').rglob('commercial_ii_01/pilot/inference_report.json'))
remainder_matches=list(Path('/kaggle/input').rglob('commercial_ii_01/remainder/inference_report.json'))
assert len(pilot_matches)==len(remainder_matches)==1
pilot=pilot_matches[0].parent;remainder=remainder_matches[0].parent
videos=list(Path('/kaggle/input').rglob('NVR_ch6_main_20261009170002_20261009180000.mp4'));assert len(videos)==1
tests=subprocess.run([sys.executable,'-m','unittest','test_cctv','-v'],cwd=root,capture_output=True,text=True)
print(tests.stdout,tests.stderr,flush=True);assert tests.returncode==0
(out/'unit_tests.json').write_text(json.dumps({'passed':True,'command':'python -m unittest test_cctv -v',
                                             'output':tests.stdout+tests.stderr},indent=2))
def run(script,*args):subprocess.check_call([sys.executable,str(root/script),*map(str,args)])
run('cctv_calibration.py','--input',pilot,'--camera','commercial_ii_01','--output',out/'calibration')
run('cctv_speed.py','--inputs',pilot,remainder,'--calibration',out/'calibration/calibration.json','--output',out/'speed')
target=out/'remainder';target.mkdir(exist_ok=True)
for path in remainder.iterdir():
    if path.is_file() and path.suffix in ['.json','.gz','.yaml','.jpg']:shutil.copy2(path,target/path.name)
import cv2,numpy,scipy
report={'stage':'refined CPU calibration/speed reproduction; final videos rendered locally from these frozen tables','python':platform.python_version(),
        'opencv':cv2.__version__,'numpy':numpy.__version__,'scipy':scipy.__version__,'unit_tests_passed':True,
        'source_sha256':{name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in sources},
        'known_speeds_used':False,'accuracy_validated':False}
(out/'runtime.json').write_text(json.dumps(report,indent=2))
print('Refined Commercial report complete',flush=True)
'''
    cells=[dict(cell_type='markdown',metadata={},source='# Commercial II-01: refined full CCTV report\n'
                'CPU reproduction using immutable speed-blind GPU measurements. Tests, multi-car calibration and '
                'local speed estimation. Final videos are rendered locally from these frozen tables. No ground-truth speed is available.'),
           dict(cell_type='code',metadata={},execution_count=None,outputs=[],source=code)]
    for i,cell in enumerate(cells):cell['id']=f'cctv-refined-report-{i}'
    notebook=dict(cells=cells,metadata={'kernelspec':{'name':'python3','display_name':'Python 3','language':'python'},
                                       'language_info':{'name':'python'}},nbformat=4,nbformat_minor=5)
    folder=ROOT/'cctv_commercial_report_notebook';folder.mkdir(exist_ok=True)
    (folder/'cctv_report.ipynb').write_text(json.dumps(notebook,indent=2)+'\n',encoding='utf-8')
    meta=dict(id='hayyanfaisal/fyp-cctv-commercial-refined-report',title='FYP CCTV Commercial Refined Report',
              code_file='cctv_report.ipynb',language='python',kernel_type='notebook',is_private=True,
              enable_gpu=False,enable_internet=True,dataset_sources=['hayyanfaisal/fyp-cctv-october2026-two-cameras'],
              kernel_sources=['hayyanfaisal/fyp-cctv-commercial-pilot','hayyanfaisal/fyp-cctv-commercial-full'],competition_sources=[])
    (folder/'kernel-metadata.json').write_text(json.dumps(meta,indent=2)+'\n',encoding='utf-8')
    print('Built',folder.name)


if __name__=='__main__':build()
