"""Cache speed-blind scene and road correspondences for a reference library."""
import cv2
import numpy as np


def register_scenes(images):
    cv2.setRNGSeed(17)
    names=sorted(images);sift=cv2.SIFT_create(nfeatures=3000,contrastThreshold=.015)
    features={}
    for name in names:
        image=cv2.resize(images[name],(960,540));gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
        kp,des=sift.detectAndCompute(gray,None)
        features[name]=(np.array([k.pt for k in kp],np.float32),des)
    pairs=[]
    for i,reference in enumerate(names):
        if features[reference][1] is None:continue
        matcher=cv2.FlannBasedMatcher(dict(algorithm=1,trees=5),dict(checks=64))
        matcher.add([features[reference][1]]);matcher.train()
        for current in names[i+1:]:
            if features[current][1] is None:continue
            matches=matcher.knnMatch(features[current][1],k=2)
            good=[a for pair in matches if len(pair)==2 for a,b in [pair] if a.distance<.7*b.distance]
            if len(good)<12:continue
            source=np.float32([features[current][0][m.queryIdx] for m in good])
            dest=np.float32([features[reference][0][m.trainIdx] for m in good])
            H,mask=cv2.findHomography(source,dest,cv2.USAC_MAGSAC,1.5)
            if H is None:continue
            keep=mask[:,0].astype(bool);count=int(keep.sum())
            coverage=min(abs(cv2.contourArea(cv2.convexHull(p[keep])))/(960*540) for p in [source,dest]) if count>=3 else 0
            road=keep&(source[:,1]>320)&(dest[:,1]>320)
            pairs.append({'reference':reference,'current':current,'matches':len(good),'inliers':count,
                'ratio':count/len(good),'coverage':coverage,'road_inliers':int(road.sum()),'H_at_960':H.tolist()})
    return pairs


def reference_options(query,flow,calibrations,pairs):
    from longitudinal_calibration import predict_longitudinal
    options=[]
    for pair in pairs:
        if query not in [pair['reference'],pair['current']]:continue
        if pair['inliers']<50 or pair['ratio']<.6 or pair['coverage']<.2 or pair['road_inliers']<15:continue
        other=pair['reference'] if query==pair['current'] else pair['current']
        if other==query or other not in calibrations:continue
        S=np.diag([.5,.5,1]);T=np.linalg.inv(S)@np.array(pair['H_at_960'])@S
        if query==pair['reference']:T=np.linalg.inv(T)
        result=predict_longitudinal(flow,calibrations[other],T)
        if result.get('available'):
            options.append({'reference':other,'score':pair['inliers']*pair['coverage'],
                'prediction':result,'registration':pair})
    return sorted(options,key=lambda r:r['score'],reverse=True)
