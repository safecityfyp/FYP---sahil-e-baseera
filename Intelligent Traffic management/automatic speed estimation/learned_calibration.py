"""Adapter for Revaud/Humenberger ICCV 2021's released calibration network.

Upstream implementation is downloaded at a pinned revision into ignored runtime
storage and retains its CC BY-NC-SA 3.0 terms. No upstream weights are committed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import urllib.request

import cv2
import numpy as np
from benchmark_speed import load_clip, target_records
from calibrate_speed import project

UPSTREAM='https://raw.githubusercontent.com/naver/cctv/'
REVISION='80b8bc4964eddfda32c40e6d1c8fe8b62f777f55'
WEIGHT_SHA='bcb5af76b769788ec18b663e0e1a879ab2d3dce30eb2d0f3162e9730e5204fbf'
FILES=['archs/__init__.py','archs/transformer.py','tools/geometry.py','tools/speed.py',
       'tools/common.py','tools/tracks.py','LICENSE','NOTICE','models/trained_transformer.pt']


def prepare_runtime(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    for name in FILES:
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True)
        if not path.exists():urllib.request.urlretrieve(UPSTREAM+REVISION+'/'+name,path)
    weights=root/'models/trained_transformer.pt'
    assert hashlib.sha256(weights.read_bytes()).hexdigest()==WEIGHT_SHA
    if str(root.resolve()) not in sys.path:sys.path.insert(0,str(root.resolve()))
    import torch
    from archs.transformer import Transformer
    data=torch.load(weights,map_location='cpu',weights_only=True)
    assert data['arch']=='Transformer(nlayers=8, nhead=4, nhid=256)'
    net=Transformer(embdim=64,outdim=8,nlayers=8,nhead=4,nhid=256).eval()
    net.load_state_dict(data['weights'])
    return net


def iou(box,boxes):
    lo=np.maximum(box[:2],boxes[:,:2]);hi=np.minimum(box[2:],boxes[:,2:])
    area=np.maximum(hi-lo,0).prod(axis=1)
    return area/(np.prod(box[2:]-box[:2])+np.prod(boxes[:,2:]-boxes[:,:2],axis=1)-area+1e-9)


def extract_mask_features(video,observations,report,detector,device,max_samples=24):
    """Get segmentation moments and motion direction without any reference speed."""
    import torch
    rows=target_records(observations,report,70,450)
    if len(rows)<8:return {'available':False,'reason':'insufficient_track'},None
    original={(r['track_id'],r['frame_index']):r for r in observations}
    selected=[rows[i] for i in np.unique(np.linspace(0,len(rows)-1,min(max_samples,len(rows))).astype(int))]
    cap=cv2.VideoCapture(str(video));assert cap.isOpened();features=[];preview=None
    W,H=report['width'],report['height'];S=max(W,H)
    try:
        for row in selected:
            cap.set(cv2.CAP_PROP_POS_FRAMES,row['frame_index']);ok,frame=cap.read();assert ok
            tensor=torch.from_numpy(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)).permute(2,0,1).float().to(device)/255
            with torch.inference_mode():result=detector([tensor])[0]
            accepted=(result['labels']==3)&(result['scores']>=.5)
            boxes=result['boxes'][accepted].cpu().numpy()
            if not len(boxes):continue
            baseline=np.array(original[row['track_id'],row['frame_index']]['baseline_box'])
            scores=iou(baseline,boxes);index=int(np.argmax(scores))
            if scores[index]<.3:continue
            box=boxes[index];mask=result['masks'][accepted][index,0].cpu().numpy()
            x0,y0,x1,y1=np.rint(box).astype(int);x0=max(0,x0);y0=max(0,y0);x1=min(W,x1);y1=min(H,y1)
            if min(x1-x0,y1-y0)<10:continue
            small=cv2.resize(mask[y0:y1,x0:x1],(28,28),interpolation=cv2.INTER_AREA)
            xy=np.mgrid[0:28,0:28].reshape(2,-1)[::-1].T
            xy=(xy+.5)/28*(box[2:]-box[:2])/S+box[:2]/S
            weight=small.ravel();weight/=max(weight.sum(),1e-9)
            center=(weight[:,None]*xy).sum(axis=0);diff=xy-center
            covariance=(diff.T*weight)@diff
            features.append({'frame_index':row['frame_index'],'time_s':row['time_s'],'box':box.tolist(),
                'center_normalized':center.tolist(),'covariance_normalized':covariance.ravel().tolist(),
                'association_iou':float(scores[index])})
            if len(features)==len(selected)//2:
                preview=frame.copy();preview[mask>.5]=(preview[mask>.5]*.5+np.array([0,127,0])).astype(np.uint8)
    finally:cap.release()
    return {'available':len(features)>=8,'track_id':rows[0]['track_id'],'features':features,
        'width':W,'height':H,'fps':report['fps'],'model':'torchvision MaskRCNN ResNet50 FPN COCO V1',
        'segmentation_min_size':640,'reference_label_used':False},preview


def calibrate_from_features(features,net,ensemble=1,seed=17):
    import torch
    from tools.speed import ransac_homography_from_jacobians
    rows=features.get('features',[])
    if len(rows)<8:return {'available':False,'reason':'insufficient_segmented_observations'}
    centers=np.array([r['center_normalized'] for r in rows]);cov=np.array([r['covariance_normalized'] for r in rows])
    times=np.array([r['time_s'] for r in rows]);motion=np.gradient(centers,times,axis=0)
    motion/=np.maximum(np.linalg.norm(motion,axis=1,keepdims=True),1e-9)
    motion*=np.sign(motion[:,1:2])
    embeddings=np.c_[centers,1001*cov,motion].astype(np.float32)
    rng=np.random.default_rng(seed);all_predictions=[]
    for repeat in range(ensemble):
        indices=(np.unique(np.linspace(0,len(rows)-1,min(10,len(rows))).astype(int)) if ensemble==1
                 else rng.choice(len(rows),size=min(10,len(rows)),replace=False))
        with torch.inference_mode():prediction=net(torch.from_numpy(embeddings[indices][None]))[0]
        all_predictions.append(prediction)
    np.random.seed(seed)
    H=ransac_homography_from_jacobians(torch.cat(all_predictions),niter=1024)
    H=H@np.diag([1/max(features['width'],features['height'])]*2+[1])
    boxes=np.array([r['box'] for r in rows]);anchors=np.c_[(boxes[:,0]+boxes[:,2])/2,boxes[:,3]]
    world=project(anchors,H);t=times-times.mean()
    velocity=np.array([np.polyfit(t,world[:,axis],1)[0] for axis in [0,1]])
    predicted=world.mean(axis=0)+t[:,None]*velocity
    return {'available':bool(np.isfinite(world).all()),'estimated_kmh':float(np.linalg.norm(velocity)*3.6),
        'method':'learned_mask_calibration' if ensemble==1 else 'learned_mask_calibration_ensemble',
        'mapping':H.tolist(),'time_interval_s':[float(times[0]),float(times[-1])],
        'support_hull_image':cv2.convexHull(anchors.astype(np.float32)).reshape(-1,2).tolist(),
        'track_id':features['track_id'],'observations':len(rows),'ensemble_samples':ensemble,
        'trajectory_rms_m':float(np.sqrt(np.mean((world-predicted)**2))),
        'upstream_revision':REVISION,'upstream_model_sha256':WEIGHT_SHA,'reference_label_used':False}


def run(args):
    import torch
    from torchvision.models.detection import maskrcnn_resnet50_fpn,MaskRCNN_ResNet50_FPN_Weights
    torch.set_num_threads(4)
    net=prepare_runtime(args.runtime)
    detector=maskrcnn_resnet50_fpn(weights=MaskRCNN_ResNet50_FPN_Weights.DEFAULT,min_size=640,max_size=1280).eval().to(args.device)
    out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    folders=sorted(Path(args.inference_dir).iterdir())
    if args.pilots:folders=[p for p in folders if p.name in {f'MercedesAMG550_{s}' for s in [30,60,100]}]
    for folder in folders:
        if not (folder/'observations.json').exists():continue
        target=out/folder.name;target.mkdir(exist_ok=True)
        obs,report=load_clip(folder)
        if (target/'mask_features.json').exists():features=json.loads((target/'mask_features.json').read_text())
        else:
            features,preview=extract_mask_features(Path(args.video_dir)/(folder.name+'.MP4'),obs,report,detector,args.device)
            (target/'mask_features.json').write_text(json.dumps(features,indent=2),encoding='utf-8')
            if preview is not None:cv2.imwrite(str(target/'mask_example.jpg'),cv2.resize(preview,(1280,720)))
        results={f'learned_{n}':calibrate_from_features(features,net,n) for n in [1,16]}
        (target/'learned_predictions.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
        print(folder.name,'mask observations',len(features.get('features',[])),
            'estimates',{k:round(v['estimated_kmh'],2) if v.get('estimated_kmh') is not None else None for k,v in results.items()},flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['inference-dir','video-dir','output','runtime']:parser.add_argument('--'+name,required=True)
    parser.add_argument('--device',default='cuda');parser.add_argument('--pilots',action='store_true')
    run(parser.parse_args())
