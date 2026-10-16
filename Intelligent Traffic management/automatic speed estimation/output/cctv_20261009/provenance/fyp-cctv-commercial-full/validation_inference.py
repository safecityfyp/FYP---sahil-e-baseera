"""Speed-blind detection and cuboid extraction for constant-speed validation clips."""
from pathlib import Path
import argparse
import hashlib
import json
import time
import urllib.request

import cv2
import numpy as np
from scipy.optimize import linear_sum_assignment
from ultralytics import YOLO

MODEL_REPO='mehmetkeremturkcan/UrbanOmniDetect'
MODEL_REVISION='2701a2eec9a73afb5ffd852740d125dfcd065ce5'
MODEL_FILE='checkpoints/urbanomnidetect_yolo11x-p2_1920.pt'
MODEL_SHA='9aa55280a5ef1c9d89c0acb5baeb974b90fbdf3c1deead1413b24d7af249226d'


def overlaps(a,b):
    lo=np.maximum(a[:,None,:2],b[None,:,:2]);hi=np.minimum(a[:,None,2:],b[None,:,2:])
    intersection=np.prod(np.maximum(0,hi-lo),axis=2)
    return intersection/(np.prod(a[:,2:]-a[:,:2],axis=1)[:,None]+
                         np.prod(b[:,2:]-b[:,:2],axis=1)[None,:]-intersection+1e-9)


def infer(folder,output,device='0'):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    model_dir=output.parent/'models';model_dir.mkdir(exist_ok=True)
    weights=model_dir/'urban_geometry.pt'
    if not weights.exists():
        urllib.request.urlretrieve(f'https://huggingface.co/{MODEL_REPO}/resolve/{MODEL_REVISION}/{MODEL_FILE}',weights)
    assert hashlib.sha256(weights.read_bytes()).hexdigest()==MODEL_SHA
    geometry_model=YOLO(str(weights))
    for video in sorted(Path(folder).rglob('*.MP4')):
        target=output/video.stem;target.mkdir(exist_ok=True)
        tracker=YOLO(str(model_dir/'yolo11s.pt'))
        cap=cv2.VideoCapture(str(video));assert cap.isOpened()
        width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH));height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps=float(cap.get(cv2.CAP_PROP_FPS));total=int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        observations=[];tracks=[];times=[];start=time.monotonic();index=0
        while True:
            ok,frame=cap.read()
            if not ok:break
            pts=float(cap.get(cv2.CAP_PROP_POS_MSEC))/1000
            timestamp=pts if abs(pts-index/fps)<.1 else index/fps
            times.append(timestamp)
            if index==0:cv2.imwrite(str(target/'reference.jpg'),frame)
            detected=tracker.track(frame,persist=True,tracker='bytetrack.yaml',device=device,
                                   imgsz=1280,classes=[2,5,7],conf=.15,verbose=False)[0]
            boxes=detected.boxes.xyxy.cpu().numpy()
            ids=detected.boxes.id.cpu().numpy().astype(int) if detected.boxes.id is not None else np.full(len(boxes),-1)
            scores=detected.boxes.conf.cpu().numpy()
            for box,tid,score in zip(boxes,ids,scores):
                tracks.append({'frame_index':index,'time_s':timestamp,'track_id':int(tid),
                               'box':box.tolist(),'confidence':float(score)})
            selected=[i for i,box in enumerate(boxes) if box[3]-box[1]>=45 and ids[i]>=0]
            if selected:
                result=geometry_model.predict(frame,device=device,imgsz=1920,classes=[0],conf=.15,verbose=False)[0]
                if result.keypoints is not None and len(result.boxes):
                    gb=result.boxes.xyxy.cpu().numpy();gs=result.boxes.conf.cpu().numpy()
                    kp=result.keypoints.data.cpu().numpy()
                    overlap=overlaps(boxes[selected],gb);ii,jj=linear_sum_assignment(1-overlap)
                    for i,j in zip(ii,jj):
                        if overlap[i,j]<.25:continue
                        k=selected[i]
                        observations.append({'frame_index':index,'time_s':timestamp,'track_id':int(ids[k]),
                            'baseline_confidence':float(scores[k]),'geometry_confidence':float(gs[j]),
                            'association_iou':float(overlap[i,j]),'baseline_box':boxes[k].tolist(),
                            'geometry_box':gb[j].tolist(),'keypoints':kp[j].tolist()})
                    if len(observations)%20<2:
                        cv2.imwrite(str(target/f'geometry_{index:04d}.jpg'),result.plot())
            index+=1
        cap.release()
        assert index==total
        (target/'observations.json').write_text(json.dumps(observations),encoding='utf-8')
        (target/'tracks.json').write_text(json.dumps(tracks),encoding='utf-8')
        if observations:
            points=np.array([r['keypoints'] for r in observations])
            vote=points[:,:4,1].mean(axis=1)>points[:,4:,1].mean(axis=1)
            ground_indices=list(range(4)) if vote.mean()>=.5 else list(range(4,8))
            agreement=float(max(vote.mean(),1-vote.mean()))
        else:ground_indices=[];agreement=0.0
        report={'source_video':video.name,'width':width,'height':height,'fps':fps,'frames':total,
                'duration_s':total/fps,'timestamps':times,'model_sha256':MODEL_SHA,
                'model_revision':MODEL_REVISION,'model_filename':MODEL_FILE,'ground_indices':ground_indices,
                'ground_order_vote_agreement':agreement,'runtime_s':time.monotonic()-start,
                'observations':len(observations),'reference_speeds_used_by_inference':False}
        (target/'geometry_run_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(video.name,'frames',index,'geometry',len(observations),'seconds',round(report['runtime_s'],1),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--device',default='0')
    args=parser.parse_args();infer(args.input,args.output,args.device)
