"""Reproduce this assistant's saved visual observations, made before error scoring.

These coordinates are manual image interpretations, not learned predictions.
The file contains no reference speeds and does not import the evaluation mapping.
"""
from pathlib import Path
import json
import cv2
from vision_calibration import digest

ROOT=Path(__file__).resolve().parent/'output/vision_assisted_trial'
POINTS={
    'M01': dict(front=[[685,698],[737,739],[797,788],[859,844],[929,883]],
                rear=[[649,675],[680,701],[718,724],[744,754],[783,779]],
                edges=[[[530,670],[710,1050]],[[1250,699],[1870,807]]]),
    'M02': dict(front=[[612,703],[644,742],[680,787],[725,848],[745,870]],
                rear=[[583,673],[601,699],[629,725],[652,758],[662,771]],
                edges=[[[520,650],[660,1020]],[[1120,670],[1800,790]]]),
    'M03': dict(front=[[432,674],[468,714],[517,782],[549,815],[584,861]],
                rear=[[409,646],[428,674],[461,711],[477,735],[494,751]],
                edges=[[[335,650],[500,1020]],[[1020,660],[1850,795]]]),
    'K01': dict(front=[[570,722],[645,764],[713,807],[796,851],[847,882]],
                rear=[[534,704],[582,724],[625,749],[667,774],[708,786]],
                edges=[[[378,700],[535,1040]],[[1060,710],[1850,795]]]),
    'K02': dict(front=[[517,688],[587,728],[652,756],[726,796],[798,823]],
                rear=[[474,667],[521,688],[555,713],[612,736],[656,753]],
                edges=[[[300,650],[450,1020]],[[1030,663],[1820,739]]]),
    'K03': dict(front=[[539,701],[616,743],[680,773],[782,826],[840,860]],
                rear=[[493,682],[545,712],[582,733],[634,763],[674,779]],
                edges=[[[330,680],[520,1000]],[[1020,681],[1830,760]]]),
}


def record():
    for case_id, points in POINTS.items():
        folder=ROOT/case_id
        frames=json.loads((folder/'frames.json').read_text())
        annotation=dict(schema_version=1,case_id=case_id,image_size=[frames['width'],frames['height']],
            author='Current assistant visual analysis, authorized by the user; external model API not used.',
            vehicle_hypothesis='Mercedes C219 CLS family (trim unconfirmed)' if case_id[0]=='M' else
                               'Kia Sportage QL family (year/trim unconfirmed)',
            wheelbase_prior_m=2.85 if case_id[0]=='M' else 2.67,
            wheelbase_prior_status='Approximate family-level prior; not measured on the supplied vehicle.',
            wheelbase_source='Engineering prior for visually inferred CLS family' if case_id[0]=='M' else
                'https://press.kia.com/ie/en/home/media-resouces/press-releases/2016/16_01_20_press-kit---kia-sportage-petd.html',
            anchor_frame=2,road_edge_segments_px=points['edges'],
            wheel_contacts=[dict(front_xy=f,rear_xy=r) for f,r in zip(points['front'],points['rear'])],
            images=[dict(file=r['image'],frame_index=r['frame_index'],sha256=digest(folder/r['image'])) for r in frames['frames']],
            uncertainty=dict(wheel_point_sigma_px=8 if case_id[0]=='M' else 10,
                             road_point_sigma_px=8,wheelbase_relative_half_range=.035),
            assumptions=['Fixed camera within this clip; no calibration transfer between clips.',
                         'Locally planar road and negligible camera roll.',
                         'Marked left/right road edges approximately parallel to the vehicle path.',
                         'Visible same-side tyre ground contacts are separated by the assumed wheelbase.',
                         'No independent camera angle, road length, vehicle dimensions or lens calibration supplied.'],
            notes='Shadow and tyre boundaries are ambiguous, especially on the dark Kia. No far wheel is invented.')
        (folder/'annotations.json').write_text(json.dumps(annotation,indent=2)+'\n',encoding='utf-8')
        # Visual QA before running numerical predictions.
        for i,(front,rear) in enumerate(zip(points['front'],points['rear'])):
            frame=cv2.imread(str(folder/f'frame_{i}.jpg'))
            cv2.drawMarker(frame,tuple(front),(0,255,0),cv2.MARKER_CROSS,18,2)
            cv2.drawMarker(frame,tuple(rear),(255,200,0),cv2.MARKER_CROSS,18,2)
            cv2.line(frame,tuple(front),tuple(rear),(0,255,255),2)
            for p1,p2 in points['edges']:
                cv2.line(frame,tuple(p1),tuple(p2),(255,0,255),2)
            cv2.putText(frame,f'{case_id} | green=front contact, cyan=rear contact | assumed wheelbase',
                        (25,35),0,.7,(0,255,255),2)
            cv2.imwrite(str(folder/f'annotated_{i}.jpg'),frame)


if __name__=='__main__':
    record()
