"""Check saved camera calibration, calibrate when needed, then estimate experimental speeds."""
import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

import calibrate_speed as speed
from camera_cache import (CalibrationCache, file_sha256, canonical_hash, read_views,
                          stable_view, valid_calibration)

ROOT = Path(__file__).resolve().parent
INFERENCE_VERSION = 'yolo11s-1280-bytetrack-urban1920-v1'
GEOMETRY_SHA = '9aa55280a5ef1c9d89c0acb5baeb974b90fbdf3c1deead1413b24d7af249226d'
INPUT_FILES = ('tracking/tracks.csv', 'tracking/run_report.json',
               'geometry/observations.json', 'geometry/geometry_run_report.json')


def input_identity(video_sha, metadata):
    return {'source_sha256': video_sha,
            **{key: metadata[key] for key in ['width', 'height', 'fps', 'start_frame', 'end_frame']},
            'inference_version': INFERENCE_VERSION, 'geometry_model_sha256': GEOMETRY_SHA}


def write_input_manifest(directory, identity):
    directory = Path(directory)
    manifest = {'schema_version': 1, 'identity': identity,
                'files': {name: file_sha256(directory / name) for name in INPUT_FILES}}
    (directory / 'input_manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')


def verified_inputs(directory, identity):
    try:
        directory = Path(directory)
        manifest = json.loads((directory / 'input_manifest.json').read_text(encoding='utf-8'))
        if manifest['schema_version'] != 1 or manifest['identity'] != identity:
            return False
        if not all(file_sha256(directory / name) == manifest['files'][name] for name in INPUT_FILES):
            return False
        tracking = json.loads((directory / 'tracking/run_report.json').read_text())
        geometry = json.loads((directory / 'geometry/geometry_run_report.json').read_text())
        return (tracking['source_width'] == identity['width'] and tracking['source_height'] == identity['height']
                and tracking['source_fps'] == identity['fps']
                and tracking['processed_frames'] == identity['end_frame'] - identity['start_frame']
                and geometry['model_sha256'] == GEOMETRY_SHA
                and geometry['ground_order_vote_agreement'] >= .8
                and geometry['ground_indices'] in [list(range(4)), list(range(4,8))]
                and geometry['width'] == identity['width'] and geometry['height'] == identity['height'])
    except (OSError, ValueError, KeyError, TypeError):
        return False


def copy_inputs(source, destination):
    for name in (*INPUT_FILES, 'input_manifest.json'):
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / name, target)


def inference_inputs(args, run_dir, identity, work_root, stages):
    destination = run_dir / 'inputs'
    cache = work_root / 'inference_cache' / canonical_hash(identity)
    candidates = [cache]
    if args.saved_inputs:
        candidates.append(Path(args.saved_inputs))
    else:
        candidates.append(ROOT / 'output' / 'inputs')
    for candidate in candidates:
        if verified_inputs(candidate, identity):
            copy_inputs(candidate, destination)
            if candidate != cache:
                copy_inputs(candidate, cache)
            stages.extend([{'stage': 'tracking', 'action': 'reuse_verified_inputs'},
                           {'stage': 'vehicle_geometry', 'action': 'reuse_verified_inputs'}])
            print('Reusing tracking and vehicle geometry verified for this exact video and interval.', flush=True)
            return destination
    try:
        for package in ['ultralytics', 'torch', 'pandas', 'ipython', 'lap']:
            importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError as exc:
        raise RuntimeError('Fresh inference needs requirements-inference.txt or the GPU workflow notebook.') from exc
    if importlib.metadata.version('ultralytics') != '8.4.175':
        raise RuntimeError('Fresh inference requires ultralytics==8.4.175 for the recorded model configuration.')
    environment = os.environ.copy()
    environment.update({'FYP_SPEED_SOURCE': str(Path(args.video).resolve()),
                        'FYP_START_S': str(args.start), 'FYP_DURATION_S': str(args.duration),
                        'FYP_TRACKING_OUTPUT': str(destination / 'tracking'),
                        'FYP_GEOMETRY_OUTPUT': str(destination / 'geometry'),
                        'FYP_TRACKS_CSV': str(destination / 'tracking/tracks.csv'),
                        'FYP_MODELS_DIR': str(work_root / 'models'),
                        'FYP_SKIP_INSTALL': '1', 'MPLBACKEND': 'Agg'})
    if args.device:
        environment['FYP_DEVICE'] = args.device
    for stage, script in [('tracking', 'notebook/baseline.py'),
                          ('vehicle_geometry', 'geometry_notebook/extract_geometry.py')]:
        print('Running ' + stage + ' inference...', flush=True)
        subprocess.run([sys.executable, '-X', 'utf8', str(ROOT / script)],
                       env=environment, cwd=ROOT, check=True)
        stages.append({'stage': stage, 'action': 'model_inference'})
    write_input_manifest(destination, identity)
    if not verified_inputs(destination, identity):
        raise RuntimeError('Inference output metadata did not match the requested video and interval.')
    copy_inputs(destination, cache)
    return destination


