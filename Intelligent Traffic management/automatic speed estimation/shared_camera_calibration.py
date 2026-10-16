"""Reference-assisted camera maps fitted jointly across known-speed passes.

The input speed dictionary contains calibration passes only. Query speed is never
an argument. A camera map is reused after lower-image scene registration; each
prediction stays within the calibrated image support. These models assume a
straight, approximately horizontal road and constant speed during each pass.
"""
import cv2
import numpy as np
from scipy.optimize import least_squares
from calibrate_speed import project


def foreground_registration(reference, current):
    """Align lower-image ground texture, avoiding a homography dominated by sky."""
    cv2.setRNGSeed(17)
    a = cv2.resize(reference, (960, 540))
    b = cv2.resize(current, (960, 540))
    mask = np.zeros((540, 960), np.uint8)
    mask[300:530, 15:945] = 255
    sift = cv2.SIFT_create(nfeatures=6000, contrastThreshold=.01)
    ka, da = sift.detectAndCompute(cv2.cvtColor(a, cv2.COLOR_BGR2GRAY), mask)
    kb, db = sift.detectAndCompute(cv2.cvtColor(b, cv2.COLOR_BGR2GRAY), mask)
    if da is None or db is None:
        return {'accepted': False, 'reason': 'insufficient_foreground_texture'}
    pairs = cv2.BFMatcher().knnMatch(db, da, k=2)
    good = [x for pair in pairs if len(pair) == 2 for x, y in [pair] if x.distance < .7*y.distance]
    if len(good) < 15:
        return {'accepted': False, 'reason': 'insufficient_foreground_matches', 'matches': len(good)}
    p = np.float32([kb[m.queryIdx].pt for m in good])
    q = np.float32([ka[m.trainIdx].pt for m in good])
    H, inliers = cv2.findHomography(p, q, cv2.USAC_MAGSAC, 1.5)
    if H is None:
        return {'accepted': False, 'reason': 'foreground_homography_failed'}
    keep = inliers[:, 0].astype(bool)
    count = int(keep.sum())
    coverage = min(abs(cv2.contourArea(cv2.convexHull(x[keep])))/(960*540) for x in [p,q]) if count >= 3 else 0
    rms = float(np.sqrt(np.mean(np.sum((project(p[keep], H)-q[keep])**2, axis=1))))
    accepted = count >= 20 and count/len(good) >= .6 and coverage >= .025 and rms <= 1.5
    S = np.diag([.5, .5, 1])
    return {'accepted': bool(accepted), 'matches': len(good), 'inliers': count,
            'coverage': coverage, 'rms_pixels_at_960': rms,
            'query_to_template': (np.linalg.inv(S)@H@S).tolist(),
            'scope': 'Lower-image planar texture; this heuristic is not semantic road segmentation.'}


def aligned_measurements(flow, transform):
    rows = flow.get('measurements', [])
    if len(rows) < 8:
        return None
    p = project([r['anchor'] for r in rows], np.asarray(transform))
    q = project([r['transported_anchor'] for r in rows], np.asarray(transform))
    t = np.array([r['time_s'] for r in rows])
    dt = np.array([r['dt_s'] for r in rows])
    keep = np.isfinite(p).all(axis=1) & np.isfinite(q).all(axis=1) & (dt > 0)
    keep &= np.array([r.get('inliers', 0) >= 6 for r in rows])
    keep &= np.array([r.get('flow_rms_pixels', 0) <= 2 for r in rows])
    if keep.sum() < 8:
        return None
    low, high = np.quantile(t[keep], [.1, .9])
    keep &= (t >= low) & (t <= high)
    if keep.sum() < 8:
        return None
    return {'p': p[keep], 'q': q[keep], 't': t[keep], 'dt': dt[keep],
            'track_id': flow.get('track_id')}


def corrected_points(points, radial_lambda=0):
    points = np.asarray(points)
    offset = (points-[960, 540])/1920
    denominator = 1+radial_lambda*np.sum(offset**2, axis=1)
    return offset/denominator[:, None]*1920+[960, 540]


