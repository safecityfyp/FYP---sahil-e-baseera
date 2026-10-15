"""Package the reviewed local calibration and renderer into a private CPU Kaggle notebook."""
from pathlib import Path
import ast
import json
ROOT=Path(__file__).resolve().parent
folder=ROOT/'speed_notebook';folder.mkdir(exist_ok=True)
files={name:(ROOT/name).read_text(encoding='utf-8') for name in ['calibrate_speed.py','render_speed.py']}
cells=[]

def markdown(text):cells.append({'cell_type':'markdown','metadata':{},'source':text})
def code(text):
    ast.parse(text)
    cells.append({'cell_type':'code','metadata':{},'execution_count':None,'outputs':[],'source':text})

markdown('''# FYP experimental automatic speed estimation

This CPU notebook consumes the completed private tracking and 3D-geometry experiments.
It fits a separate local road mapping for each carriageway from predicted vehicle ground footprints.
Approximate car-size priors establish a provisional scale: nominal length 4.5 m and width 1.8 m.
Sensitivity scenarios vary length from 3.2–5.2 m and width from 1.45–2.0 m, and vary the calibration track subset.

**All km/h values are experimental and unvalidated. Ranges are sensitivity envelopes, not confidence intervals.**
Predicted corners, approximate dimensions, road slope and lens distortion can introduce errors outside those ranges.
Only track segments passing geometric and temporal consistency screens receive speed labels.
These screens are not accuracy validation. Some tracks and road regions will have no speed.

This is an independent prototype using learned 3D footprints and dimension priors. It is not a reproduction
of Sochor et al.'s exact vehicle-model alignment, which requires make/model recognition and corresponding geometry.

References: [Sochor et al. 2017](https://arxiv.org/abs/1702.06451),
[UrbanOmniDetect — Turkcan, Gumaste and Kostic, CVPRW 2026](https://github.com/mkturkcan/urbanomnidetect).
''')
code('''from pathlib import Path
import os, json, subprocess, sys
from IPython.display import display, Image, Video
import pandas as pd
input_root=Path('/kaggle/input')
def unique(name):
    paths=list(input_root.rglob(name))
    assert len(paths)==1,(name,paths)
    return paths[0]
geometry=unique('geometry_run_report.json').parent
geometry_report=json.loads((geometry/'geometry_run_report.json').read_text())
assert geometry_report['model_sha256']=='9aa55280a5ef1c9d89c0acb5baeb974b90fbdf3c1deead1413b24d7af249226d', 'Unexpected geometry model version'
os.environ.update({'FYP_SPEED_ROOT':'/kaggle/working','FYP_GEOMETRY_DIR':str(geometry),
    'FYP_SPEED_OUTPUT':'/kaggle/working/speed_experiment',
    'FYP_BASELINE_TRACKS':str(unique('tracks.csv')),
    'FYP_SPEED_SOURCE':str(unique('A3_ch14_20260822105146_20260822110347.mp4'))})
print('Input geometry:',geometry_report['model_filename'])
print('No GPU inference is repeated by this notebook.')
''')
code('sources='+repr(files)+'''
for name,source in sources.items():
    Path('/kaggle/working',name).write_text(source,encoding='utf-8')
subprocess.check_call([sys.executable,'/kaggle/working/calibrate_speed.py'])
subprocess.check_call([sys.executable,'/kaggle/working/render_speed.py'])
''')
code('''output=Path('/kaggle/working/speed_experiment')
report=json.loads((output/'speed_run_report.json').read_text())
print(json.dumps(report,indent=2))
if (output/'experimental_speeds.csv').exists():
    speeds=pd.read_csv(output/'experimental_speeds.csv')
    display(speeds[['track_id','side','experimental_kmh','dimension_and_fit_sensitivity_low_kmh',
                    'dimension_and_fit_sensitivity_high_kmh','quality_passed','quality_reasons']])
for name in ['road_mapping.jpg','birdseye_trajectories.jpg','speed_sensitivity.jpg']:
    if (output/name).exists():display(Image(filename=str(output/name),width=1100))
display(Video(str(output/'calibration_preview.mp4'),embed=True,width=1100))
display(Video(str(output/'experimental_speed_preview.mp4'),embed=True,width=1100))
''')
for i,cell in enumerate(cells):cell['id']=f'speed-{i:02d}'
notebook={'cells':cells,'metadata':{'kernelspec':{'display_name':'Python 3','language':'python','name':'python3'},'language_info':{'name':'python'}},'nbformat':4,'nbformat_minor':5}
(folder/'experimental_speed.ipynb').write_text(json.dumps(notebook,indent=2),encoding='utf-8')
metadata={'id':'hayyanfaisal/fyp-cctv-experimental-speed-estimation','title':'FYP CCTV Experimental Speed Estimation',
 'code_file':'experimental_speed.ipynb','language':'python','kernel_type':'notebook',
 'is_private':True,'enable_gpu':False,'enable_internet':False,
 'dataset_sources':['hayyanfaisal/fyp-cctv-a3-ch14-speed-estimation'],
 'kernel_sources':['hayyanfaisal/fyp-cctv-vehicle-tracking-baseline','hayyanfaisal/fyp-cctv-automatic-vehicle-geometry'],
 'competition_sources':[]}
(folder/'kernel-metadata.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
print('Packaged CPU speed notebook:',folder)
