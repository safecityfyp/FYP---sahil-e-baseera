"""Render separate longitudinal-calibration and decimal-speed review videos."""
from pathlib import Path
import json,subprocess
import cv2
import numpy as np
from calibrate_speed import project


def distance_marks(image,result,flow,scale):
    rows=flow.get('measurements',[])
    if len(rows)<8:return
    points=np.array([r['anchor'] for r in rows]);times=np.array([r['time_s'] for r in rows])
    if result.get('calibration_reused'):
        components=result.get('distance_calibration_components',[{'weight':1,
            'query_to_reference':result['query_to_reference'],'calibration':result['reference_road_calibration']}])
        distance=np.zeros(len(points))
        for component in components:
            reference=project(points,np.array(component['query_to_reference']))
            calibration=component['calibration'];h=calibration['horizon_y']
            coordinate=calibration['distance_coefficient_meter_pixels']/(reference[:,1]-h)
            sign=np.sign(np.median(np.diff(coordinate))) or 1
            distance+=component['weight']*sign*(coordinate-coordinate[0])
        weight=result.get('library_weight',1)
        geometry=result.get('geometry_component_kmh',result['estimated_kmh'])/3.6*(times-times[0])
        distance=weight*distance+(1-weight)*geometry
    else:
        distance=result['estimated_kmh']/3.6*(times-times[0])
    valid=np.isfinite(distance)&(distance>=0)&(distance<200)
    points=points[valid]*scale;distance=distance[valid]
    if len(points)<8:return
    cv2.polylines(image,[points.astype(int)],False,(255,190,0),2)
    order=np.argsort(distance);distance=distance[order];points=points[order]
    if np.ptp(distance)<5:return
    for meter in np.arange(0,min(distance.max(),100)+.1,5):
        p=np.array([np.interp(meter,distance,points[:,axis]) for axis in [0,1]])
        cv2.circle(image,tuple(p.astype(int)),4,(255,255,0),-1)
        cv2.putText(image,f'{meter:.0f} m',tuple((p+[8,0]).astype(int)),cv2.FONT_HERSHEY_SIMPLEX,.48,(0,0,0),3)
        cv2.putText(image,f'{meter:.0f} m',tuple((p+[8,0]).astype(int)),cv2.FONT_HERSHEY_SIMPLEX,.48,(255,255,0),1)


def render_pair(video,folder,inference,result,reference_kmh,flow):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);inference=Path(inference)
    observations=json.loads((inference/'observations.json').read_text())
    report=json.loads((inference/'geometry_run_report.json').read_text())
    tracks=json.loads((inference/'tracks.json').read_text())
    geometry={};boxes={}
    for r in observations:geometry.setdefault(r['frame_index'],[]).append(r)
    for r in tracks:boxes.setdefault(r['frame_index'],[]).append(r)
    cap=cv2.VideoCapture(str(video));assert cap.isOpened()
    fps=float(cap.get(cv2.CAP_PROP_FPS));size=(1280,720)
    scale=np.array([1280/report['width'],720/report['height']])
    writers={name:cv2.VideoWriter(str(folder/(name+'.avi')),cv2.VideoWriter_fourcc(*'MJPG'),fps,size)
             for name in ['calibration','speed']}
    assert all(w.isOpened() for w in writers.values())
    interval=result['time_interval_s'];speed=result['estimated_kmh'];index=0;labelled=0
    try:
        while True:
            ok,source=cap.read()
            if not ok:break
            calibration=cv2.resize(source,size);speed_image=calibration.copy()
            distance_marks(calibration,result,flow,scale)
            for r in geometry.get(index,[]):
                points=np.array(r['keypoints'])[report['ground_indices'],:2]*scale
                cv2.polylines(calibration,[points.astype(int)],True,(0,255,0),2)
                for node,p in enumerate(points):
                    cv2.circle(calibration,tuple(p.astype(int)),4,(0,255,255),-1)
                    cv2.putText(calibration,str(node),tuple((p+[6,-6]).astype(int)),cv2.FONT_HERSHEY_SIMPLEX,.45,(0,255,255),1)
            for r in boxes.get(index,[]):
                points=np.array(r['box']).reshape(2,2)*scale
                active=r['track_id']==result.get('track_id') and interval[0]<=index/fps<=interval[1]
                color=(0,255,255) if active else (160,160,160)
                cv2.rectangle(speed_image,tuple(points[0].astype(int)),tuple(points[1].astype(int)),color,2)
                if active:
                    labelled+=1;position=(max(5,int(points[0,0])),max(98,int(points[0,1])-7))
                    cv2.putText(speed_image,f'{speed:.1f} km/h',position,cv2.FONT_HERSHEY_SIMPLEX,.85,(0,0,0),4)
                    cv2.putText(speed_image,f'{speed:.1f} km/h',position,cv2.FONT_HERSHEY_SIMPLEX,.85,color,2)
            for image in [calibration,speed_image]:
                cv2.rectangle(image,(0,0),(1280,78),(20,20,20),-1)
                cv2.rectangle(image,(0,677),(1280,720),(20,20,20),-1)
            cv2.putText(calibration,'CALIBRATION REVIEW | vehicle nodes and local road distance',(15,29),cv2.FONT_HERSHEY_SIMPLEX,.68,(0,220,255),2)
            reused=result.get('calibration_reused',False)
            subtitle='Reused reference calibration + new vehicle geometry' if reused else 'New calibration from vehicle geometry + visual motion'
            cv2.putText(calibration,subtitle,(15,60),cv2.FONT_HERSHEY_SIMPLEX,.58,(235,235,235),1)
            footer='Other reference passes calibrate the scale. This test video is excluded.' if reused else 'Car-size prior and constant-motion fit. Distances are local hypotheses.'
            cv2.putText(calibration,footer,(15,704),cv2.FONT_HERSHEY_SIMPLEX,.55,(230,230,230),1)
            cv2.putText(speed_image,f'Estimated pass speed: {speed:.1f} km/h',(15,31),cv2.FONT_HERSHEY_SIMPLEX,.82,(0,255,255),2)
            cv2.putText(speed_image,f'Average over source t={interval[0]:.2f}-{interval[1]:.2f} s | Development test',(15,62),cv2.FONT_HERSHEY_SIMPLEX,.57,(230,230,230),1)
            cv2.putText(speed_image,f'Cruise-control reference: {reference_kmh:.1f} km/h | Signed error: {speed-reference_kmh:+.1f} km/h',(15,704),cv2.FONT_HERSHEY_SIMPLEX,.62,(230,230,230),1)
            writers['calibration'].write(calibration);writers['speed'].write(speed_image)
            if index==round(sum(interval)/2*fps):
                cv2.imwrite(str(folder/'calibration_example.jpg'),calibration)
                cv2.imwrite(str(folder/'speed_example.jpg'),speed_image)
            index+=1
    finally:
        cap.release()
        for writer in writers.values():writer.release()
    for name in writers:
        raw=folder/(name+'.avi')
        subprocess.run(['ffmpeg','-y','-loglevel','error','-i',str(raw),'-c:v','libx264','-crf','25',
            '-pix_fmt','yuv420p','-movflags','+faststart',str(folder/(name+'.mp4'))],check=True)
        raw.unlink()
    (folder/'render_report.json').write_text(json.dumps({'frames':index,'fps':fps,'duration_s':index/fps,
        'speed_display_decimal_places':1,'vehicle_label_frames':labelled,
        'files':['calibration.mp4','speed.mp4'],'scope':'Longitudinal road-distance review; not a full road survey'},indent=2),encoding='utf-8')
