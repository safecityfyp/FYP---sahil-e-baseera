"""Package independent per-video calibration candidates for a private Kaggle GPU run."""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parent
folder=ROOT/'comparison_notebook';folder.mkdir(exist_ok=True)
names=['calibrate_speed.py','benchmark_speed.py','calibration_candidates.py','flow_calibration.py',
       'learned_calibration.py','research_inference.py']
sources={name:(ROOT/name).read_text(encoding='utf-8') for name in names}
cells=[{'cell_type':'markdown','metadata':{},'source':'''# Per-video calibration method comparison

Each of the 30 clips is calibrated independently using its own imagery.
The inference stage does not read reference speeds or annotation files.
Methods: temporal projective delay, rigid 3D bundle with/without distortion,
released ICCV 2021 learned mask calibration, an ensemble version,
learned calibration with checked optical flow, and vehicle-envelope bundle fits.
The upstream NAVER code/model retain CC BY-NC-SA 3.0 terms and are downloaded at a pinned revision.
These are research/development reruns of previously inspected clips, not fresh independent validation.
'''}, {'cell_type':'code','metadata':{},'execution_count':None,'outputs':[],'source':
'from pathlib import Path\nimport subprocess,sys\nsources='+repr(sources)+'''
root=Path('/kaggle/working/pipeline');root.mkdir(exist_ok=True)
for name,source in sources.items():(root/name).write_text(source,encoding='utf-8')
input_root=Path('/kaggle/input')
matches=[p.parent.parent for p in input_root.rglob('observations.json') if p.parent.name=='MercedesAMG550_30']
assert len(matches)==1,matches
assert len(list(matches[0].glob('*/observations.json')))==30
videos=list(input_root.rglob('MercedesAMG550_30.MP4'));assert len(videos)==1,videos
subprocess.check_call([sys.executable,str(root/'research_inference.py'),'--inference-dir',str(matches[0]),
    '--video-dir',str(videos[0].parent),'--output','/kaggle/working/calibration_comparison_inference',
    '--runtime','/kaggle/working/runtime/naver_cctv','--device','cuda'])
'''}]
for i,cell in enumerate(cells):cell['id']=f'compare-{i:02d}'
book={'cells':cells,'metadata':{'kernelspec':{'name':'python3','display_name':'Python 3','language':'python'},
    'language_info':{'name':'python'}},'nbformat':4,'nbformat_minor':5}
(folder/'calibration_comparison.ipynb').write_text(json.dumps(book,indent=2),encoding='utf-8')
meta={'id':'hayyanfaisal/fyp-per-video-calibration-method-comparison','title':'FYP Per Video Calibration Method Comparison',
    'code_file':'calibration_comparison.ipynb','language':'python','kernel_type':'notebook','is_private':True,
    'enable_gpu':True,'enable_internet':True,'dataset_sources':['hayyanfaisal/fyp-mercedes-amg550-speed-validation'],
    'kernel_sources':['hayyanfaisal/fyp-mercedes-speed-validation'],'competition_sources':[]}
(folder/'kernel-metadata.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
print('Built private method comparison notebook.')
