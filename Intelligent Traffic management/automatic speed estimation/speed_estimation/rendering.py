"""Render calibration replay and complete CCTV speed videos without AVI buffers.

Full source frame rates are retained. Speed recordings are split into ten-minute
MP4s so the complete output can be reviewed on GitHub within its file-size limit.
"""
from bisect import bisect_left
from collections import defaultdict
import json
from pathlib import Path
import subprocess

import cv2
import numpy as np

from .geometry import project
from .calibration import read_rows


COLORS=[(40,220,240),(255,190,70),(160,220,100)]


def clock(seconds):
    seconds=max(0,int(seconds));return f'{seconds//3600:02d}:{seconds//60%60:02d}:{seconds%60:02d}'


def grid_overlay(calibration,size):
    width,height=size;scale=np.array([width/calibration['width'],height/calibration['height']])
    grid=np.zeros((height,width,3),np.uint8);regions=[]
    for i,(name,mapping) in enumerate(calibration['regions'].items()):
        color=COLORS[i%len(COLORS)]
        if not mapping.get('accepted'):continue
        H=np.asarray(mapping['H_image_to_experimental_meters']);hull=np.asarray(mapping['support_hull_image'])
        polygon=np.round(hull*scale).astype(np.int32)
        mask=np.zeros((height,width),np.uint8);cv2.fillPoly(mask,[polygon],255)
        road=np.zeros_like(mask)
        roi=np.round(np.asarray(calibration['profile']['regions'][name])*[width,height]).astype(np.int32)
        cv2.fillPoly(road,[roi],255);mask=cv2.bitwise_and(mask,road)
        world=project(hull,H);lo=np.floor(world.min(axis=0)/5)*5;hi=np.ceil(world.max(axis=0)/5)*5
        layer=np.zeros_like(grid)
        for axis in [0,1]:
            values=np.arange(lo[axis],hi[axis]+.1,5)
            if len(values)>120:values=np.linspace(lo[axis],hi[axis],60)
            for value in values:
                line=np.array([[lo[0],lo[1]],[hi[0],hi[1]]])
                line[:,axis]=value
                points=project(line,np.linalg.inv(H))*scale
                if np.isfinite(points).all() and abs(points).max()<1e7:
                    cv2.line(layer,tuple(np.round(points[0]).astype(int)),tuple(np.round(points[1]).astype(int)),color,1,cv2.LINE_AA)
        grid[mask>0]=layer[mask>0]
        border=np.zeros_like(grid);cv2.polylines(border,[polygon],True,color,2,cv2.LINE_AA)
        grid[(mask>0)&np.any(border>0,axis=2)]=border[(mask>0)&np.any(border>0,axis=2)]
        regions.append(dict(region=name,support_world_span_m=(world.max(axis=0)-world.min(axis=0)).tolist(),
                            calibration_s=mapping['calibration_end_s'],car_tracks=len(mapping['track_ids'])))
    return grid,regions


def label(frame,text,point,color,small=False):
    font=.45 if small else .62;thickness=1 if small else 2
    width,height=frame.shape[1],frame.shape[0]
    (tw,th),baseline=cv2.getTextSize(text,cv2.FONT_HERSHEY_SIMPLEX,font,thickness)
    x=max(2,min(int(point[0]),width-tw-6));y=max(th+3,min(int(point[1]),height-baseline-4))
    cv2.rectangle(frame,(x-2,y-th-3),(x+tw+3,y+baseline+2),(15,15,15),-1)
    cv2.putText(frame,text,(x,y),cv2.FONT_HERSHEY_SIMPLEX,font,color,thickness,cv2.LINE_AA)


def sample_at(records,times,time_s,max_distance=.30):
    j=bisect_left(times,time_s)
    candidates=[k for k in [j-1,j] if 0<=k<len(records)]
    if not candidates:return None
    k=min(candidates,key=lambda k:abs(times[k]-time_s))
    if abs(times[k]-time_s)>max_distance:return None
    return records[k]


def encoder(path,width,height,fps,segmented=False,codec='libx264'):
    args=['ffmpeg','-hide_banner','-loglevel','error','-y','-f','rawvideo','-pix_fmt','bgr24',
          '-s',f'{width}x{height}','-r',str(fps),'-i','pipe:0','-an']
    if codec=='h264_nvenc':
        args+=['-c:v','h264_nvenc','-preset','p5','-rc','vbr','-cq','28','-b:v','0']
    else:args+=['-c:v','libx264','-preset','fast','-crf','30','-threads','2']
    args+=['-pix_fmt','yuv420p']
    if segmented:
        args+=['-force_key_frames','expr:gte(t,n_forced*600)','-f','segment','-segment_time','600',
               '-reset_timestamps','1','-segment_format_options','movflags=+faststart']
    else:args+=['-movflags','+faststart']
    return subprocess.Popen(args+[str(path)],stdin=subprocess.PIPE,stderr=subprocess.PIPE)


