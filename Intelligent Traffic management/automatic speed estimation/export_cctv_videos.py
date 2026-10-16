"""Export one complete speed video and one calibration video per camera locally."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT=Path(__file__).resolve().parent


def export(report,destination):
    report=Path(report).resolve();destination=Path(destination).resolve();destination.mkdir(parents=True,exist_ok=True)
    summary=json.loads((report/'experiment_summary.json').read_text());exports=[]
    temporary=ROOT/'outputs/cctv_20261009/concat';temporary.mkdir(parents=True,exist_ok=True)
    for item in summary['cameras']:
        camera=item['camera_id'];target=destination/camera;target.mkdir(exist_ok=True)
        assert target.resolve().is_relative_to(destination)
        source=report/camera/'videos';parts=sorted(source.glob('speed_*.mp4'));assert parts
        concat=temporary/(camera+'.txt')
        concat.write_text(''.join("file '"+p.as_posix().replace("'","'\\''")+"'\n" for p in parts),encoding='utf-8')
        full=target/'speed_estimation_full.mp4'
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','concat','-safe','0','-i',str(concat),
                        '-c','copy','-movflags','+faststart',str(full)],check=True)
        shutil.copy2(source/'calibration.mp4',target/'calibration.mp4')
        probe=subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=nb_frames,r_frame_rate,duration',
                              '-of','json',str(full)],capture_output=True,text=True,check=True)
        stream=json.loads(probe.stdout)['streams'][0]
        assert int(stream['nb_frames'])==item['source_frames']
        assert abs(float(stream['duration'])-item['duration_s'])<.1
        with full.open('rb') as handle:sha=hashlib.file_digest(handle,'sha256').hexdigest()
        exports.append(dict(camera_id=camera,full_speed_file=camera+'/'+full.name,source_frames=item['source_frames'],
                            duration_s=float(stream['duration']),sha256=sha,bytes=full.stat().st_size,
                            calibration_file=camera+'/calibration.mp4'))
        (target/'README.md').write_text(f'''# {item['display_name']}

- `speed_estimation_full.mp4`: the entire {item['duration_s']/60:.2f}-minute recording, {item['source_frames']:,} frames at {item['source_fps']:g} FPS.
- `calibration.mp4`: separate replay of the selected initial calibration interval.

Decimal car speeds are experimental. The metre scale comes from assumed car dimensions; no independently measured speed reference is available. Grey objects have no qualified speed. The smaller secondary range is a calibration sensitivity test, not a confidence interval.

Full tables, method comparisons and ordered video segments are on the `feature/automatic-speed-estimation` branch, under `Intelligent Traffic management/automatic speed estimation/output/cctv_20261009/{camera}/`.
''',encoding='utf-8')
    (destination/'export_manifest.json').write_text(json.dumps(dict(exports=exports),indent=2)+'\n',encoding='utf-8')
    (report/'local_exports.json').write_text(json.dumps(dict(exports=exports,source_audio_included=False),indent=2)+'\n',encoding='utf-8')
    print('Exported',len(exports),'full speed videos and',len(exports),'calibration videos to',destination,flush=True)
    return exports


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--report',default=str(ROOT/'output/cctv_20261009'))
    p.add_argument('--destination',required=True);a=p.parse_args();export(a.report,a.destination)
