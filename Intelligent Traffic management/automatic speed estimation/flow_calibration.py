"""Forward/backward checked optical flow and robust contact-anchor transport.

Inspired by dynamic vehicle-template flow, with the metric ground map supplied
by a separate calibration method. This is not the 36-keypoint paper's model.
"""
from pathlib import Path
import cv2
import numpy as np
from benchmark_speed import target_records
from calibrate_speed import project


def extract_flow(video,observations,report,tracks):
    rows=target_records(observations,report)
    if not rows:return {'available':False,'measurements':[]}
    tid=rows[0]['track_id'];by_frame={r['frame_index']:r for r in tracks if r['track_id']==tid}
    cap=cv2.VideoCapture(str(video));assert cap.isOpened()
    ok,previous=cap.read();index=0;measurements=[]
    try:
        while ok:
            ok,current=cap.read()
            if not ok:break
            a=by_frame.get(index);b=by_frame.get(index+1)
            if a is not None and b is not None:
                box=np.array(a['box']);next_box=np.array(b['box']);height=box[3]-box[1]
                if 80<=height<=450 and min(box[0],report['width']-box[2])>report['width']*.02:
                    union=np.r_[np.minimum(box[:2],next_box[:2])-20,np.maximum(box[2:],next_box[2:])+20]
                    x0,y0,x1,y1=np.rint(union).astype(int)
                    x0=max(x0,0);y0=max(y0,0);x1=min(x1,report['width']);y1=min(y1,report['height'])
                    g0=cv2.cvtColor(previous[y0:y1,x0:x1],cv2.COLOR_BGR2GRAY)
                    g1=cv2.cvtColor(current[y0:y1,x0:x1],cv2.COLOR_BGR2GRAY)
                    mask=np.zeros_like(g0);offset=np.array([x0,y0])
                    p0=(box[:2]+(box[2:]-box[:2])*.12-offset).astype(int)
                    p1=(box[2:]-(box[2:]-box[:2])*.12-offset).astype(int)
                    cv2.rectangle(mask,tuple(p0),tuple(p1),255,-1)
                    features=cv2.goodFeaturesToTrack(g0,120,.01,4,mask=mask)
                    if features is not None and len(features)>=8:
                        forward,status,_=cv2.calcOpticalFlowPyrLK(g0,g1,features,None,winSize=(31,31),maxLevel=3)
                        backward,bs,_=cv2.calcOpticalFlowPyrLK(g1,g0,forward,None,winSize=(31,31),maxLevel=3)
                        old=features[:,0];new=forward[:,0]
                        keep=(status[:,0]>0)&(bs[:,0]>0)&(np.linalg.norm(backward[:,0]-old,axis=1)<1)
                        keep&=(np.linalg.norm(new-old,axis=1)>.25)
                        if keep.sum()>=6:
                            affine,inliers=cv2.estimateAffinePartial2D(old[keep],new[keep],method=cv2.RANSAC,ransacReprojThreshold=1.5,maxIters=1000)
                            if affine is not None and inliers.sum()>=6:
                                anchor=np.array([(box[0]+box[2])/2,box[3]])
                                transported=affine@np.r_[anchor-offset,1]+offset
                                selected=inliers[:,0].astype(bool)
                                error=np.linalg.norm(old[keep][selected]@affine[:,:2].T+affine[:,2]-new[keep][selected],axis=1)
                                measurements.append({'frame_index':index,'time_s':a['time_s'],
                                    'dt_s':b['time_s']-a['time_s'],'anchor':anchor.tolist(),
                                    'transported_anchor':transported.tolist(),'affine':affine.tolist(),
                                    'crop_origin':offset.tolist(),'inliers':int(inliers.sum()),
                                    'flow_rms_pixels':float(np.sqrt(np.mean(error**2))),
                                    'box_height':float(height)})
            previous=current;index+=1
    finally:cap.release()
    return {'available':len(measurements)>=8,'track_id':tid,'measurements':measurements,
            'reference_label_used':False,'frames_decoded':index+1}


def estimate_flow(features,mapping,trim_fraction=.1):
    rows=features.get('measurements',[])
    if len(rows)<8:return {'available':False,'reason':'insufficient_checked_flow'}
    times=np.array([r['time_s'] for r in rows]);lo,hi=np.quantile(times,[trim_fraction,1-trim_fraction])
    rows=[r for r in rows if lo<=r['time_s']<=hi]
    points=np.array([r['anchor'] for r in rows]);next_points=np.array([r['transported_anchor'] for r in rows])
    dt=np.array([r['dt_s'] for r in rows])
    velocities=(project(next_points,np.array(mapping))-project(points,np.array(mapping)))/dt[:,None]
    speeds=np.linalg.norm(velocities,axis=1)*3.6
    finite=np.isfinite(speeds)&(speeds>0)&(speeds<300)
    if finite.sum()<8:return {'available':False,'reason':'invalid_mapped_flow'}
    median=np.median(speeds[finite]);mad=np.median(np.abs(speeds[finite]-median))
    keep=finite&(np.abs(speeds-median)<=max(4*1.4826*mad,2))
    return {'available':True,'estimated_kmh':float(np.median(speeds[keep])),
        'method':'learned_map_and_optical_flow','mapping':np.asarray(mapping).tolist(),
        'track_id':features['track_id'],'observations':int(keep.sum()),
        'time_interval_s':[float(times.min()),float(times.max())],
        'support_hull_image':cv2.convexHull(points.astype(np.float32)).reshape(-1,2).tolist(),
        'per_frame_kmh':speeds.tolist(),'per_frame_keep':keep.tolist(),
        'per_frame_times_s':[r['time_s'] for r in rows],
        'speed_mad_kmh':float(mad),'time_trim_fraction':trim_fraction,'reference_label_used':False}
