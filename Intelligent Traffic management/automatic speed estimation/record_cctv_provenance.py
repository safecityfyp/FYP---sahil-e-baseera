"""Record private Kaggle job status and the exact source bundles actually submitted."""
import ast
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path

from kaggle.api.kaggle_api_extended import KaggleApi

ROOT=Path(__file__).resolve().parent
JOBS=[('fyp-cctv-commercial-pilot',1),('fyp-cctv-k-block-pilot',2),
      ('fyp-cctv-commercial-full',1),('fyp-cctv-k-block-full',1),
      ('fyp-cctv-commercial-refined-report',1)]


def record():
    api=KaggleApi();api.authenticate()
    temporary=ROOT/'outputs/cctv_20261009/executed_notebooks';temporary.mkdir(parents=True,exist_ok=True)
    target=ROOT/'output/cctv_20261009/provenance';target.mkdir(parents=True,exist_ok=True)
    rows=[]
    for slug,version in JOBS:
        status=api.kernels_status('hayyanfaisal/'+slug)
        assert str(status.status).endswith('COMPLETE'),f'{slug} has not completed'
        local=temporary/slug;local.mkdir(exist_ok=True)
        api.kernels_pull('hayyanfaisal/'+slug,str(local),metadata=True,quiet=True)
        metadata=json.loads((local/'kernel-metadata.json').read_text());assert metadata['is_private'] is True
        notebook_path=next(local.glob('*.ipynb'));notebook=json.loads(notebook_path.read_text())
        bundles=[]
        for cell in notebook['cells']:
            if cell['cell_type']!='code':continue
            source=cell['source'];source=''.join(source) if isinstance(source,list) else source
            for statement in ast.parse(source).body:
                if isinstance(statement,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='sources' for t in statement.targets):
                    bundles.append(ast.literal_eval(statement.value))
        assert len(bundles)==1
        source_dir=target/slug;source_dir.mkdir(exist_ok=True)
        hashes={}
        for name,source in bundles[0].items():
            assert Path(name).name==name
            data=source.encode('utf-8');(source_dir/name).write_bytes(data)
            hashes[name]=hashlib.sha256(data).hexdigest()
        rows.append(dict(notebook='hayyanfaisal/'+slug,url='https://www.kaggle.com/code/hayyanfaisal/'+slug,
                         snapshot_version=version,status='COMPLETE',is_private=True,executed_source_sha256=hashes))
    dataset_folder=temporary/'dataset';dataset_folder.mkdir(exist_ok=True)
    api.dataset_metadata('hayyanfaisal/fyp-cctv-october2026-two-cameras',path=str(dataset_folder))
    info=json.loads(next(dataset_folder.glob('*.json')).read_text())['info'];assert info['isPrivate'] is True
    report=dict(verified_at_utc=datetime.now(timezone.utc).isoformat(),
                source_dataset='hayyanfaisal/fyp-cctv-october2026-two-cameras',source_dataset_private=True,jobs=rows,
                note='Original low-rate K Block pilot v1 is retained in pilot_history with its runtime source hashes. '
                     'Current K Block pilot snapshot is v2. Commercial full v1 is the initial geometry-only mapping; '
                     'the refined CPU report supplies its final selected calibration and speed tables. '
                     'Commercial final videos are rendered locally from those frozen tables.')
    (target/'kaggle_jobs.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print('Verified private dataset and',len(rows),'complete private notebooks',flush=True)
    return report


if __name__=='__main__':record()
