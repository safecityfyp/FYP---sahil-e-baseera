"""Package the automatic workflow and inference adapters as a private GPU Kaggle notebook."""
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
folder = ROOT / 'workflow_notebook'
folder.mkdir(exist_ok=True)
names = ['workflow.py', 'camera_cache.py', 'calibrate_speed.py', 'render_speed.py',
         'notebook/baseline.py', 'geometry_notebook/extract_geometry.py']
sources = {name: (ROOT / name).read_text(encoding='utf-8') for name in names}
cells = []


def cell(kind, source):
    if kind == 'code':
        ast.parse(source)
    value = {'cell_type': kind, 'id': f'workflow-{len(cells):02d}', 'metadata': {}, 'source': source}
    if kind == 'code':
        value.update(execution_count=None, outputs=[])
    cells.append(value)


cell('markdown', '''# Automatic CCTV calibration and speed workflow

Check this camera view for usable saved calibration. If missing or invalid, infer vehicle geometry
and fit a local road mapping; otherwise reuse the mapping. Then estimate speeds and save outputs.
Fresh video intervals still need tracking and vehicle ground positions. Inference outputs are reused
only when the source hash, interval, configuration and artifact hashes match.

This notebook demonstrates a cold-cache run with fresh GPU inference, then a warm-cache run
that must skip calibration fitting. Calibration files are under `workflow_outputs/calibration_cache`.
Download that directory or supply persistent storage to retain calibration across Kaggle sessions.

**Experimental km/h only. Approximate car dimensions determine scale. Sensitivity ranges are not
confidence intervals; physical speed accuracy remains unvalidated.** Five sampled view checks
cannot guarantee that a camera stayed fixed between samples. This implementation targets the
A3 CH14 camera's two-carriageway geometry; other cameras need their road-region assumptions reviewed.

References: [Sochor et al.](https://arxiv.org/abs/1702.06451),
[UrbanOmniDetect](https://github.com/mkturkcan/urbanomnidetect).
''')
cell('code', '''import subprocess, sys
subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-q',
                       'ultralytics==8.4.175', 'lap==0.5.13'])
''')
cell('code', 'sources = ' + repr(sources) + '''
from pathlib import Path
root = Path('/kaggle/working/pipeline')
for name, source in sources.items():
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding='utf-8')
sys.path.insert(0, str(root))
import workflow
import json
from unittest.mock import patch
videos = list(Path('/kaggle/input').rglob('A3_ch14_20260822105146_20260822110347.mp4'))
assert len(videos) == 1, videos
arguments = ['--video', str(videos[0]), '--camera-id', 'A3-CH14',
             '--work-dir', '/kaggle/working/workflow_outputs', '--device', '0']
''')
cell('code', '''cold_code, cold_dir = workflow.run_workflow(workflow.parser().parse_args(arguments))
assert cold_code == 0, (cold_dir / 'workflow_report.json').read_text()
cold = json.loads((cold_dir / 'workflow_report.json').read_text())
assert cold['calibration_lookup']['status'] == 'miss'
assert any(s['action'] == 'model_inference' for s in cold['stages'])
with patch.object(workflow.speed, 'fit_road_mappings', side_effect=AssertionError('Warm run refitted calibration')):
    warm_code, warm_dir = workflow.run_workflow(workflow.parser().parse_args(arguments + ['--no-render']))
assert warm_code == 0, (warm_dir / 'workflow_report.json').read_text()
warm = json.loads((warm_dir / 'workflow_report.json').read_text())
assert warm['calibration_lookup']['status'] == 'hit'
assert cold['qualified_track_ids'] == warm['qualified_track_ids']
assert (cold_dir / 'speed/vehicle_speed_estimates.json').read_text() == (warm_dir / 'speed/vehicle_speed_estimates.json').read_text()
verification = {'cold_run': cold_dir.name, 'warm_run': warm_dir.name,
    'cold_cache_calibrated': True, 'fresh_gpu_inference_executed': True,
    'warm_cache_reused_without_fitting': True, 'qualified_results_identical': True,
    'qualified_track_ids': warm['qualified_track_ids'], 'accuracy_validated': False}
Path('/kaggle/working/workflow_verification.json').write_text(json.dumps(verification, indent=2))
print(json.dumps(verification, indent=2))
''')
cell('code', '''from IPython.display import display, Image, Video
import pandas as pd
display(pd.read_csv(cold_dir / 'speed/qualified_experimental_speeds.csv'))
for name in ['road_mapping.jpg', 'speed_sensitivity.jpg']:
    display(Image(filename=str(cold_dir / 'speed' / name), width=1100))
display(Video(str(cold_dir / 'speed/calibration_preview.mp4'), embed=True, width=1100))
display(Video(str(cold_dir / 'speed/experimental_speed_preview.mp4'), embed=True, width=1100))
''')
notebook = {'cells': cells, 'metadata': {'kernelspec': {'display_name': 'Python 3', 'language': 'python', 'name': 'python3'},
             'language_info': {'name': 'python'}}, 'nbformat': 4, 'nbformat_minor': 5}
(folder / 'automatic_workflow.ipynb').write_text(json.dumps(notebook, indent=2), encoding='utf-8')
metadata = {'id': 'hayyanfaisal/fyp-cctv-camera-calibration-workflow',
    'title': 'FYP CCTV Camera Calibration Workflow', 'code_file': 'automatic_workflow.ipynb',
    'language': 'python', 'kernel_type': 'notebook', 'is_private': True,
    'enable_gpu': True, 'enable_internet': True,
    'dataset_sources': ['hayyanfaisal/fyp-cctv-a3-ch14-speed-estimation'],
    'kernel_sources': [], 'competition_sources': []}
(folder / 'kernel-metadata.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
print('Packaged automatic GPU workflow notebook:', folder)