def camera_coordinate(points, model):
    p = corrected_points(points, model.get('radial_lambda', 0))
    y = p[:, 1]
    if model['family'] == 'scale_curve':
        return np.interp(y, model['coordinate_y_pixels'], model['coordinate_meters'])
    return model['distance_coefficient_meter_pixels']/(y-model['horizon_y'])


def _reference_data(flows, speeds, transforms):
    data = []
    for name in sorted(speeds):
        if name not in flows or name not in transforms:
            continue
        r = aligned_measurements(flows[name], transforms[name])
        if r is not None:
            data.append({**r, 'video': name, 'reference_mps': speeds[name]/3.6})
    return data


def fit_shared_camera(flows, speeds, transforms, family='trajectory', degree=2):
    """Fit a camera using reference speeds only, balancing contributions per pass."""
    data = _reference_data(flows, speeds, transforms)
    if len(data) < 2:
        return {'available': False, 'reason': 'fewer_than_two_compatible_calibration_passes'}
    all_y = np.concatenate([r['p'][:, 1] for r in data])
    low_y, high_y = float(all_y.min()), float(all_y.max())
    if family == 'scale_curve':
        center = float(np.median(all_y)); scale = max(float(np.ptp(all_y))/2, 50)
        ys=[]; targets=[]; weights=[]
        for row in data:
            displacement=np.abs(row['q'][:,1]-row['p'][:,1])/row['dt']
            keep=displacement>.5
            ys.extend(row['p'][keep,1]); targets.extend(np.log(row['reference_mps']/displacement[keep]))
            weights.extend([1/np.sqrt(max(keep.sum(),1))]*int(keep.sum()))
        ys=np.asarray(ys);targets=np.asarray(targets);weights=np.asarray(weights)
        if len(ys)<20:return {'available':False,'reason':'insufficient_curve_samples'}
        X=np.vander((ys-center)/scale,degree+1,increasing=True)
        initial=np.linalg.lstsq(X*weights[:,None],targets*weights,rcond=None)[0]
        def residual(c):return np.r_[(X@c-targets)*weights, c[2:]*.025]
        fit=least_squares(residual,initial,loss='soft_l1',f_scale=.03,max_nfev=500)
        grid=np.linspace(low_y,high_y,512)
        meters_per_pixel=np.exp(np.vander((grid-center)/scale,degree+1,increasing=True)@fit.x)
        coordinate=np.r_[0,np.cumsum((meters_per_pixel[:-1]+meters_per_pixel[1:])*.5*np.diff(grid))]
        return {'available':True,'family':family,'degree':degree,'curve_coefficients':fit.x.tolist(),
                'curve_center_y':center,'curve_scale_y':scale,'coordinate_y_pixels':grid.tolist(),
                'coordinate_meters':coordinate.tolist(),'meters_per_y_pixel':meters_per_pixel.tolist(),
                'support_y_pixels':[low_y,high_y],'reference_videos':[r['video'] for r in data],
                'reference_label_used':True,'query_reference_label_used':False}
    radial = family == 'trajectory_radial'
    upper_h = low_y-20
    initial_h = min(500, upper_h-30)
    factors = []
    for row in data:
        c=1/(row['p'][:,1]-initial_h)
        slope=abs(np.polyfit(row['t'],c,1)[0])
        if slope>1e-8:factors.append(row['reference_mps']/slope)
    initial_a=float(np.median(factors)) if factors else 10000
    initial=[initial_h,np.log(np.clip(initial_a,1,1e8))]+([0] if radial else [])
    lower=[-540,np.log(1)]+([-.75] if radial else [])
    upper=[upper_h,np.log(1e8)]+([.75] if radial else [])
    def residual(parameters):
        h,loga=parameters[:2];a=np.exp(loga);lam=parameters[2] if radial else 0
        result=[]
        for row in data:
            p=corrected_points(row['p'],lam);den=p[:,1]-h
            if family == 'flow':
                q=corrected_points(row['q'],lam)
                v=a*np.abs(1/np.maximum(q[:,1]-h,10)-1/np.maximum(den,10))/row['dt']
                r=v/row['reference_mps']-1
            else:
                z=a/np.maximum(den,10);t=row['t']-row['t'].mean()
                sign=np.sign(np.polyfit(t,z,1)[0]) or 1
                r=(z-z.mean()-sign*row['reference_mps']*t)/row['reference_mps']
            result.extend(r/np.sqrt(len(r)))
            result.extend(np.minimum(den-10,0)/np.sqrt(len(den)))
        if radial:result.append(lam*.002)
        return np.asarray(result)
    fit=least_squares(residual,initial,bounds=(lower,upper),loss='soft_l1',
                      f_scale=.01 if family!='flow' else .04,max_nfev=1000)
    lam=float(fit.x[2]) if radial else 0
    bound=radial and abs(lam)>.745
    coordinates=np.concatenate([corrected_points(r['p'],lam)[:,1] for r in data])
    if min(coordinates)-fit.x[0]<15:return {'available':False,'reason':'mapping_pole_near_calibrated_path'}
    return {'available':not bound,'reason':'radial_parameter_at_bound' if bound else 'fitted',
            'family':family,'horizon_y':float(fit.x[0]),
            'distance_coefficient_meter_pixels':float(np.exp(fit.x[1])),
            'radial_lambda':lam,'support_y_pixels':[float(coordinates.min()),float(coordinates.max())],
            'reference_videos':[r['video'] for r in data],
            'fit_residual_rms':float(np.sqrt(np.mean(residual(fit.x)**2))),
            'reference_label_used':True,'query_reference_label_used':False,
            'assumption':'One shared longitudinal camera map, approximately horizontal road horizon.'}


