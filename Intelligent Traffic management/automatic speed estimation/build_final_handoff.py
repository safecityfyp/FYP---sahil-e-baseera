"""Assemble the user-facing code, actual weights, mappings and screenshot evidence ZIP."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import subprocess
import zipfile
from download_models import download

ROOT=Path(__file__).resolve().parent


def build(destination):
    destination=Path(destination)
    package=destination/'FYP_Speed_Calibration_Final'
    package.mkdir(parents=True,exist_ok=True)
    verified=download(ROOT/'models',verify_only=True)
    files=[]
    def copy(source,relative=None):
        target=package/(relative or source.relative_to(ROOT))
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source,target)
        files.append(target)
    # All top-level feature Python modules, plus dynamically invoked notebook sources.
    for source in sorted(ROOT.glob('*.py')):
        copy(source)
    for folder in ['notebook','geometry_notebook']:
        for source in sorted((ROOT/folder).glob('*.py')):
            copy(source)
    for name in ['requirements.txt','requirements-inference.txt','requirements-kaggle.txt',
                 'model_manifest.json','MODEL_NOTICES.md','FINAL_FILES.md','LLM_CALIBRATION_PROMPT.md',
                 'cctv_camera_profiles.json','cctv_method.md','calibration_methods.md']:
        copy(ROOT/name)
    copy(ROOT/'FINAL_FILES.md',Path('START_HERE.md'))
    copy(ROOT/'LICENSES/AGPL-3.0.txt')
    for model in verified:
        copy(ROOT/'models'/model['filename'])
    copy(ROOT/'models/verified_models.json')
    for camera in ['commercial_ii_01','k_block_st20']:
        copy(ROOT/f'output/cctv_20261009/{camera}/calibration/calibration.json',
             Path('saved_calibrations')/(camera+'.json'))
    for source in sorted((ROOT/'output/vision_assisted_trial').rglob('*')):
        if source.is_file() and source.suffix.lower() in {'.json','.csv','.md','.jpg','.png'}:
            copy(source)
    # Minimal historic reference tables for the standalone comparison command.
    for name in ['output/calibration_comparison/results.csv','output/kia_validation/results.csv']:
        copy(ROOT/name)
    # Selected saved detections allow re-extraction of the image sheets when source clips exist.
    for case in json.loads((ROOT/'output/vision_assisted_trial/evaluation_sources.json').read_text()):
        for name in ['tracks.json','geometry_run_report.json']:
            copy(ROOT/case['measurement_directory']/name)
    version=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    dirty=bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip())
    manifest=dict(repository='https://github.com/safecityfyp/FYP---sahil-e-baseera',
        branch='feature/automatic-speed-estimation',source_commit=version,
        source_checkout_has_uncommitted_changes=dirty,models=verified,
        no_video_files=True,no_credentials=True,
        files=[dict(path=str(p.relative_to(package)).replace('\\','/'),bytes=p.stat().st_size,
                    sha256=hashlib.file_digest(p.open('rb'),'sha256').hexdigest()) for p in sorted(files)])
    (package/'PACKAGE_MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
    archive=destination/'FYP_Speed_Calibration_Final.zip'
    # Only the files in this build manifest enter the archive; no ambient user files.
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=4) as stream:
        for path in sorted(files)+[package/'PACKAGE_MANIFEST.json']:
            stream.write(path,Path(package.name)/path.relative_to(package))
    with zipfile.ZipFile(archive) as stream:
        if stream.testzip() is not None:
            raise ValueError('ZIP CRC verification failed')
        forbidden=[n for n in stream.namelist() if Path(n).suffix.lower() in {'.mp4','.avi','.mov'}
                   or Path(n).name in {'.env','kaggle.json','access_token'}]
        if forbidden:
            raise ValueError('Unexpected media/credential file in archive')
    print(json.dumps(dict(folder=str(package),zip=str(archive),bytes=archive.stat().st_size,
                          files=len(files)+1,source_commit=version),indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--destination',required=True)
    a=p.parse_args()
    build(a.destination)