def render(video,inputs,calibration_file,speed_folder,output,duration=None,codec='libx264'):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    calibration=json.loads(Path(calibration_file).read_text());speed_folder=Path(speed_folder)
    speed_report=json.loads((speed_folder/'speed_report.json').read_text())
    tracks=defaultdict(list);observations=defaultdict(list);speeds=defaultdict(list)
    detection_frames=set()
    for folder in inputs:
        for r in read_rows(folder,'tracks.jsonl.gz'):
            tracks[r['frame_index']].append(r);detection_frames.add(r['frame_index'])
        for r in read_rows(folder,'observations.jsonl.gz'):observations[r['track_id']].append(r)
    for r in read_rows(speed_folder,'speeds.jsonl.gz'):speeds[r['track_id']].append(r)
    for group in list(speeds.values())+list(observations.values()):group.sort(key=lambda r:r['time_s'])
    speed_times={tid:[r['time_s'] for r in group] for tid,group in speeds.items()}
    observation_times={tid:[r['time_s'] for r in group] for tid,group in observations.items()}
    cap=cv2.VideoCapture(str(video));assert cap.isOpened()
    fps=float(cap.get(cv2.CAP_PROP_FPS));total=int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    expected_frames=total if duration is None else min(total,int(round(duration*fps)))
    width,height=1280,720;scale=np.array([width/calibration['width'],height/calibration['height']])
    grid,region_info=grid_overlay(calibration,(width,height))
    grid_mask=np.any(grid>0,axis=2)
    calibration_frames=min(expected_frames,int(round(calibration['calibration_duration_s']*fps)))
    speed_encoder=encoder(output/'speed_%02d.mp4',width,height,fps,True,codec)
    calibration_encoder=encoder(output/'calibration.mp4',width,height,fps,codec=codec)
    current=[];index=0;labelled_frames=0;labelled_ids=set();examples=[];counts={}
    name=calibration['profile']['display_name']
    region_colors={k:COLORS[i%len(COLORS)] for i,k in enumerate(calibration['regions'])}
    try:
        while index<expected_frames:
            ok,source=cap.read()
            if not ok:break
            time_s=index/fps
            base=cv2.resize(source,(width,height),interpolation=cv2.INTER_AREA)
            if index in tracks:current=tracks[index]
            shown=[r for r in current if index-r['frame_index']<=fps*.16 and r.get('region')]
            speed_frame=base.copy();n=0
            for r in shown:
                tid=r['track_id'];box=np.round(np.array(r['box'])*np.r_[scale,scale]).astype(int)
                speed=sample_at(speeds[tid],speed_times.get(tid,[]),time_s,.35) if tid in speeds else None
                color=(70,220,110) if speed else (170,170,170)
                cv2.rectangle(speed_frame,tuple(box[:2]),tuple(box[2:]),color,2 if speed else 1)
                if speed:
                    value=f'#{tid}  {speed["experimental_kmh"]:.1f} km/h'
                    label(speed_frame,value,(box[0],box[1]-24),color)
                    label(speed_frame,f'approx {speed["sensitivity_low_kmh"]:.1f}-{speed["sensitivity_high_kmh"]:.1f}',(box[0],box[1]-5),color,True)
                    n+=1;labelled_ids.add(tid)
                elif r.get('moving'):
                    label(speed_frame,f'#{tid} tracked | no qualified speed',(box[0],box[1]-5),color,True)
            if n:labelled_frames+=1
            cv2.rectangle(speed_frame,(0,0),(width,90),(12,12,12),-1)
            cv2.putText(speed_frame,f'SPEED ESTIMATES | {name} | {clock(time_s)} / {clock(total/fps)}',(14,29),cv2.FONT_HERSHEY_SIMPLEX,.65,(255,255,255),2,cv2.LINE_AA)
            cv2.putText(speed_frame,'Experimental km/h | car-dimension prior | accuracy not independently measured',(14,58),cv2.FONT_HERSHEY_SIMPLEX,.49,(100,215,255),1,cv2.LINE_AA)
            speed_encoder.stdin.write(speed_frame.tobytes())
            if n and (not examples or time_s-examples[-1]['time_s']>=300):
                path=output/f'speed_example_{len(examples):02d}.jpg';cv2.imwrite(str(path),speed_frame)
                examples.append(dict(time_s=time_s,file=path.name,labels=n))
            if index<calibration_frames:
                calibration_frame=base.copy()
                calibration_frame[grid_mask]=cv2.addWeighted(base,.35,grid,.65,0)[grid_mask]
                for r in shown:
                    tid=r['track_id'];group=observations.get(tid,[])
                    obs=sample_at(group,observation_times.get(tid,[]),time_s,.25) if group else None
                    if obs is None:continue
                    quad=np.array(obs['keypoints'])[calibration['ground_order']['indices'],:2]*scale
                    color=region_colors.get(r['region'],(180,180,180))
                    cv2.polylines(calibration_frame,[np.round(quad).astype(np.int32)],True,color,2,cv2.LINE_AA)
                    for j,point in enumerate(quad):
                        point=tuple(np.round(point).astype(int));cv2.circle(calibration_frame,point,4,color,-1)
                        cv2.putText(calibration_frame,str(j+1),(point[0]+4,point[1]-4),cv2.FONT_HERSHEY_SIMPLEX,.4,color,1,cv2.LINE_AA)
                cv2.rectangle(calibration_frame,(0,0),(width,100),(12,12,12),-1)
                cv2.putText(calibration_frame,f'CALIBRATION REPLAY | {name} | {clock(time_s)} / {clock(calibration_frames/fps)}',(14,28),cv2.FONT_HERSHEY_SIMPLEX,.61,(255,255,255),2,cv2.LINE_AA)
                text=' | '.join(f'{k.replace("_"," ")}: {len(v["track_ids"])} cars, {v.get("method","unavailable")}' for k,v in calibration['regions'].items())
                cv2.putText(calibration_frame,text,(14,55),cv2.FONT_HERSHEY_SIMPLEX,.46,(100,215,255),1,cv2.LINE_AA)
                cv2.putText(calibration_frame,'Final fitted road grid: 5 m spacing | car ground nodes 1-4 | prior 4.5 x 1.8 m',(14,82),cv2.FONT_HERSHEY_SIMPLEX,.46,(225,225,225),1,cv2.LINE_AA)
                calibration_encoder.stdin.write(calibration_frame.tobytes())
                if index==min(calibration_frames-1,int(60*fps)):
                    cv2.imwrite(str(output/'calibration_example.jpg'),calibration_frame)
            if index==calibration_frames-1:
                calibration_encoder.stdin.close()
                error=calibration_encoder.stderr.read().decode(errors='replace');code=calibration_encoder.wait()
                assert code==0,error
            index+=1
            if index%int(fps*300)==0:
                print('Rendered',calibration['camera_id'],clock(time_s),'of',clock(total/fps),'labelled frames',labelled_frames,flush=True)
    finally:
        cap.release()
        if not speed_encoder.stdin.closed:speed_encoder.stdin.close()
        if not calibration_encoder.stdin.closed:calibration_encoder.stdin.close()
    error=speed_encoder.stderr.read().decode(errors='replace');code=speed_encoder.wait();assert code==0,error
    if calibration_encoder.poll() is None:
        error=calibration_encoder.stderr.read().decode(errors='replace');code=calibration_encoder.wait();assert code==0,error
    assert index==expected_frames,f'Source decoded {index}/{expected_frames} frames'
    files=[]
    for path in sorted(output.glob('*.mp4')):
        result=subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-show_entries',
                               'stream=nb_frames,r_frame_rate,duration,width,height','-of','json',str(path)],capture_output=True,text=True,check=True)
        stream=json.loads(result.stdout)['streams'][0]
        files.append(dict(file=path.name,bytes=path.stat().st_size,**stream))
    speed_files=[r for r in files if r['file'].startswith('speed_')]
    rendered_frames=sum(int(r['nb_frames']) for r in speed_files)
    assert rendered_frames==expected_frames,(rendered_frames,expected_frames)
    report=dict(camera_id=calibration['camera_id'],source_sha256=calibration['source_sha256'],source_frames=total,
                speed_rendered_frames=rendered_frames,calibration_rendered_frames=calibration_frames,
                source_fps=fps,output_resolution=[width,height],audio_included=False,files=files,
                video_covers_entire_source=expected_frames==total,segment_duration_s=600,
                render_source_sha256=__import__('hashlib').sha256(Path(__file__).read_bytes()).hexdigest(),
                encoder=codec,encoder_quality='NVENC VBR CQ 28, preset p5' if codec=='h264_nvenc' else 'x264 CRF 30, preset fast',
                frames_with_metric_labels=labelled_frames,labelled_car_tracks=len(labelled_ids),
                examples=examples,calibration_regions=region_info,
                calibration_video_note='Offline replay shows the final mapping fitted from the selected initial interval.',
                speeds_note='Only qualified car footprints receive a metric label; grey tracks lack a qualified speed.',
                accuracy_validated=False)
    (output/'video_manifest.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print('All videos complete:',calibration['camera_id'],rendered_frames,'speed frames',calibration_frames,'calibration frames',flush=True)
    return report
