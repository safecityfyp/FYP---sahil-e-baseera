# %% markdown
# FYP automatic vehicle geometry experiment
# A pretrained UrbanOmniDetect (CVPR 2026 DriveX) model predicts 8 projected 3D cuboid corners.
# Predictions are associated with the original baseline tracker IDs. No metric speeds are
# assigned here: approximate dimension priors and geometry consistency are evaluated separately.
# Source and citation: https://github.com/mkturkcan/urbanomnidetect
# Turkcan, Gumaste and Kostic, Calibration-Free View-Agnostic Monocular 3D Object Detection
# for Urban Scenes, CVPR Workshops 2026, pp. 786–795.

# %%
import subprocess, sys
subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-q', 'ultralytics==8.4.175'])

# %%
from pathlib import Path
import json, time, urllib.request, hashlib
import cv2
import numpy as np
import pandas as pd
import torch
from scipy.optimize import linear_sum_assignment
from ultralytics import YOLO
from IPython.display import display
import matplotlib.pyplot as plt

OUT = Path('/kaggle/working/geometry')
OUT.mkdir(exist_ok=True)
SOURCE = list(Path('/kaggle/input').rglob('A3_ch14_20260822105146_20260822110347.mp4'))
TRACKS = list(Path('/kaggle/input').rglob('tracks.csv'))
assert len(SOURCE)==1 and len(TRACKS)==1, (SOURCE,TRACKS)
SOURCE, TRACKS = SOURCE[0], TRACKS[0]
REPO='mehmetkeremturkcan/UrbanOmniDetect'
REVISION='2701a2eec9a73afb5ffd852740d125dfcd065ce5'
FILENAME='checkpoints/urbanomnidetect_yolo11x-p2_1920.pt'
weights=Path('/kaggle/working/urban_vehicle_geometry.pt')
urllib.request.urlretrieve(f'https://huggingface.co/{REPO}/resolve/{REVISION}/{FILENAME}',weights)
weight_sha=hashlib.sha256(weights.read_bytes()).hexdigest()
model=YOLO(str(weights))
car_classes=[int(k) for k,v in model.names.items() if v.lower()=='car']
assert car_classes,'Model has no car class'
device=0 if torch.cuda.is_available() else 'cpu'
print('Model:',REPO,REVISION,'Names:',model.names,'Device:',device)
df=pd.read_csv(TRACKS).dropna(subset=['track_id'])
df['track_id']=df.track_id.astype(int)
eligible=[]
for tid,group in df.groupby('track_id'):
    if len(group)>=25 and (group.class_name=='car').mean()>=0.7:
        eligible.append(tid)
df=df[df.track_id.isin(eligible)]
df=df[(df.frame_index%5==0)&(df.confidence>=0.3)&((df.y2-df.y1)>=60)]
by_frame={int(n):g for n,g in df.groupby('frame_index')}
cap=cv2.VideoCapture(str(SOURCE));assert cap.isOpened()
fps=cap.get(cv2.CAP_PROP_FPS);width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH));height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
start,end=round(150*fps),round(210*fps)
cap.set(cv2.CAP_PROP_POS_FRAMES,start)
records=[];samples=[];total_predictions=0;frames_processed=0
start_wall=time.monotonic()

def iou_matrix(a,b):
    lo=np.maximum(a[:,None,:2],b[None,:,:2]);hi=np.minimum(a[:,None,2:],b[None,:,2:])
    inter=np.prod(np.maximum(0,hi-lo),axis=2)
    area_a=np.prod(a[:,2:]-a[:,:2],axis=1);area_b=np.prod(b[:,2:]-b[:,:2],axis=1)
    return inter/(area_a[:,None]+area_b[None,:]-inter+1e-9)

