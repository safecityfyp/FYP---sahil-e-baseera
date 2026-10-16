"""Verify hashes, complete source coverage, videos and metric-label provenance."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np

from cctv_calibration import read_rows

ROOT=Path(__file__).resolve().parent


def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def probe_video(path):
    result=subprocess.run(['ffprobe','-v','error','-threads','1','-count_frames','-select_streams','v:0',
                           '-show_entries','stream=nb_frames,nb_read_frames,r_frame_rate,duration,width,height',
                           '-of','json',str(path)],capture_output=True,text=True,check=True)
    assert not result.stderr.strip(),f'Decoder reported errors in {path.name}'
    stream=json.loads(result.stdout)['streams'][0]
    assert int(stream['nb_frames'])==int(stream['nb_read_frames']),f'Incomplete decode: {path.name}'
    return stream


def verified_streams(paths,cache_path=None):
    """Reuse a prior complete decode only when the exact SHA-256 matches."""
    cache_path=Path(cache_path) if cache_path else None
    cache=json.loads(cache_path.read_text()) if cache_path and cache_path.exists() else {}
    hashes={path:digest(path) for path in paths}
    def fetch(path):return cache[hashes[path]] if hashes[path] in cache else probe_video(path)
    with ThreadPoolExecutor(max_workers=4) as pool:streams=list(pool.map(fetch,paths))
    if cache_path:
        for path,stream in zip(paths,streams):cache[hashes[path]]=stream
        cache_path.parent.mkdir(parents=True,exist_ok=True)
        cache_path.write_text(json.dumps(cache,indent=2)+'\n',encoding='utf-8')
    return streams


def verify(folder,source_dir=None,decode_cache=None):
    folder=Path(folder);summary=json.loads((folder/'experiment_summary.json').read_text())
    config=json.loads((ROOT/'cctv_camera_profiles.json').read_text());results=[]
    for item in summary['cameras']:
        camera=item['camera_id'];local=folder/camera;profile=config['cameras'][camera]
        if source_dir:
            assert digest(Path(source_dir)/profile['video'])==profile['sha256']
        cal=json.loads((local/'calibration/calibration.json').read_text())
        speed=json.loads((local/'speed/speed_report.json').read_text())
        manifest=json.loads((local/'videos/video_manifest.json').read_text())
        assert cal['source_sha256']==speed['source_sha256']==manifest['source_sha256']==profile['sha256']
        assert cal['all_regions_accepted'] and not cal['accuracy_validated'] and not speed['accuracy_validated']
        assert not cal['known_speeds_used'] and not cal['benchmark_vehicle_scales_used']
        assert speed['all_sampled_views_consistent'] and manifest['video_covers_entire_source']
        reports=[json.loads((local/'measurements'/part/'inference_report.json').read_text()) for part in ['pilot','remainder']]
        assert all(r['decode_complete'] and r['source_sha256']==profile['sha256'] for r in reports)
        assert reports[0]['start_s']==0 and reports[0]['stop_s']==reports[1]['start_s']
        assert abs(reports[1]['stop_s']-item['duration_s'])<.001
        assert reports[1]['frames_decoded']==item['source_frames']
        files=[];speed_frames=0;calibration_frames=0
        paths=sorted((local/'videos').glob('*.mp4'))
        decoded=verified_streams(paths,decode_cache)
        expected_sizes={r['file']:r['bytes'] for r in manifest['files']}
        for path,stream in zip(paths,decoded):
            assert path.stat().st_size<100*1024**2
            assert path.stat().st_size==expected_sizes[path.name]
            n,d=map(int,stream['r_frame_rate'].split('/'))
            assert abs(n/d-item['source_fps'])<1e-8 and [stream['width'],stream['height']]==[1280,720]
            frames=int(stream['nb_frames']);assert int(stream['nb_read_frames'])==frames
            assert abs(float(stream['duration'])-frames/item['source_fps'])<.051
            if path.stem.startswith('speed_'):speed_frames+=frames
            elif path.stem=='calibration':calibration_frames+=frames
            files.append(dict(file=path.relative_to(folder).as_posix(),frames=frames,bytes=path.stat().st_size,sha256=digest(path)))
        assert speed_frames==item['source_frames']==manifest['speed_rendered_frames']
        assert calibration_frames==int(round(cal['calibration_duration_s']*item['source_fps']))
        rows=read_rows(local/'speed','speeds.jsonl.gz')
        for r in rows:
            values=[r[k] for k in ['time_s','experimental_kmh','sensitivity_low_kmh','sensitivity_high_kmh','trajectory_rms_m']]
            assert np.isfinite(values).all() and 0<=r['time_s']<=item['duration_s']
            assert r['sensitivity_low_kmh']<=r['experimental_kmh']<=r['sensitivity_high_kmh']
            assert r['experimental_kmh']>=0 and r['trajectory_rms_m']<=.8
            assert abs(r['frame_index']/item['source_fps']-r['time_s'])<.15
            assert cal['regions'][r['region']]['accepted']
        assert len(rows)==speed['speed_counts']['accepted_speed_samples']
        assert len(set(r['track_id'] for r in rows))==speed['cars_with_speed_estimates']
        for name,mapping in cal['regions'].items():
            H=np.array(mapping['H_image_to_experimental_meters']);hull=np.array(mapping['support_hull_image'])
            assert np.isfinite(H).all() and abs(np.linalg.det(H))>1e-12
            den=np.c_[hull,np.ones(len(hull))]@H[2];assert not den.min()<=0<=den.max()
            assert len(mapping['track_ids'])>=config['minimum_cars_per_region']
        results.append(dict(camera_id=camera,source_frames=speed_frames,calibration_frames=calibration_frames,
                            speed_samples=len(rows),cars_with_speed=len(set(r['track_id'] for r in rows)),videos=files,
                            complete_coverage=True,all_output_frames_decoded=True,source_hash_checked=bool(source_dir),static_view_checks_passed=True))
    tests=subprocess.run([sys.executable,'-m','unittest','test_cctv','-v'],cwd=ROOT,capture_output=True,text=True)
    assert tests.returncode==0,tests.stdout+tests.stderr
    report=dict(passed=True,cameras=results,total_source_frames=sum(r['source_frames'] for r in results),
                unit_tests_passed=True,unit_test_output=tests.stdout+tests.stderr,
                scope='Mathematical, integrity and completeness verification. No ground-truth speed accuracy claim.',
                accuracy_validated=False)
    (folder/'verification.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    manifest={p.relative_to(folder).as_posix():dict(bytes=p.stat().st_size,sha256=digest(p))
              for p in sorted(folder.rglob('*')) if p.is_file() and p.name!='file_manifest.json'}
    (folder/'file_manifest.json').write_text(json.dumps(dict(files=manifest),indent=2)+'\n',encoding='utf-8')
    print('PASS:',len(results),'cameras,',report['total_source_frames'],'source frames,',sum(len(r['videos']) for r in results),'verified MP4s, all mathematical tests',flush=True)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--folder',default=str(ROOT/'output/cctv_20261009'))
    p.add_argument('--source-dir');p.add_argument('--decode-cache',help='Optional exact-SHA cache of earlier full video decoding checks')
    a=p.parse_args();verify(a.folder,a.source_dir,a.decode_cache)
