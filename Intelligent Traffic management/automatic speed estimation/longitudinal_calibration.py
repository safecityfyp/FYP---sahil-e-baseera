"""One-dimensional road-distance calibration using reference-pass optical flow.

For straight road motion with a horizontal horizon, longitudinal distance is
proportional to reciprocal height above that horizon. A known reference pass
provides metric scale; a query video's own speed is never an input.
"""
import numpy as np
from scipy.optimize import least_squares
from calibrate_speed import project
from refine_flow import flow_vanishing_point


def fit_longitudinal_reference(flow,reference_kmh):
    rows=flow.get('measurements',[])
    if len(rows)<12:return {'available':False,'reason':'insufficient_reference_motion'}
    vp=flow_vanishing_point(flow)
    if not vp['available']:return vp
    t=np.array([r['time_s'] for r in rows]);low,high=np.quantile(t,[.1,.9])
    rows=[r for r in rows if low<=r['time_s']<=high]
    p=np.array([r['anchor'] for r in rows]);q=np.array([r['transported_anchor'] for r in rows])
    dt=np.array([r['dt_s'] for r in rows]);horizon=vp['point'][1]
    def factors(h):return np.abs(1/(q[:,1]-h)-1/(p[:,1]-h))/dt
    target=reference_kmh/3.6;initial_scale=target/max(np.median(factors(horizon)),1e-9)
    max_h=min(np.min(p[:,1]),np.min(q[:,1]))-20
    lower=min(horizon-80,max_h-150);upper=min(horizon+80,max_h)
    def residual(parameters):
        h,loga=parameters
        return np.r_[(np.exp(loga)*factors(h)/target-1), (h-horizon)/40*.04]
    fit=least_squares(residual,[min(horizon,upper-1e-5),np.log(initial_scale)],
        bounds=([lower,np.log(1)],[upper,np.log(1e8)]),loss='soft_l1',f_scale=.05,max_nfev=500)
    h=float(fit.x[0]);a=float(np.exp(fit.x[1]))
    # Same median estimator is used for calibration and subsequent queries.
    a*=target/np.median(a*factors(h))
    return {'available':True,'horizon_y':h,'distance_coefficient_meter_pixels':a,
        'flow_vanishing_point':vp,'reference_kmh':reference_kmh,
        'reference_motion_relative_mad':float(np.median(abs(a*factors(h)-target))/target),
        'support_y_pixels':[float(min(p[:,1].min(),q[:,1].min())),float(max(p[:,1].max(),q[:,1].max()))],
        'assumption':'Locally straight longitudinal motion; reference-image horizon approximately horizontal',
        'method':'reciprocal_road_coordinate_reference_calibration'}


def predict_longitudinal(flow,calibration,query_to_reference):
    if not calibration.get('available'):return {'available':False,'reason':'reference_calibration_unavailable'}
    rows=flow.get('measurements',[])
    if len(rows)<8:return {'available':False,'reason':'insufficient_query_flow'}
    p=project([r['anchor'] for r in rows],query_to_reference)
    q=project([r['transported_anchor'] for r in rows],query_to_reference)
    h=calibration['horizon_y'];dt=np.array([r['dt_s'] for r in rows])
    t=np.array([r['time_s'] for r in rows]);lo,hi=np.quantile(t,[.1,.9])
    low,high=calibration['support_y_pixels'];margin=(high-low)*.1
    keep=(t>=lo)&(t<=hi)&(p[:,1]>h+20)&(q[:,1]>h+20)&(p[:,1]>=low-margin)&(p[:,1]<=high+margin)
    if keep.sum()<8:return {'available':False,'reason':'query_outside_reference_road_support'}
    speed=np.abs(1/(q[:,1]-h)-1/(p[:,1]-h))/dt*calibration['distance_coefficient_meter_pixels']*3.6
    median=np.median(speed[keep]);mad=np.median(abs(speed[keep]-median))
    keep&=abs(speed-median)<=max(4*1.4826*mad,2)
    if keep.sum()<8:return {'available':False,'reason':'insufficient_consistent_query_flow'}
    return {'available':True,'estimated_kmh':float(np.median(speed[keep])),
        'observations':int(keep.sum()),'track_id':flow['track_id'],
        'time_interval_s':[float(t[keep].min()),float(t[keep].max())],
        'method':'registered_reciprocal_reference_flow','reference_label_used':False,
        'query_to_reference':np.asarray(query_to_reference).tolist(),
        'reference_road_calibration':calibration,'per_frame_kmh':speed.tolist(),
        'per_frame_times_s':t.tolist(),'per_frame_keep':keep.tolist()}
