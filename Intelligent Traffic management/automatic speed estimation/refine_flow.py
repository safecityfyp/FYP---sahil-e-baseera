"""Adaptive optical-flow intervals and speed-blind constant-motion map refinement."""
from collections import deque
import cv2
import numpy as np
from scipy.optimize import least_squares
from benchmark_speed import target_records
from calibrate_speed import project
from flow_calibration import estimate_flow


def extract_adaptive_flow(video,observations,report,tracks,max_gap=4,min_displacement=4):
    rows=target_records(observations,report)
    if not rows:return {'available':False,'measurements':[]}
    tid=rows[0]['track_id'];by_frame={r['frame_index']:r for r in tracks if r['track_id']==tid}
    cap=cv2.VideoCapture(str(video));assert cap.isOpened();buffer=deque(maxlen=max_gap+1)
    measurements=[];index=0
    def anchor(box):return np.array([(box[0]+box[2])/2,box[3]])
    try:
        while True:
            ok,frame=cap.read()
            if not ok:break
            buffer.append((index,frame))
            b=by_frame.get(index)
            if b is not None:
                for gap in range(1,min(max_gap,index)+1):
                    a=by_frame.get(index-gap)
                    if a is None:continue
                    if np.linalg.norm(anchor(a['box'])-anchor(b['box']))>=min_displacement or gap==max_gap:
                        break
                else:a=None
                if a is not None:
                    old_index=index-gap;previous=next(im for number,im in buffer if number==old_index)
                    box=np.array(a['box']);next_box=np.array(b['box']);height=box[3]-box[1]
                    if 80<=height<=450 and min(box[0],report['width']-box[2])>report['width']*.02:
                        union=np.r_[np.minimum(box[:2],next_box[:2])-20,np.maximum(box[2:],next_box[2:])+20]
                        x0,y0,x1,y1=np.rint(union).astype(int);x0=max(x0,0);y0=max(y0,0)
                        x1=min(x1,report['width']);y1=min(y1,report['height']);offset=np.array([x0,y0])
                        g0=cv2.cvtColor(previous[y0:y1,x0:x1],cv2.COLOR_BGR2GRAY)
                        g1=cv2.cvtColor(frame[y0:y1,x0:x1],cv2.COLOR_BGR2GRAY)
                        mask=np.zeros_like(g0)
                        cv2.rectangle(mask,tuple((box[:2]+(box[2:]-box[:2])*.12-offset).astype(int)),
                            tuple((box[2:]-(box[2:]-box[:2])*.12-offset).astype(int)),255,-1)
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
                                    point=anchor(box);transported=affine@np.r_[point-offset,1]+offset
                                    valid=inliers[:,0].astype(bool)
                                    error=np.linalg.norm(old[keep][valid]@affine[:,:2].T+affine[:,2]-new[keep][valid],axis=1)
                                    measurements.append({'frame_index':old_index,'next_frame_index':index,
                                        'frame_gap':gap,'time_s':a['time_s'],'dt_s':b['time_s']-a['time_s'],
                                        'anchor':point.tolist(),'transported_anchor':transported.tolist(),
                                        'affine':affine.tolist(),'crop_origin':offset.tolist(),
                                        'matched_points_image':(old[keep][valid]+offset).tolist(),
                                        'matched_next_points_image':(new[keep][valid]+offset).tolist(),
                                        'inliers':int(inliers.sum()),'flow_rms_pixels':float(np.sqrt(np.mean(error**2))),
                                        'box_height':float(height)})
            index+=1
    finally:cap.release()
    return {'available':len(measurements)>=8,'track_id':tid,'measurements':measurements,
            'frames_decoded':index,'maximum_frame_gap':max_gap,'minimum_target_pixel_displacement':min_displacement,
            'reference_label_used':False}


def flow_vanishing_point(features):
    points=[];weights=[]
    for row in features.get('measurements',[]):
        A=np.asarray(row['affine']);C=np.eye(2)-A[:,:2]
        if abs(np.linalg.det(C))<1e-6:continue
        center=np.linalg.solve(C,A[:,2]+C@np.asarray(row['crop_origin']))
        if not np.isfinite(center).all() or abs(center).max()>10000:continue
        points.append(center);weights.append(row['inliers'])
    if len(points)<8:return {'available':False,'reason':'insufficient_expansion_centres'}
    points=np.asarray(points);initial=np.median(points,axis=0)
    mad=np.median(np.abs(points-initial),axis=0)
    keep=np.all(np.abs(points-initial)<=np.maximum(4*1.4826*mad,15),axis=1)
    point=np.median(points[keep],axis=0)
    return {'available':True,'point':point.tolist(),'observations':int(keep.sum()),
            'median_absolute_deviation_pixels':np.median(np.abs(points[keep]-point),axis=0).tolist(),
            'reference_label_used':False}


def refine_constant_motion(features,mapping):
    """Constrain mapped flow to one velocity without knowing its magnitude.

    Retain the learned map's Jacobian at the centre of observed support to fix
    metric scale. This assumption is specific to these constant-speed passes.
    """
    rows=features.get('measurements',[])
    if len(rows)<12:return {'available':False,'reason':'insufficient_checked_flow'}
    times=np.array([r['time_s'] for r in rows]);lo,hi=np.quantile(times,[.1,.9])
    rows=[r for r in rows if lo<=r['time_s']<=hi]
    points=np.array([r['anchor'] for r in rows]);next_points=np.array([r['transported_anchor'] for r in rows])
    dt=np.array([r['dt_s'] for r in rows]);H=np.asarray(mapping)
    world=project(points,H);after=project(next_points,H)
    origin=np.median(world,axis=0);scale=max(np.ptp(world,axis=0).max(),1)
    normalizer=np.array([[1/scale,0,-origin[0]/scale],[0,1/scale,-origin[1]/scale],[0,0,1]])
    w=project(world,normalizer);a=project(after,normalizer)
    velocity=(a-w)/dt[:,None];median=np.median(velocity,axis=0)
    speed=max(np.linalg.norm(median),1e-5)
    def warp(p):return np.array([[1,0,0],[0,1,0],[p[0],p[1],1]])
    def residual(p):
        G=warp(p);v=(project(a,G)-project(w,G))/dt[:,None]
        den=np.c_[np.r_[w,a],np.ones(len(w)*2)]@G[2]
        return np.r_[((v-p[2:4])/speed).ravel(),p[:2]*.04,np.maximum(.25-den,0)*20]
    fit=least_squares(residual,np.r_[0,0,median],bounds=([-1.5,-1.5,-20,-20],[1.5,1.5,20,20]),
                      loss='soft_l1',f_scale=.08,max_nfev=300)
    G=warp(fit.x);den=np.c_[np.r_[w,a],np.ones(len(w)*2)]@G[2]
    if np.min(den)<.25:return {'available':False,'reason':'refined_mapping_pole'}
    refined=np.linalg.inv(normalizer)@G@normalizer@H
    result=estimate_flow(features,refined)
    if not result.get('available'):return result
    result.update(method='learned_flow_constant_motion_refinement',
        constant_speed_assumed=True,refinement_parameters=fit.x.tolist(),
        metric_scale_constraint='Preserve learned-map Jacobian at support centre',
        original_mapping=H.tolist(),velocity_relative_rms=float(np.sqrt(np.mean(residual(fit.x)[:2*len(w)]**2))))
    return result
