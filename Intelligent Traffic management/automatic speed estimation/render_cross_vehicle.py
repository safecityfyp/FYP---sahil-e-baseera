"""Paired videos showing the actual shared camera map and decimal pass speed."""
from pathlib import Path
import json
import cv2
import numpy as np
import render_comparison
from calibrate_speed import project
from shared_camera_calibration import camera_coordinate, corrected_points

ORIGINAL_MARKS=render_comparison.distance_marks


def camera_marks(image,result,flow,scale):
    model=result.get('shared_camera_model')
    components=result.get('geometry_calibration_components')
    if not model and not components:
        return ORIGINAL_MARKS(image,result,flow,scale)
    rows=flow.get('measurements',[])
    if len(rows)<8:return
    points=np.array([r['anchor'] for r in rows]);times=np.array([r['time_s'] for r in rows])
    keep=(times>=result['time_interval_s'][0])&(times<=result['time_interval_s'][1])
    if components:
        points=points[keep]
        if len(points)<8:return
        distance=np.zeros(len(points))
        for component in components:
            prediction=component['prediction']
            if 'mapping' not in prediction:return ORIGINAL_MARKS(image,result,flow,scale)
            f=prediction['focal_length_pixels']
            K=np.array([[f,0,960],[0,f,540],[0,0,1]],float)
            distortion=np.array([prediction.get('radial_k1',0),0,0,0,0],float)
            undistorted=cv2.undistortPoints(points[:,None,:].astype(float),K,distortion,P=K)[:,0,:]
            world=project(undistorted,np.asarray(prediction['mapping']))*component['metric_scale']
            heading=world[-1]-world[0];heading/=max(np.linalg.norm(heading),1e-9)
            distance+=component['weight']*((world-world[0])@heading)
    else:
        aligned=project(points,np.asarray(result['query_to_template']))
        y=corrected_points(aligned,model.get('radial_lambda',0))[:,1]
        low,high=model['support_y_pixels'];keep&=(y>=low)&(y<=high)
        points=points[keep];aligned=aligned[keep]
        if len(points)<8:return
        coordinate=camera_coordinate(aligned,model)
        sign=np.sign(np.median(np.diff(coordinate))) or 1
        distance=sign*(coordinate-coordinate[0])
    points=points*scale
    valid=np.isfinite(distance)&(distance>=0)&(distance<200)
    points=points[valid];distance=distance[valid]
    if len(points)<8:return
    cv2.polylines(image,[points.astype(int)],False,(255,190,0),2)
    order=np.argsort(distance);distance=distance[order];points=points[order]
    for meter in np.arange(0,min(distance.max(),100)+.1,5):
        p=np.array([np.interp(meter,distance,points[:,axis]) for axis in [0,1]])
        cv2.circle(image,tuple(p.astype(int)),4,(255,255,0),-1)
        cv2.putText(image,f'{meter:.0f} m',tuple((p+[8,0]).astype(int)),cv2.FONT_HERSHEY_SIMPLEX,.48,(0,0,0),3)
        cv2.putText(image,f'{meter:.0f} m',tuple((p+[8,0]).astype(int)),cv2.FONT_HERSHEY_SIMPLEX,.48,(255,255,0),1)


def render(video,folder,inference,result,reference_kmh,flow,phase):
    render_comparison.distance_marks=camera_marks
    try:render_comparison.render_pair(video,folder,inference,result,reference_kmh,flow)
    finally:render_comparison.distance_marks=ORIGINAL_MARKS
    path=Path(folder)/'render_report.json'
    report=json.loads(path.read_text(encoding='utf-8'))
    report.update(phase=phase,calibration_method=result.get('adaptation',result.get('method')),
                  reference_videos=result.get('reference_videos',[]),
                  own_reference_speed_used=False,
                  distance_marks_use_fitted_shared_camera=bool(result.get('shared_camera_model')))
    report['distance_marks_use_fitted_vehicle_camera']=bool(result.get('geometry_calibration_components'))
    path.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
