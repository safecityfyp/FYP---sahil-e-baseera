"""Package the second research round, individual tests and paired output videos."""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parent
folder=ROOT/'comparison_report_notebook';folder.mkdir(exist_ok=True)
names=['calibrate_speed.py','benchmark_speed.py','reference_calibration.py','calibration_candidates.py',
    'learned_calibration.py','flow_calibration.py','refine_flow.py','lens_calibration.py',
    'longitudinal_calibration.py','scene_registration.py','refinement_inference.py',
    'calibration_comparison.py','render_comparison.py','test_calibration_candidates.py']
sources={name:(ROOT/name).read_text(encoding='utf-8') for name in names}
historical=json.loads((ROOT/'output/mercedes_validation/results.json').read_text())
cells=[{'cell_type':'markdown','metadata':{},'source':'''# Calibration refinements and individual video tests

Consumes the completed first GPU comparison. Runs additional speed-blind methods,
then evaluates each video with its own reference excluded from calibration and selection.
The reference library uses other labelled cruise-control passes. All clips were
previously inspected, so the report describes development cross-validation.
Writes every version's result and separate calibration/speed videos for all 30 clips.
'''},{'cell_type':'code','metadata':{},'execution_count':None,'outputs':[],'source':
'from pathlib import Path\nimport json,subprocess,sys\nsources='+repr(sources)+'\nhistorical='+repr(historical)+'''
root=Path('/kaggle/working/pipeline');root.mkdir(exist_ok=True)
for name,source in sources.items():(root/name).write_text(source,encoding='utf-8')
old=Path('/kaggle/working/historical_results.json');old.write_text(json.dumps(historical),encoding='utf-8')
subprocess.check_call([sys.executable,'-m','unittest','test_calibration_candidates','-v'],cwd=root)
input_root=Path('/kaggle/input')
observations=[p.parent.parent for p in input_root.rglob('observations.json') if p.parent.name=='MercedesAMG550_30']
first=[p.parent.parent for p in input_root.rglob('mask_features.json') if p.parent.name=='MercedesAMG550_30']
videos=list(input_root.rglob('MercedesAMG550_30.MP4'))
assert len(observations)==len(first)==len(videos)==1,(observations,first,videos)
second=Path('/kaggle/working/calibration_refinement')
subprocess.check_call([sys.executable,str(root/'refinement_inference.py'),'--inference-dir',str(observations[0]),
    '--video-dir',str(videos[0].parent),'--previous',str(first[0]),'--output',str(second)])
subprocess.check_call([sys.executable,str(root/'calibration_comparison.py'),'--inference-dir',str(observations[0]),
    '--first-round',str(first[0]),'--second-round',str(second),'--video-dir',str(videos[0].parent),
    '--historical-results',str(old),'--output','/kaggle/working/calibration_comparison','--archive-inputs'])
'''},{'cell_type':'code','metadata':{},'execution_count':None,'outputs':[],'source':'''from IPython.display import display,Markdown,Video,Image
import pandas as pd
out=Path('/kaggle/working/calibration_comparison')
display(Markdown((out/'README.md').read_text()))
display(pd.read_csv(out/'results.csv'))
display(Image(filename=str(out/'errors.jpg')))
for speed in [30,50,78,100]:
    for name in ['calibration.mp4','speed.mp4']:
        display(Video(str(out/'videos'/f'MercedesAMG550_{speed}'/name),embed=True,width=1100))
'''}]
for index,cell in enumerate(cells):cell['id']=f'calibration-report-{index:02d}'
book={'cells':cells,'metadata':{'kernelspec':{'name':'python3','display_name':'Python 3','language':'python'},
    'language_info':{'name':'python'}},'nbformat':4,'nbformat_minor':5}
(folder/'calibration_refinement_report.ipynb').write_text(json.dumps(book,indent=2),encoding='utf-8')
meta={'id':'hayyanfaisal/fyp-calibration-refinement-report','title':'FYP Calibration Refinement Report',
    'code_file':'calibration_refinement_report.ipynb','language':'python','kernel_type':'notebook','is_private':True,
    'enable_gpu':False,'enable_internet':False,'dataset_sources':['hayyanfaisal/fyp-mercedes-amg550-speed-validation'],
    'kernel_sources':['hayyanfaisal/fyp-mercedes-speed-validation','hayyanfaisal/fyp-per-video-calibration-method-comparison'],
    'competition_sources':[]}
(folder/'kernel-metadata.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
print('Built private calibration-refinement report notebook.')