try:
    for frame_index in range(start,end):
        ok,frame=cap.read()
        assert ok,f'Decode stopped at {frame_index}'
        if frame_index not in by_frame:continue
        result=model.predict(frame,device=device,imgsz=1920,conf=0.15,classes=car_classes,verbose=False)[0]
        frames_processed+=1
        total_predictions+=len(result.boxes)
        if result.keypoints is None or not len(result.boxes):continue
        baseline=by_frame[frame_index]
        boxes=result.boxes.xyxy.cpu().numpy();scores=result.boxes.conf.cpu().numpy()
        points=result.keypoints.data.cpu().numpy()
        assert points.shape[1]==8,points.shape
        overlap=iou_matrix(baseline[['x1','y1','x2','y2']].to_numpy(),boxes)
        ii,jj=linear_sum_assignment(1-overlap)
        for i,j in zip(ii,jj):
            if overlap[i,j]<0.35:continue
            row=baseline.iloc[i]
            records.append({'frame_index':frame_index,'time_s':float(row.video_time_s),
                'track_id':int(row.track_id),'baseline_confidence':float(row.confidence),
                'geometry_confidence':float(scores[j]),'association_iou':float(overlap[i,j]),
                'baseline_box':[float(row[k]) for k in ['x1','y1','x2','y2']],
                'geometry_box':boxes[j].tolist(),'geometry_class':'car','keypoints':points[j].tolist()})
        if frame_index%125==0 and len(samples)<12:
            # Keep raw images too: keypoint quality must be checked against the source.
            cv2.imwrite(str(OUT/f'raw_{frame_index:06d}.jpg'),frame)
            annotated=result.plot()
            for points_one in points:
                corners=points_one[:,:2].astype(int)
                for a,b in [(0,1),(1,2),(2,3),(3,0),(4,5),(5,6),(6,7),(7,4),(0,4),(1,5),(2,6),(3,7)]:
                    cv2.line(annotated,tuple(corners[a]),tuple(corners[b]),(0,220,255),2)
            cv2.imwrite(str(OUT/f'pose_{frame_index:06d}.jpg'),annotated)
            samples.append((frame_index/fps,cv2.resize(annotated,(1280,720))))
        if frames_processed%50==0:print('Inference frames:',frames_processed,'Matched observations:',len(records),flush=True)
finally:
    cap.release()

(OUT/'observations.json').write_text(json.dumps(records),encoding='utf-8')
# Resolve checkpoint corner-order discrepancy by voting, then lock for the entire run.
if records:
    p=np.array([r['keypoints'] for r in records])
    vote=(p[:,:4,1].mean(axis=1)>p[:,4:,1].mean(axis=1))
    first_ground=bool(vote.mean()>=0.5)
    ground_indices=list(range(4)) if first_ground else list(range(4,8))
    agreement=float(max(vote.mean(),1-vote.mean()))
else:ground_indices=[];agreement=0
report={'model_repo':REPO,'model_revision':REVISION,'model_filename':FILENAME,
    'model_sha256':weight_sha,'model_names':model.names,'ground_indices':ground_indices,
    'ground_order_vote_agreement':agreement,'width':width,'height':height,'fps':fps,
    'inference_frames':frames_processed,'all_geometry_predictions':total_predictions,
    'matched_observations':len(records),'matched_track_ids':len(set(r['track_id'] for r in records)),
    'runtime_s':time.monotonic()-start_wall,'metric_calibration_available':False,'imgsz':1920,
    'gpu':torch.cuda.get_device_name(0) if device==0 else None,
    'limitations':['Predicted ground corners are learned estimates, not measured contacts.',
    'No scene-specific keypoint labels or speed ground truth supplied.',
    'Approximate metric scale must be labelled as a dimension-prior hypothesis.']}
(OUT/'geometry_run_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
fig,axes=plt.subplots(3,4,figsize=(20,10))
for ax,(timestamp,image) in zip(axes.flat,samples):
    ax.imshow(cv2.cvtColor(image,cv2.COLOR_BGR2RGB));ax.set_title(f't={timestamp:.1f}s')
for ax in axes.flat:ax.axis('off')
fig.tight_layout();fig.savefig(OUT/'geometry_contact_sheet.jpg',dpi=150);plt.show()
