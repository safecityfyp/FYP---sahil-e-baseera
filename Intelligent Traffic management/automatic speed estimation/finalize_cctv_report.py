"""Update repository indexes only after complete CCTV artifact verification."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent


def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def finalize():
    folder=ROOT/'output/cctv_20261009'
    verification=json.loads((folder/'verification.json').read_text());assert verification['passed']
    assert verification['total_source_frames']==187641
    summary=json.loads((folder/'experiment_summary.json').read_text())
    provenance=json.loads((folder/'provenance/kaggle_jobs.json').read_text())
    assert all(j['status']=='COMPLETE' and j['is_private'] for j in provenance['jobs'])
    # Added provenance can be catalogued without repeating unchanged video decoding.
    catalog_path=folder/'file_manifest.json';catalog=json.loads(catalog_path.read_text())
    for name,info in catalog['files'].items():
        assert sha(folder/name)==info['sha256'],f'Verified artifact changed: {name}'
    catalog['files']={p.relative_to(folder).as_posix():dict(bytes=p.stat().st_size,sha256=sha(p))
                      for p in sorted(folder.rglob('*')) if p.is_file() and p!=catalog_path}
    catalog_path.write_text(json.dumps(catalog,indent=2)+'\n',encoding='utf-8')
    registry=json.loads((ROOT/'experiments.json').read_text())
    new_jobs={}
    for job in provenance['jobs']:
        key=job['notebook'].split('/')[-1].removeprefix('fyp-').replace('-','_')
        entry=dict(notebook=job['notebook'],snapshot_version=job['snapshot_version'],
                   output_pattern=r'cctv_outputs/.*\.(json|gz|csv|jpg|yaml|mp4)$')
        if 'commercial-full' in job['notebook']:
            entry['purpose']='Initial full measurements and baseline fit. Final Commercial calibration/tables come from the refined CPU report.'
        elif 'refined-report' in job['notebook']:
            entry['purpose']='Final Commercial calibration, speed tables and 11 tests. Full videos rendered locally from these frozen tables.'
        new_jobs[key]=entry
    registry['experiments'].update(new_jobs)
    registry['cctv_october2026_dataset']=dict(videos=provenance['source_dataset'],private=True)
    (ROOT/'experiments.json').write_text(json.dumps(registry,indent=2)+'\n',encoding='utf-8')
    path=ROOT/'README.md';text=path.read_text(encoding='utf-8')
    start=text.index('## Long real CCTV:');end=text.index('## Kia Sportage:',start)
    section='''## Long real CCTV: Commercial II-01 and K Block St 20

The [completed two-camera report](output/cctv_20261009/README.md) processes **60 minutes at Commercial II-01** and **81 minutes 22 seconds at K Block St 20**. All **187,641 source frames** are covered by the speed outputs at their native 25/20 FPS. Each camera has a separate calibration video, and the complete speed recordings are supplied in **15 ordered ten-minute parts** on GitHub. Single full-length speed files are exported locally under the supplied CCTV folder's `output` directory.

Commercial uses 14 qualifying car tracks from 5 minutes on the left and 21 tracks from 10 minutes on the right. K Block uses 18 near-approach and 14 cross-street tracks from 5 minutes. The full recordings provide **306** and **355 car track IDs** with qualified local speed estimates. Track IDs can fragment; these are not verified unique-vehicle counts. Eleven mathematical/behavior checks passed, all exported video frames were decoded, and periodic camera-view checks passed.

See [the CCTV method and reproduction steps](cctv_method.md) and [pilot patterns and method comparisons](output/cctv_20261009/PATTERNS.md). The code supports turns and speed changes, separates road regions, excludes parked cars from calibration, and increases geometry sampling for K Block's brief vehicle passes. It selects among three calibration methods using held-out car geometry and car-subset stability. No Kia/Mercedes empirical speed correction is transferred. **CCTV speed accuracy remains unverified:** a nominal 4.5 × 1.8 m car supplies scale, and these recordings have no measured speed or road-distance reference. Decimal km/h and secondary sensitivity ranges are experimental.

'''
    path.write_text(text[:start]+section+text[end:],encoding='utf-8')
    path=ROOT/'output/README.md';text=path.read_text(encoding='utf-8')
    line='''The latest [two-camera CCTV report](cctv_20261009/README.md) adds complete **60-minute Commercial** and **81-minute K Block** recordings, with **17 calibration/speed MP4s**, full tables, source hashes and before/after pilot diagnostics. All **187,641 source frames** are covered, with 306 and 355 car track IDs receiving qualified experimental speeds. Multi-car calibration uses 5–10 minutes, and each camera has a separate calibration replay. **These CCTV speeds have no independently measured accuracy reference.**

'''
    if line not in text:
        title,rest=text.split('\n\n',1);text=title+'\n\n'+line+rest.replace('The latest [Kia Sportage report]','The [Kia Sportage report]',1)
    path.write_text(text,encoding='utf-8')
    path=ROOT/'cctv_method.md';text=path.read_text(encoding='utf-8')
    note='''
The [completed report](output/cctv_20261009/README.md) contains the full recordings, separate calibration replays, source measurements, method comparisons, pilot history and artifact verification. `build_cctv_report_notebook.py` independently reproduces the refined Commercial calibration and speed tables on Kaggle CPU with eleven tests. `cctv_render.py --encoder h264_nvenc` optionally uses a compatible local NVIDIA encoder; the default remains software H.264. Encoding does not change the frozen speed calculations.

Each region's selected track IDs and `calibration_end_s` define its fitting data. The saved calibration-footprint file covers the complete replay interval, which may include later observations from a region that froze earlier. Reproduction uses the per-region window/track filters in `cctv_calibration.py`.
'''
    if note not in text:text+=note
    path.write_text(text,encoding='utf-8')
    path=ROOT/'output/manifest.json';manifest=json.loads(path.read_text())
    manifest['kaggle_notebooks'].update(new_jobs)
    manifest['cctv_real_recordings']=dict(report='cctv_20261009/README.md',
        total_source_frames=verification['total_source_frames'],total_duration_s=summary['total_duration_s'],
        cameras=[{k:v for k,v in r.items() if k!='regions'} for r in summary['cameras']],
        all_output_frames_decoded=True,unit_tests_passed=True,accuracy_validated=False,
        known_speeds_used=False,source_dataset=provenance['source_dataset'],source_dataset_private=True)
    manifest['files']={p.relative_to(ROOT/'output').as_posix():dict(bytes=p.stat().st_size,sha256=sha(p))
                       for p in sorted((ROOT/'output').rglob('*')) if p.is_file() and p!=path}
    path.write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print('Updated feature/output READMEs, experiment registry and',len(manifest['files']),'artifact checksums.',flush=True)


if __name__=='__main__':finalize()
