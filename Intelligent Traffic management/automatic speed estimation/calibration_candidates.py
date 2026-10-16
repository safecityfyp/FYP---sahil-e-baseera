"""Independent per-video calibration candidates; prediction functions accept no speed labels.

The temporal and rigid-bundle methods are new implementations of projective and
rigid-body geometry, not reproductions of any authors' trained keypoint system.
"""
import math
import cv2
import numpy as np
from scipy.optimize import least_squares
from benchmark_speed import target_records, projective_delay


def select_rows(observations, report, minimum=100, maximum=400):
    rows = target_records(observations, report, minimum, maximum)
    original={(r['track_id'],r['frame_index']):r for r in observations}
    rows=[{**original[r['track_id'],r['frame_index']],**r} for r in rows]
    for row in rows:row['box_height']=row['baseline_box'][3]-row['baseline_box'][1]
    width, height = report['width'], report['height']
    rows = [r for r in rows if np.all(np.asarray(r['quad'])[:, 0] > width*.02)
            and np.all(np.asarray(r['quad'])[:, 0] < width*.98)
            and np.all(np.asarray(r['quad'])[:, 1] < height*.98)]
    return sorted(rows, key=lambda r:r['time_s'])


def temporal_delay_2d(rows, length_m=4.9):
    """Fit front/rear ground midpoints to one 2D rational constant-motion curve."""
    if len(rows)<8:return {'available':False,'reason':'insufficient_geometry'}
    q=np.asarray([r['quad'] for r in rows]);times=np.asarray([r['time_s'] for r in rows])
    span=float(np.ptp(times))
    if span<.2:return {'available':False,'reason':'short_interval'}
    front=(q[:,0]+q[:,3])/2;rear=(q[:,1]+q[:,2])/2
    direction=np.mean(q[-3:],axis=(0,1))-np.mean(q[:3],axis=(0,1))
    if np.median((front-rear)@direction)<0:front,rear=rear,front
    origin=np.mean(np.r_[front,rear],axis=0);scale=max(np.ptp(np.r_[front,rear],axis=0).max(),1)
    f=(front-origin)/scale;r=(rear-origin)/scale;t=(times-times[0])/span
    linear=np.array([np.polyfit(t,f[:,axis],1) for axis in [0,1]])
    def curve(p,s):return (p[:2]+s[:,None]*p[2:4])/np.maximum(1+p[4]*s[:,None],.01)
    def residual(p):
        d=np.exp(p[5]);den=np.r_[1+p[4]*t,1+p[4]*(t-d)]
        return np.r_[(curve(p,t)-f).ravel(),(curve(p,t-d)-r).ravel(),np.maximum(.03-den,0)*10]
    fits=[]
    for perspective in [-.7,-.3,0,.7,2]:
        initial=np.r_[linear[:,1],linear[:,0],perspective,np.log(.25/span)]
        fit=least_squares(residual,initial,bounds=([-5,-5,-20,-20,-.95,np.log(.03/span)],
            [5,5,20,20,4,np.log(4/span)]),loss='soft_l1',f_scale=.015,max_nfev=500)
        error=np.mean(residual(fit.x)**2);fits.append((error,fit))
    error,fit=min(fits,key=lambda x:x[0]);delay=float(np.exp(fit.x[5])*span)
    return {'available':True,'estimated_kmh':length_m/delay*3.6,'method':'temporal_projective_2d',
        'delay_s':delay,'time_interval_s':[float(times[0]),float(times[-1])],
        'track_id':rows[0]['track_id'],'observations':len(rows),
        'reprojection_rms_pixels':float(np.sqrt(error)*scale),
        'parameters':fit.x.tolist(),'curve_origin':origin.tolist(),'curve_scale':float(scale),
        'fitted_front_image':(curve(fit.x,t)*scale+origin).tolist(),
        'fitted_rear_image':(curve(fit.x,t-np.exp(fit.x[5]))*scale+origin).tolist(),
        'curve_times_s':times.tolist(),
        'support_hull_image':cv2.convexHull(q.reshape(-1,2).astype(np.float32)).reshape(-1,2).tolist(),
        'length_prior_m':length_m,'reference_label_used':False}


