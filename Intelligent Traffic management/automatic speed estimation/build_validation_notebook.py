"""Build a private Kaggle notebook for speed-blind inference on the validation videos."""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parent
folder=ROOT/'validation_notebook';folder.mkdir(exist_ok=True)
source=(ROOT/'validation_inference.py').read_text(encoding='utf-8')
cells=[{'cell_type':'markdown','source':'# Mercedes constant-speed validation: speed-blind inference\nReference speeds and text labels are not used by the detector or geometry model.','metadata':{}},
       {'cell_type':'code','source':"import subprocess,sys\nsubprocess.check_call([sys.executable,'-m','pip','install','-q','ultralytics==8.4.175','lap==0.5.13'])",'metadata':{},'outputs':[],'execution_count':None},
       {'cell_type':'code','source':"from pathlib import Path\nsource="+repr(source)+"\nPath('/kaggle/working/validation_inference.py').write_text(source)\nsubprocess.check_call([sys.executable,'/kaggle/working/validation_inference.py','--input','/kaggle/input','--output','/kaggle/working/validation_inference','--device','0'])",'metadata':{},'outputs':[],'execution_count':None}]
for i,cell in enumerate(cells):cell['id']=f'validation-{i:02}'
notebook={'cells':cells,'metadata':{'kernelspec':{'display_name':'Python 3','language':'python','name':'python3'},'language_info':{'name':'python'}},'nbformat':4,'nbformat_minor':5}
(folder/'validation_inference.ipynb').write_text(json.dumps(notebook,indent=2),encoding='utf-8')
metadata={'id':'hayyanfaisal/fyp-mercedes-speed-validation','title':'FYP Mercedes Speed Validation','code_file':'validation_inference.ipynb','language':'python','kernel_type':'notebook','is_private':True,'enable_gpu':True,'enable_internet':True,'dataset_sources':['hayyanfaisal/fyp-mercedes-amg550-speed-validation'],'kernel_sources':[],'competition_sources':[]}
(folder/'kernel-metadata.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
