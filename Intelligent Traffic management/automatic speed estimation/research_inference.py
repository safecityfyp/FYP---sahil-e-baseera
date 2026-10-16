"""Run multiple speed-blind per-video calibration techniques and archive each version."""
import argparse
import json
from pathlib import Path
import time
import cv2
import numpy as np

from benchmark_speed import load_clip, target_records, projective_delay
from calibration_candidates import select_rows,temporal_delay_2d,rigid_cuboid_bundle,silhouette_bundle
from flow_calibration import extract_flow,estimate_flow
from learned_calibration import prepare_runtime,extract_mask_features,calibrate_from_features


def run(args):
    import torch,torchvision
    from torchvision.models.detection import maskrcnn_resnet50_fpn,MaskRCNN_ResNet50_FPN_Weights
    torch.set_num_threads(4);cv2.setNumThreads(4)
    net=prepare_runtime(args.runtime)
    detector=maskrcnn_resnet50_fpn(weights=MaskRCNN_ResNet50_FPN_Weights.DEFAULT,min_size=640,max_size=1280).eval().to(args.device)
    out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    for folder in sorted(Path(args.inference_dir).iterdir()):
        if not (folder/'observations.json').exists():continue
        target=out/folder.name;target.mkdir(exist_ok=True);start=time.monotonic()
        obs,report=load_clip(folder);tracks=json.loads((folder/'tracks.json').read_text())
        video=Path(args.video_dir)/(folder.name+'.MP4')
        def cached(name,call):
            path=target/(name+'.json')
            if path.exists():return json.loads(path.read_text())
            value=call();path.write_text(json.dumps(value,indent=2),encoding='utf-8');return value
        def masks():
            features,preview=extract_mask_features(video,obs,report,detector,args.device)
            if preview is not None:cv2.imwrite(str(target/'mask_example.jpg'),cv2.resize(preview,(1280,720)))
            return features
        mask=cached('mask_features',masks)
        flow=cached('flow_features',lambda:extract_flow(video,obs,report,tracks))
        rows=select_rows(obs,report,80,300)
        delay=projective_delay(rows,4.9) if len(rows)>=8 else {'available':False}
        if delay.get('available'):
            delay.update(estimated_kmh=delay['raw_kmh'],track_id=rows[0]['track_id'],
                time_interval_s=[rows[0]['time_s'],rows[-1]['time_s']])
        predictions={'v2_delay_1d':delay,
            'v2b_delay_2d':cached('delay_2d',lambda:temporal_delay_2d(select_rows(obs,report))),
            'v3_rigid_bundle':cached('rigid_bundle',lambda:rigid_cuboid_bundle(obs,report)),
            'v3b_rigid_distortion':cached('rigid_distortion',lambda:rigid_cuboid_bundle(obs,report,distortion=True)),
            'v4_learned_mask':cached('learned_mask',lambda:calibrate_from_features(mask,net,1)),
            'v4b_learned_ensemble':cached('learned_ensemble',lambda:calibrate_from_features(mask,net,16))}
        target_rows=target_records(obs,report)
        tid=target_rows[0]['track_id'] if target_rows else None
        tracking=[r for r in tracks if r['track_id']==tid]
        for shape in ['cuboid','sedan']:
            result=cached('silhouette_'+shape,lambda: silhouette_bundle([r['box'] for r in tracking],
                [r['time_s'] for r in tracking],report['width'],report['height'],shape))
            result['track_id']=tid;predictions['v6_silhouette_'+shape]=result
        for version,key in [('v5_learned_flow','v4_learned_mask'),('v5b_ensemble_flow','v4b_learned_ensemble')]:
            learned=predictions[key]
            predictions[version]=estimate_flow(flow,learned['mapping']) if learned.get('available') else {'available':False,'reason':'calibration_unavailable'}
        (target/'predictions.json').write_text(json.dumps(predictions,indent=2),encoding='utf-8')
        run={'video':video.name,'reference_speeds_used':False,'runtime_s':time.monotonic()-start,
            'torch':torch.__version__,'torchvision':torchvision.__version__,'opencv':cv2.__version__,
            'gpu':torch.cuda.get_device_name() if torch.cuda.is_available() else None}
        (target/'run_report.json').write_text(json.dumps(run,indent=2),encoding='utf-8')
        print(folder.name,{k:round(v['estimated_kmh'],1) if v.get('estimated_kmh') is not None else None for k,v in predictions.items()},flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['inference-dir','video-dir','output','runtime']:parser.add_argument('--'+name,required=True)
    parser.add_argument('--device',default='cuda')
    run(parser.parse_args())