def corner_vanishing_point(rows):
    """Robust intersection of tracked longitudinal-corner motion lines."""
    quads=np.asarray([r['quad'] for r in rows]);lines=[]
    for index in range(4):
        vx,vy,x,y=cv2.fitLine(quads[:,index].astype(np.float32),cv2.DIST_HUBER,0,.01,.01).ravel()
        lines.append([-float(vy),float(vx),float(vy*x-vx*y)])
    lines=np.array(lines);initial=np.linalg.lstsq(lines[:,:2],-lines[:,2],rcond=None)[0]
    fit=least_squares(lambda p:lines[:,:2]@p+lines[:,2],initial,loss='soft_l1',f_scale=3)
    return fit.x,float(np.sqrt(np.mean((lines[:,:2]@fit.x+lines[:,2])**2)))


def shared_vp_delay(rows,length_m=4.9,vanishing_point=None,vp_weight=.02):
    """Fit both longitudinal sides with a shared motion vanishing point and delay.

    Each side retains its own projective depth. This avoids averaging projected
    corners before accounting for perspective. An optional flow VP is speed-blind.
    """
    if len(rows)<8:return {'available':False,'reason':'insufficient_geometry'}
    q=np.asarray([r['quad'] for r in rows]);times=np.array([r['time_s'] for r in rows])
    span=float(np.ptp(times));t=(times-times[0])/span
    fronts=q[:,[0,3]];rears=q[:,[1,2]]
    direction=q[-1].mean(axis=0)-q[0].mean(axis=0)
    if np.median(np.sum((fronts-rears)*direction,axis=2))<0:fronts,rears=rears,fronts
    origin=q.mean(axis=(0,1));scale=max(np.ptp(q.reshape(-1,2),axis=0).max(),1)
    front=(fronts-origin)/scale;rear=(rears-origin)/scale
    inferred,uncertainty=corner_vanishing_point(rows)
    if vanishing_point is None:vanishing_point=inferred
    vp=(np.asarray(vanishing_point)-origin)/scale
    # Allow small VP refinement for noisy correspondences while retaining the geometric prior.
    sigma=max(uncertainty*4,15)/scale
    def curve(p,s):
        current_vp=p[7:9];A=p[:4].reshape(2,2);c=p[4:6]
        return current_vp[None,None]+A[None]/np.maximum(1+s[:,None,None]*c[None,:,None],.02)
    def residual(p):
        d=np.exp(p[6]);den=np.r_[(1+t[:,None]*p[4:6]).ravel(),(1+(t[:,None]-d)*p[4:6]).ravel()]
        return np.r_[(curve(p,t)-front).ravel(),(curve(p,t-d)-rear).ravel(),
                     np.maximum(.03-den,0)*10,(p[7:9]-vp)/sigma*vp_weight]
    fits=[]
    for c in [-.75,-.4,0,.5,2]:
        initial=np.r_[(front[0]-vp).ravel(),c,c,np.log(.25/span),vp]
        lower=[-10]*4+[-.95,-.95,np.log(.03/span),-10,-10]
        upper=[10]*4+[4,4,np.log(4/span),10,10]
        initial=np.clip(initial,np.array(lower)+1e-6,np.array(upper)-1e-6)
        fit=least_squares(residual,initial,bounds=(lower,upper),loss='soft_l1',f_scale=.015,max_nfev=500)
        score=float(np.mean(residual(fit.x)**2));fits.append((score,fit))
    score,fit=min(fits,key=lambda x:x[0]);delay=float(np.exp(fit.x[6])*span)
    return {'available':True,'estimated_kmh':length_m/delay*3.6,'method':'shared_vanishing_point_temporal_calibration',
        'track_id':rows[0]['track_id'],'observations':len(rows),'delay_s':delay,'length_prior_m':length_m,
        'time_interval_s':[float(times[0]),float(times[-1])],'parameters':fit.x.tolist(),
        'vanishing_point_image':(fit.x[7:9]*scale+origin).tolist(),
        'initial_vanishing_point_image':np.asarray(vanishing_point).tolist(),
        'corner_line_rms_pixels':uncertainty,'reprojection_rms_pixels':float(np.sqrt(score)*scale),
        'fitted_front_image':(curve(fit.x,t)*scale+origin).tolist(),
        'fitted_rear_image':(curve(fit.x,t-np.exp(fit.x[6]))*scale+origin).tolist(),
        'curve_times_s':times.tolist(),
        'curve_origin':origin.tolist(),'curve_scale':float(scale),'vanishing_point_weight':vp_weight,
        'reference_label_used':False}


