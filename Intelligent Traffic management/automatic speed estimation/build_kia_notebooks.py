"""Build private, speed-blind Kia inference jobs with a predeclared development split."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEV = [31, 44, 55, 65, 77, 85, 96, 105]
NAMES = ['validation_inference.py', 'calibrate_speed.py', 'benchmark_speed.py',
         'calibration_candidates.py', 'flow_calibration.py', 'learned_calibration.py',
         'research_inference.py', 'refine_flow.py', 'lens_calibration.py',
         'refinement_inference.py']


def build():
    videos = sorted(Path(r'C:\Users\hayya\Videos\FYP\Speed\KiaSportage').glob('*.MP4'))
    plan = {
        'created_date': '2026-10-16', 'timezone': 'Asia/Karachi',
        'development_videos': [f'KiaSportage_{speed}' for speed in DEV],
        'reserved_test_videos': [p.stem for p in videos if int(p.stem.rsplit('_', 1)[1]) not in DEV],
        'split_rule': 'Eight speeds spaced across the range, chosen before Kia speed errors were calculated.',
        'reserved_protocol': 'Do not inspect reserved speed errors until improved configuration is frozen. '
                             'Speed-blind image measurements may be computed for all videos.',
        'reference': 'Filename speed in km/h; text annotation files are ignored.',
        'frozen_baseline': {'source_commit': '63c1b3923153cfaf92b1faba2292d62a8261015b',
                            'configuration': 'top3weighted_weight_0.75',
                            'reference_library': '30 Mercedes passes only; no Kia speed reference',
                            'configuration_sha256': hashlib.sha256((ROOT/'output/calibration_comparison/selected_configuration.json').read_bytes()).hexdigest()},
        'input_videos': [{'video': p.name, 'bytes': p.stat().st_size,
                          'sha256': hashlib.file_digest(p.open('rb'), 'sha256').hexdigest()} for p in videos],
        'scope': 'New vehicle on the same site. Reserved clips share one recording session; '
                 'this is not an independent camera/site benchmark.',
    }
    (ROOT/'kia_experiment_plan.json').write_text(json.dumps(plan, indent=2)+'\n', encoding='utf-8')
    sources = {name: (ROOT/name).read_text(encoding='utf-8') for name in NAMES}
    for split, selected in [('development', plan['development_videos']), ('reserved', plan['reserved_test_videos'])]:
        folder = ROOT/f'kia_{split}_notebook'; folder.mkdir(exist_ok=True)
        code = 'from pathlib import Path\nimport hashlib,json,subprocess,sys\nsources='+repr(sources)+'\nselected='+repr(selected)+'''
root=Path('/kaggle/working/pipeline');root.mkdir(exist_ok=True)
for name,source in sources.items():(root/name).write_text(source,encoding='utf-8')
subprocess.check_call([sys.executable,'-m','pip','install','-q','ultralytics==8.4.175','lap==0.5.13'])
videos=Path('/kaggle/working/selected_videos');videos.mkdir(exist_ok=True)
for name in selected:
    matches=list(Path('/kaggle/input').rglob(name+'.MP4'));assert len(matches)==1,(name,matches)
    (videos/(name+'.MP4')).symlink_to(matches[0])
out=Path('/kaggle/working/kia_measurements');out.mkdir(exist_ok=True)
def run(script,*args):subprocess.check_call([sys.executable,str(root/script),*map(str,args)])
run('validation_inference.py','--input',videos,'--output',out/'inference','--device','0')
run('research_inference.py','--inference-dir',out/'inference','--video-dir',videos,
    '--output',out/'round1','--runtime','/kaggle/working/runtime/naver_cctv','--device','cuda')
run('refinement_inference.py','--inference-dir',out/'inference','--video-dir',videos,
    '--previous',out/'round1','--output',out/'round2')
import torch,torchvision,cv2
report={'videos':selected,'reference_labels_read':False,'text_annotations_read':False,
        'torch':torch.__version__,'torchvision':torchvision.__version__,'opencv':cv2.__version__,
        'gpu':torch.cuda.get_device_name(),
        'source_sha256':{name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in sources}}
(out/'run_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print('All speed-blind measurements complete:',len(selected))
'''
        cells = [
            {'cell_type': 'markdown', 'metadata': {}, 'source': '# Kia Sportage '+split+' measurements\n'
             'Speed-blind detection, geometry, masks and optical flow. No speed errors are calculated here. '
             'Text annotations are not uploaded. Pinned NAVER model retains its CC BY-NC-SA 3.0 terms.'},
            {'cell_type': 'code', 'metadata': {}, 'execution_count': None, 'outputs': [], 'source': code},
        ]
        for i, cell in enumerate(cells):cell['id']=f'kia-{split}-{i}'
        notebook={'cells':cells,'metadata':{'kernelspec':{'name':'python3','display_name':'Python 3','language':'python'},
                                           'language_info':{'name':'python'}},'nbformat':4,'nbformat_minor':5}
        (folder/'kia_measurements.ipynb').write_text(json.dumps(notebook,indent=2),encoding='utf-8')
        meta={'id':f'hayyanfaisal/fyp-kia-{split}-calibration','title':f'FYP Kia {split.title()} Calibration',
              'code_file':'kia_measurements.ipynb','language':'python','kernel_type':'notebook','is_private':True,
              'enable_gpu':True,'enable_internet':True,
              'dataset_sources':['hayyanfaisal/fyp-kia-sportage-speed-validation'],
              'kernel_sources':[],'competition_sources':[]}
        (folder/'kernel-metadata.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
    print('Built private notebooks: 8 development clips and 25 reserved clips.')


if __name__=='__main__':build()
