"""Build private staged CCTV jobs. Calibration and speed processing are separate."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent


def build(stage='pilot'):
    names=['cctv_inference.py','cctv_camera_profiles.json','validation_inference.py']
    if stage == 'full':
        names += ['calibrate_speed.py','cctv_calibration.py','cctv_speed.py','cctv_render.py','camera_cache.py']
    sources={name:(ROOT/name).read_text(encoding='utf-8') for name in names}
    config=json.loads(sources['cctv_camera_profiles.json'])
    for camera,profile in config['cameras'].items():
        short='commercial' if camera=='commercial_ii_01' else 'k-block'
        folder=ROOT/f'cctv_{short}_{stage}_notebook';folder.mkdir(exist_ok=True)
        code='from pathlib import Path\nimport hashlib,json,subprocess,sys\nsources='+repr(sources)+'\ncamera='+repr(camera)+'\nvideo_name='+repr(profile['video'])+'''
root=Path('/kaggle/working/pipeline');root.mkdir(exist_ok=True)
for name,source in sources.items():(root/name).write_text(source,encoding='utf-8')
subprocess.check_call([sys.executable,'-m','pip','install','-q','ultralytics==8.4.175','lap==0.5.13'])
videos=list(Path('/kaggle/input').rglob(video_name));assert len(videos)==1,(video_name,videos)
out=Path('/kaggle/working/cctv_outputs')/camera;out.mkdir(parents=True,exist_ok=True)
def run(script,*args):subprocess.check_call([sys.executable,str(root/script),*map(str,args)])
'''
        if stage=='pilot':
            code+="run('cctv_inference.py','--video',videos[0],'--output',out/'pilot','--camera',camera,'--duration',900)\n"
        else:
            code+='''
pilot_matches=list(Path('/kaggle/input').rglob(camera+'/pilot/inference_report.json'))
assert len(pilot_matches)==1,pilot_matches
pilot=pilot_matches[0].parent
run('cctv_calibration.py','--input',pilot,'--camera',camera,'--output',out/'calibration')
run('cctv_inference.py','--video',videos[0],'--output',out/'remainder','--camera',camera,'--resume-s',900)
run('cctv_speed.py','--inputs',pilot,out/'remainder','--calibration',out/'calibration/calibration.json','--output',out/'speed')
run('cctv_render.py','--video',videos[0],'--inputs',pilot,out/'remainder','--calibration',out/'calibration/calibration.json','--speed',out/'speed','--output',out/'videos')
'''
        code+='''
import torch,cv2,ultralytics
report={'camera_id':camera,'torch':torch.__version__,'opencv':cv2.__version__,
        'ultralytics':ultralytics.__version__,'gpu':torch.cuda.get_device_name(),
        'source_sha256':{name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in sources}}
(out/'runtime.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print('Job complete:',camera)
'''
        cells=[{'cell_type':'markdown','metadata':{},'source':f'# CCTV {profile["display_name"]}: {stage}\nPrivate CCTV processing. No known-speed reference or prior Kia/Mercedes correction is used.'},
               {'cell_type':'code','metadata':{},'execution_count':None,'outputs':[],'source':code}]
        for i,c in enumerate(cells):c['id']=f'cctv-{stage}-{i}'
        notebook=dict(cells=cells,metadata={'kernelspec':{'name':'python3','display_name':'Python 3','language':'python'},'language_info':{'name':'python'}},nbformat=4,nbformat_minor=5)
        (folder/'cctv.ipynb').write_text(json.dumps(notebook,indent=2)+'\n',encoding='utf-8')
        meta=dict(id=f'hayyanfaisal/fyp-cctv-{short}-{stage}',title=f'FYP CCTV {short.title()} {stage.title()}',code_file='cctv.ipynb',
                  language='python',kernel_type='notebook',is_private=True,enable_gpu=True,enable_internet=True,
                  dataset_sources=['hayyanfaisal/fyp-cctv-october2026-two-cameras'],competition_sources=[],
                  kernel_sources=[] if stage=='pilot' else [f'hayyanfaisal/fyp-cctv-{short}-pilot'])
        (folder/'kernel-metadata.json').write_text(json.dumps(meta,indent=2)+'\n',encoding='utf-8')
        print('Built',folder.name)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--stage',choices=['pilot','full'],default='pilot')
    build(p.parse_args().stage)