def rigid_cuboid_bundle(observations,report,length_m=4.9,width_m=1.87,height_m=1.45,distortion=False):
    """Jointly fit one camera and constant rigid 3D motion to many cuboid observations.

    Camera principal point is assumed at image centre; focal length and rotation
    are fitted. Object dimensions are priors, not independently measured values.
    """
    rows=select_rows(observations,report,100,400)
    if len(rows)<8:return {'available':False,'reason':'insufficient_geometry'}
    # Bound computation and balance temporal support without reference-speed input.
    rows=[rows[i] for i in np.unique(np.linspace(0,len(rows)-1,min(36,len(rows))).astype(int))]
    times=np.array([r['time_s'] for r in rows]);dt=times-times.mean()
    base=np.array([[-width_m/2,0,0],[-width_m/2,0,length_m],
                   [width_m/2,0,length_m],[width_m/2,0,0]],float)
    object_points=np.r_[base,base+[0,-height_m,0]]
    indices=report['ground_indices']+[i for i in range(8) if i not in report['ground_indices']]
    points=np.array([r['keypoints'] for r in rows])[:,indices,:2]
    pixel_scale=np.maximum(np.array([r['box_height'] for r in rows]),100)
    center=np.median(points[:,:4].mean(axis=1),axis=0);cx=report['width']/2;cy=report['height']/2
    def camera(p):
        R=cv2.Rodrigues(p[:3])[0];T=np.r_[p[3:5],np.exp(p[5])]
        v=np.exp(p[6]);f=np.exp(p[7]);k=p[8] if distortion else 0
        XYZ=object_points[None]@R.T+T-dt[:,None,None]*v*R[:,2]
        xy=XYZ[:,:,:2]/np.maximum(XYZ[:,:,2:],.1)
        xy*=1+k*np.sum(xy**2,axis=2,keepdims=True)
        image=xy*f+[cx,cy]
        return image,XYZ,R,T,f
    def residual(p):
        image,XYZ,*_=camera(p)
        return np.r_[((image-points)/pixel_scale[:,None,None]*200).ravel(),np.maximum(1-XYZ[:,:,2],0).ravel()*20]
    lower=[-.8,-1.5,-.4,-100,-10,np.log(3),np.log(.5),np.log(250)]
    upper=[.8,1.5,.4,100,10,np.log(1000),np.log(70),np.log(4000)]
    if distortion:lower+=[-.5];upper+=[.5]
    fits=[]
    for focal,yaw in [(600,0),(1000,0),(1600,0),(1000,.35),(1000,-.35)]:
        depth=20;initial=[0,yaw,0,(center[0]-cx)/focal*depth,(center[1]-cy)/focal*depth,
                         np.log(depth),np.log(12),np.log(focal)]
        if distortion:initial+=[0]
        initial=np.clip(initial,np.array(lower)+1e-6,np.array(upper)-1e-6)
        fit=least_squares(residual,initial,bounds=(lower,upper),loss='soft_l1',f_scale=3,max_nfev=300)
        score=float(np.mean(np.minimum(residual(fit.x)**2,100**2)));fits.append((score,fit))
    score,fit=min(fits,key=lambda x:x[0]);image,XYZ,R,T,f=camera(fit.x)
    K=np.array([[f,0,cx],[0,f,cy],[0,0,1]])
    H=np.linalg.inv(K@np.c_[R[:,0],R[:,2],T])
    return {'available':bool(np.min(XYZ[:,:,2])>0),'estimated_kmh':float(np.exp(fit.x[6])*3.6),
        'method':'rigid_cuboid_bundle_distortion' if distortion else 'rigid_cuboid_bundle',
        'parameters':fit.x.tolist(),'focal_length_pixels':float(f),'radial_k1':float(fit.x[8]) if distortion else 0,
        'mapping':H.tolist(),'support_hull_image':cv2.convexHull(points[:,:4].reshape(-1,2).astype(np.float32)).reshape(-1,2).tolist(),
        'time_interval_s':[float(times[0]),float(times[-1])],'track_id':rows[0]['track_id'],
        'observations':len(rows),'weighted_reprojection_rms':float(np.sqrt(score)),
        'dimensions_m':[length_m,width_m,height_m],'reference_label_used':False}


