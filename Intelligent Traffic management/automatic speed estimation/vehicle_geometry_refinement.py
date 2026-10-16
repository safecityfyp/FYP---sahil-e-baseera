"""Speed-blind SUV geometry and temporal-window ablations, without a fixed flow VP."""
import argparse
import json
from pathlib import Path
import cv2
from benchmark_speed import load_clip
from calibration_candidates import select_rows, temporal_delay_2d, rigid_cuboid_bundle, shared_vp_delay


def run(args):
    cv2.setNumThreads(4)
    out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    for folder in sorted(Path(args.inference_dir).iterdir()):
        if not (folder/'observations.json').exists():continue
        target=out/folder.name;target.mkdir(exist_ok=True)
        observations,report=load_clip(folder)
        predictions={}
        for label,minimum,maximum in [('far',60,250),('middle',80,350),('wide',80,450)]:
            predictions['delay_'+label]=temporal_delay_2d(select_rows(observations,report,minimum,maximum))
        for distortion in [False,True]:
            label='suv_rigid_radial' if distortion else 'suv_rigid'
            predictions[label]=rigid_cuboid_bundle(observations,report,length_m=4.485,width_m=1.855,
                                                  height_m=1.645,distortion=distortion)
        predictions['corner_vp_weak']=shared_vp_delay(select_rows(observations,report),vp_weight=.002)
        (target/'predictions.json').write_text(json.dumps(predictions,indent=2)+'\n',encoding='utf-8')
        print(folder.name,{k:round(v['estimated_kmh'],3) if v.get('available') else None for k,v in predictions.items()},flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inference-dir',required=True);parser.add_argument('--output',required=True)
    run(parser.parse_args())