def predict_shared_camera(flow, model, transform):
    if not model.get('available'):
        return {'available':False,'reason':model.get('reason','unavailable_camera_map')}
    row=aligned_measurements(flow,transform)
    if row is None:return {'available':False,'reason':'insufficient_query_measurements'}
    p=row['p'];q=row['q'];t=row['t'];dt=row['dt']
    y=corrected_points(p,model.get('radial_lambda',0))[:,1]
    low,high=model['support_y_pixels'];margin=(high-low)*.05
    keep=(y>=low-margin)&(y<=high+margin)
    if model['family']=='scale_curve':keep=(y>=low)&(y<=high)
    if keep.sum()<8:return {'available':False,'reason':'query_outside_shared_camera_support'}
    z=camera_coordinate(p,model)
    if model['family'] in ['flow','scale_curve']:
        after=camera_coordinate(q,model);values=np.abs(after-z)/dt*3.6
        median=np.median(values[keep]);mad=np.median(abs(values[keep]-median))
        keep&=abs(values-median)<=max(4*1.4826*mad,2)
        if keep.sum()<8:return {'available':False,'reason':'inconsistent_query_flow'}
        speed=float(np.median(values[keep]));rms=None
    else:
        times=t[keep]-t[keep].mean();positions=z[keep]
        initial=np.polyfit(times,positions,1)
        fit=least_squares(lambda p:p[0]*times+p[1]-positions,initial,loss='soft_l1',f_scale=.15,max_nfev=300)
        speed=float(abs(fit.x[0])*3.6)
        rms=float(np.sqrt(np.mean((fit.x[0]*times+fit.x[1]-positions)**2)))
    return {'available':True,'estimated_kmh':speed,'method':'shared_camera_'+model['family'],
            'track_id':row['track_id'],'time_interval_s':[float(t[keep].min()),float(t[keep].max())],
            'observations':int(keep.sum()),'trajectory_rms_m':rms,'calibration_reused':True,
            'reference_videos':model['reference_videos'],'shared_camera_model':model,
            'query_to_template':np.asarray(transform).tolist(),'query_reference_speed_used':False,
            'own_reference_excluded':True}