def run_workflow(args):
    started = time.monotonic()
    video = Path(args.video).resolve()
    if not video.is_file():
        raise ValueError('Source video does not exist.')
    if args.start < 0 or args.duration < 2:
        raise ValueError('Use a nonnegative start and a duration of at least two seconds.')
    work_root = Path(args.work_dir).resolve()
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
    run_dir = work_root / 'runs' / run_id
    run_dir.mkdir(parents=True)
    stages = []
    report = {'schema_version': 1, 'run_id': run_id, 'camera_id': args.camera_id,
              'source_video': video.name, 'start_s': args.start, 'duration_s': args.duration,
              'accuracy_validated': False, 'stages': stages, 'status': 'running'}
    code = 0
    try:
        metadata, views = read_views(video, args.start, args.duration)
        report['video_metadata'] = metadata
        report['view_stability'] = stable_view(views)
        if not report['view_stability']['valid']:
            raise ValueError('The camera view changed or could not be verified within this interval. '
                             'Use a stable-camera segment; no speeds were generated.')
        signature = {'width': metadata['width'], 'height': metadata['height'],
                     'geometry_model_sha256': GEOMETRY_SHA,
                     'calculation_code_sha256': file_sha256(ROOT / 'calibrate_speed.py'),
                     'view_check_code_sha256': file_sha256(ROOT / 'camera_cache.py'),
                     'nominal_dimensions_m': [speed.LENGTH_M, speed.WIDTH_M],
                     'dimension_scenarios_m': [list(pair) for pair in speed.DIMENSION_SCENARIOS]}
        cache = CalibrationCache(args.cache_dir or work_root / 'calibration_cache', args.camera_id)
        if args.recalibrate:
            calibration, decision = None, {'status': 'miss', 'reason': 'recalibration_requested'}
        else:
            calibration, decision = cache.load(signature, views)
        report['calibration_lookup'] = decision
        stages.append({'stage': 'calibration_lookup', 'action': decision['status'], 'reason': decision['reason']})
        print('Calibration check: ' + decision['reason'], flush=True)
        source_sha = file_sha256(video)
        report['source_sha256'] = source_sha
        identity = input_identity(source_sha, metadata)
        inputs = inference_inputs(args, run_dir, identity, work_root, stages)
        output = run_dir / 'speed'
        if calibration is None:
            print('No usable saved calibration. Fitting local road geometry...', flush=True)
            geometry_report = json.loads((inputs / 'geometry/geometry_run_report.json').read_text())
            observations = json.loads((inputs / 'geometry/observations.json').read_text())
            footprints = speed.prepare(observations, geometry_report['ground_indices'],
                                       metadata['width'], metadata['height'])
            calibration = speed.fit_road_mappings(footprints, geometry_report)
            stages.append({'stage': 'road_calibration', 'action': 'fit_new_mapping'})
            if valid_calibration(calibration):
                cache.save(signature, views[0], calibration,
                           {'source_sha256': source_sha, 'start_s': args.start, 'duration_s': args.duration,
                            'created_at_utc': datetime.now(timezone.utc).isoformat()})
            else:
                # Still write empty result files, making unavailable speeds explicit.
                speed.run(calibration=calibration, geometry_dir=inputs / 'geometry', output_dir=output)
                report['status'] = 'insufficient_calibration_geometry'
                raise ValueError('Insufficient consistent vehicle geometry for a road mapping; no speeds available.')
        else:
            stages.append({'stage': 'road_calibration', 'action': 'reuse_saved_mapping'})
            print('Reusing the saved road mapping; no calibration fitting is run.', flush=True)
        print('Calculating speeds inside the calibrated road regions...', flush=True)
        _, rows, _ = speed.run(calibration=calibration, geometry_dir=inputs / 'geometry', output_dir=output,
                               calibration_reused=decision['status'] == 'hit')
        report['qualified_track_ids'] = sorted(row['track_id'] for row in rows if row['quality_passed'])
        report['candidate_track_spans'] = len(rows)
        report['calibration_reused'] = decision['status'] == 'hit'
        stages.append({'stage': 'speed_estimation', 'action': 'calculate_from_ground_motion'})
        if not args.no_render:
            environment = os.environ.copy()
            environment.update({'FYP_SPEED_SOURCE': str(video), 'FYP_START_S': str(args.start),
                                'FYP_DURATION_S': str(args.duration), 'FYP_SPEED_OUTPUT': str(output),
                                'FYP_BASELINE_TRACKS': str(inputs / 'tracking/tracks.csv')})
            subprocess.run([sys.executable, '-X', 'utf8', str(ROOT / 'render_speed.py')],
                           env=environment, check=True)
            stages.append({'stage': 'render', 'action': 'write_video_and_charts'})
        report['status'] = 'complete' if report['qualified_track_ids'] else 'complete_no_qualified_speeds'
    except Exception as exc:
        if report['status'] == 'running':
            report['status'] = 'failed'
        report['error'] = str(exc)
        code = 2
        print('Workflow stopped: ' + str(exc), file=sys.stderr, flush=True)
    finally:
        report['runtime_s'] = time.monotonic() - started
        (run_dir / 'workflow_report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print('Run folder: ' + str(run_dir), flush=True)
        print('Workflow status: ' + report['status'], flush=True)
    return code, run_dir


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument('--video', required=True, help='Original video path')
    result.add_argument('--camera-id', required=True, help='Stable identifier for this CCTV camera')
    result.add_argument('--start', type=float, default=150, help='Source interval start, seconds')
    result.add_argument('--duration', type=float, default=60, help='Interval duration, seconds')
    result.add_argument('--work-dir', default=str(ROOT / 'outputs'), help='Run, inference and cache storage')
    result.add_argument('--cache-dir', help='Optional persistent camera-calibration storage')
    result.add_argument('--saved-inputs', help='Optional verified inference bundle, with input_manifest.json')
    result.add_argument('--device', help='Inference device, e.g. 0 or cpu')
    result.add_argument('--recalibrate', action='store_true', help='Refit even if a valid calibration exists')
    result.add_argument('--no-render', action='store_true', help='Write speed tables/reports without regenerating video')
    return result


if __name__ == '__main__':
    code, _ = run_workflow(parser().parse_args())
    raise SystemExit(code)