def silhouette_bundle(boxes,times,width,height,shape='sedan',length_m=4.9,width_m=1.87,height_m=1.45):
    """Fit a rigid constant-motion vehicle envelope directly to detector boxes.

    This avoids inferred hidden cuboid corners. The generic envelope is a size
    prior, not an identified CAD model of the Mercedes.
    """
    boxes=np.asarray(boxes,float);times=np.asarray(times,float)
    keep=(boxes[:,3]-boxes[:,1]>=70)&(boxes[:,3]-boxes[:,1]<=450)&(boxes[:,0]>width*.02)&(boxes[:,2]<width*.98)
    boxes=boxes[keep];times=times[keep]
    if len(boxes)<8:return {'available':False,'reason':'insufficient_unclipped_boxes'}
    selected=np.unique(np.linspace(0,len(boxes)-1,min(60,len(boxes))).astype(int))
    boxes=boxes[selected];times=times[selected];dt=times-times.mean()
    if shape=='cuboid':
        vertices=np.array([[x,y,z] for x in [-width_m/2,width_m/2]
                           for y in [0,-height_m] for z in [0,length_m]])
    else:
        # Front/rear bumper, bonnet, windscreen, roof and rear deck sections.
        sections=[(0,.85,1),(.22,1.0,1),(1.25,1.0,.98),(1.8,height_m,.77),
                  (3.2,height_m,.77),(3.85,1.0,.96),(length_m,.83,1)]
        vertices=np.array([[sign*width_m/2*w,-h,z] for z,h,w in sections for sign in [-1,1]]+
                          [[sign*width_m/2,0,z] for z in [.85,length_m-.85] for sign in [-1,1]])
    cx=width/2;cy=height/2;center=np.median((boxes[:,:2]+boxes[:,2:])/2,axis=0)
    pixel_scale=np.maximum(boxes[:,3]-boxes[:,1],70)
    def camera(p):
        R=cv2.Rodrigues(p[:3])[0];T=np.r_[p[3:5],np.exp(p[5])];v=np.exp(p[6]);f=np.exp(p[7])
        XYZ=vertices[None]@R.T+T-dt[:,None,None]*v*R[:,2]
        xy=XYZ[:,:,:2]/np.maximum(XYZ[:,:,2:],.1)*f+[cx,cy]
        predicted=np.c_[xy.min(axis=1),xy.max(axis=1)]
        return predicted,XYZ,R,T,f
    def residual(p):
        predicted,XYZ,*_=camera(p)
        return np.r_[((predicted-boxes)/pixel_scale[:,None]*200).ravel(),np.maximum(1-XYZ[:,:,2],0).ravel()*20]
    lower=[-.6,-1.5,-.2,-100,-10,np.log(3),np.log(.5),np.log(250)]
    upper=[.6,1.5,.2,100,10,np.log(1000),np.log(70),np.log(4000)]
    fits=[]
    for focal,yaw in [(600,0),(1000,0),(1600,0),(1000,.4),(1000,-.4)]:
        initial=[0,yaw,0,(center[0]-cx)/focal*20,(center[1]-cy)/focal*20,
                 np.log(20),np.log(12),np.log(focal)]
        fit=least_squares(residual,initial,bounds=(lower,upper),loss='soft_l1',f_scale=2,max_nfev=500)
        score=float(np.mean(np.minimum(residual(fit.x)**2,10000)));fits.append((score,fit))
    score,fit=min(fits,key=lambda x:x[0]);predicted,XYZ,R,T,f=camera(fit.x)
    K=np.array([[f,0,cx],[0,f,cy],[0,0,1]])
    H=np.linalg.inv(K@np.c_[R[:,0],R[:,2],T])
    anchors=np.c_[(boxes[:,0]+boxes[:,2])/2,boxes[:,3]]
    return {'available':bool(np.min(XYZ[:,:,2])>0),'estimated_kmh':float(np.exp(fit.x[6])*3.6),
        'method':'silhouette_bundle_'+shape,'parameters':fit.x.tolist(),'mapping':H.tolist(),
        'focal_length_pixels':float(f),'weighted_reprojection_rms':float(np.sqrt(score)),
        'time_interval_s':[float(times[0]),float(times[-1])],'observations':len(boxes),
        'fitted_boxes':predicted.tolist(),'observed_boxes':boxes.tolist(),'times_s':times.tolist(),
        'support_hull_image':cv2.convexHull(anchors.astype(np.float32)).reshape(-1,2).tolist(),
        'dimensions_m':[length_m,width_m,height_m],'reference_label_used':False}


