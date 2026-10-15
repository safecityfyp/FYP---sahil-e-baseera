"""Package frozen-calibration evaluation and paired video rendering as a private CPU Kaggle notebook."""
from pathlib import Path
import json

ROOT=Path(__file__).resolve().parent
folder=ROOT/'validation_report_notebook';folder.mkdir(exist_ok=True)
names=['calibrate_speed.py','camera_cache.py','benchmark_speed.py','reference_calibration.py','validation_experiment.py']
sources={name:(ROOT/name).read_text(encoding='utf-8') for name in names}
calibration=json.loads((ROOT/'output/mercedes_validation/pilot_frozen_calibration.json').read_text())
cells=[{'cell_type':'markdown','metadata':{},'source':'''# Mercedes validation: frozen calibration, held-out report and paired videos

The calibration was developed using only the 30, 60 and 100 km/h pilot clips.
The other 27 filenames supply evaluation references only after prediction.
Text label files are ignored. No neural-network weights are fine-tuned here.
This CPU notebook consumes the completed speed-blind GPU inference notebook and the private source videos.
It writes a before/after report, per-clip errors and separate calibration/speed videos.
Cruise-control settings are reference values, not independent radar measurements.
'''},
{'cell_type':'code','metadata':{},'execution_count':None,'outputs':[],'source':
"from pathlib import Path\nimport json,subprocess,sys\nsources="+repr(sources)+"\ncalibration="+repr(calibration)+'''
root=Path('/kaggle/working/pipeline');root.mkdir(exist_ok=True)
for name,source in sources.items():(root/name).write_text(source,encoding='utf-8')
frozen=Path('/kaggle/working/frozen_pilot_calibration.json')
frozen.write_text(json.dumps(calibration),encoding='utf-8')
input_root=Path('/kaggle/input')
matches=[p.parent.parent for p in input_root.rglob('observations.json') if p.parent.name=='MercedesAMG550_30']
assert len(matches)==1,matches
inference=matches[0]
assert len(list(inference.glob('*/observations.json')))==30,'Wait for the full 30-clip GPU run to finish.'
videos=list(input_root.rglob('MercedesAMG550_30.MP4'));assert len(videos)==1,videos
subprocess.check_call([sys.executable,str(root/'validation_experiment.py'),
    '--inference-dir',str(inference),'--video-dir',str(videos[0].parent),
    '--calibration',str(frozen),'--output','/kaggle/working/mercedes_validation'])
'''},
{'cell_type':'code','metadata':{},'execution_count':None,'outputs':[],'source':'''from IPython.display import display,Image,Video,Markdown
import pandas as pd
out=Path('/kaggle/working/mercedes_validation')
display(Markdown((out/'README.md').read_text()))
display(pd.read_csv(out/'results.csv'))
display(Image(filename=str(out/'validation_errors.jpg'),width=1100))
for speed in [30,60,80,100]:
    for name in ['calibration.mp4','speed.mp4']:
        display(Video(str(out/'videos'/f'MercedesAMG550_{speed}'/name),embed=True,width=1100))
'''}]
for i,cell in enumerate(cells):cell['id']=f'report-{i:02d}'
notebook={'cells':cells,'metadata':{'kernelspec':{'display_name':'Python 3','language':'python','name':'python3'},'language_info':{'name':'python'}},'nbformat':4,'nbformat_minor':5}
(folder/'validation_report.ipynb').write_text(json.dumps(notebook,indent=2),encoding='utf-8')
metadata={'id':'hayyanfaisal/fyp-mercedes-calibration-validation-report','title':'FYP Mercedes Calibration Validation Report',
 'code_file':'validation_report.ipynb','language':'python','kernel_type':'notebook','is_private':True,
 'enable_gpu':False,'enable_internet':False,'dataset_sources':['hayyanfaisal/fyp-mercedes-amg550-speed-validation'],
 'kernel_sources':['hayyanfaisal/fyp-mercedes-speed-validation'],'competition_sources':[]}
(folder/'kernel-metadata.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
print('Built private CPU report notebook.')
