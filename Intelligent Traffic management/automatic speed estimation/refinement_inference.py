"""Second calibration-development round, using first-round learned maps and new flow."""
import argparse,json
from pathlib import Path
from benchmark_speed import load_clip
from calibration_candidates import select_rows,shared_vp_delay,vp_rigid_bundle
from lens_calibration import distortion_aware_delay
from refine_flow import extract_adaptive_flow,refine_constant_motion,flow_vanishing_point
from flow_calibration import estimate_flow


def run(args):
    import cv2
    cv2.setNumThreads(4)
    out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    for folder in sorted(Path(args.previous).iterdir()):
        if not (folder/'predictions.json').exists():continue
        target=out/folder.name;target.mkdir(exist_ok=True)
        obs,report=load_clip(Path(args.inference_dir)/folder.name)
        tracks=json.loads((Path(args.inference_dir)/folder.name/'tracks.json').read_text())
        original=json.loads((folder/'predictions.json').read_text())
        previous_flow=json.loads((folder/'flow_features.json').read_text())
        path=target/'adaptive_flow_features.json'
        flow=json.loads(path.read_text()) if path.exists() else None
        if flow is None or not any('matched_points_image' in r for r in flow.get('measurements',[])):
            flow=extract_adaptive_flow(Path(args.video_dir)/(folder.name+'.MP4'),obs,report,tracks)
            path.write_text(json.dumps(flow,indent=2),encoding='utf-8')
        old_vp=flow_vanishing_point(previous_flow);vp=flow_vanishing_point(flow)
        rows=select_rows(obs,report)
        learned=original['v4_learned_mask']
        predictions={'v2c_corner_vp_delay':shared_vp_delay(rows),
            'v2d_flow_vp_delay':shared_vp_delay(rows,vanishing_point=old_vp['point'],vp_weight=20),
            'v5c_adaptive_learned_flow':estimate_flow(flow,learned['mapping']),
            'v5d_constant_motion_refinement':refine_constant_motion(flow,learned['mapping']),
            'v7_adaptive_vp_delay':shared_vp_delay(rows,vanishing_point=vp['point'],vp_weight=20),
            'v7b_adaptive_vp_rigid':vp_rigid_bundle(obs,report,vp['point']),
            'v7c_fitted_effective_length':vp_rigid_bundle(obs,report,vp['point'],fit_length=True),
            'v9_motion_lens_delay':distortion_aware_delay(obs,report,flow)}
        (target/'predictions.json').write_text(json.dumps(predictions,indent=2),encoding='utf-8')
        (target/'vanishing_points.json').write_text(json.dumps({'original_flow':old_vp,'adaptive_flow':vp},indent=2),encoding='utf-8')
        print(folder.name,{k:round(v['estimated_kmh'],2) if v.get('estimated_kmh') is not None else None for k,v in predictions.items()},flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['inference-dir','video-dir','previous','output']:parser.add_argument('--'+name,required=True)
    run(parser.parse_args())