def vp_rigid_bundle(observations,report,vanishing_point,length_m=4.9,width_m=1.87,height_m=1.45,fit_length=False):
    """Rigid camera fit whose translation axis is fixed by visual optical flow."""
    rows=select_rows(observations,report)
    if len(rows)<8:return {'available':False,'reason':'insufficient_geometry'}
    rows=[rows[i] for i in np.unique(np.linspace(0,len(rows)-1,min(36,len(rows))).astype(int))]
    times=np.array([r['time_s'] for r in rows]);dt=times-times.mean()
    base=np.array([[-width_m/2,0,0],[-width_m/2,0,length_m],[width_m/2,0,length_m],[width_m/2,0,0]])
    vertices=np.r_[base,base+[0,-height_m,0]]
    indices=report['ground_indices']+[i for i in range(8) if i not in report['ground_indices']]
    observed=np.array([r['keypoints'] for r in rows])[:,indices,:2]
    pixel_scale=np.array([r['box_height'] for r in rows]);cx=report['width']/2;cy=report['height']/2
    vp=np.asarray(vanishing_point);center=np.median(observed[:,:4].mean(axis=1),axis=0)
    def camera(p):
        roll,tx,ty,logz,logv,logf=p[:6];f=np.exp(logf)
        z=np.r_[(vp-[cx,cy])/f,1];z/=np.linalg.norm(z)
        x=np.cross([0,1,0],z);x/=np.linalg.norm(x);y=np.cross(z,x)
        R=np.c_[x*np.cos(roll)+y*np.sin(roll),-x*np.sin(roll)+y*np.cos(roll),z]
        T=np.array([tx,ty,np.exp(logz)]);v=np.exp(logv)
        current=vertices.copy()
        if fit_length:current[:,2]*=np.exp(p[6])/length_m
        XYZ=current[None]@R.T+T-dt[:,None,None]*v*z
        xy=XYZ[:,:,:2]/np.maximum(XYZ[:,:,2:],.1)*f+[cx,cy]
        return xy,XYZ,R,T,f
    def residual(p):
        xy,XYZ,*_=camera(p)
        values=np.r_[((xy-observed)/pixel_scale[:,None,None]*200).ravel(),np.maximum(1-XYZ[:,:,2],0).ravel()*20]
        return np.r_[values,(p[6]-np.log(length_m))] if fit_length else values
    lower=[-.4,-100,-10,np.log(3),np.log(.5),np.log(250)]
    upper=[.4,100,10,np.log(1000),np.log(70),np.log(4000)]
    if fit_length:lower+=[np.log(2.5)];upper+=[np.log(7.5)]
    fits=[]
    for f in [600,1000,1600]:
        initial=[0,(center[0]-cx)/f*20,(center[1]-cy)/f*20,np.log(20),np.log(12),np.log(f)]
        if fit_length:initial+=[np.log(length_m)]
        fit=least_squares(residual,initial,bounds=(lower,upper),loss='soft_l1',f_scale=3,max_nfev=400)
        score=float(np.mean(np.minimum(residual(fit.x)**2,10000)));fits.append((score,fit))
    score,fit=min(fits,key=lambda x:x[0]);xy,XYZ,R,T,f=camera(fit.x)
    K=np.array([[f,0,cx],[0,f,cy],[0,0,1]]);H=np.linalg.inv(K@np.c_[R[:,0],R[:,2],T])
    return {'available':bool(np.min(XYZ[:,:,2])>0),'estimated_kmh':float(np.exp(fit.x[4])*3.6),
        'method':'optical_flow_vp_rigid_bundle','mapping':H.tolist(),'parameters':fit.x.tolist(),
        'focal_length_pixels':float(f),'vanishing_point_image':vp.tolist(),
        'track_id':rows[0]['track_id'],'time_interval_s':[float(times[0]),float(times[-1])],
        'observations':len(rows),'weighted_reprojection_rms':float(np.sqrt(score)),
        'support_hull_image':cv2.convexHull(observed[:,:4].reshape(-1,2).astype(np.float32)).reshape(-1,2).tolist(),
        'reference_label_used':False,'dimensions_m':[float(np.exp(fit.x[6])) if fit_length else length_m,width_m,height_m],
        'effective_cuboid_length_fitted':fit_length}
