"""Make figures and the evidence report from the already-frozen six-clip trial."""
from pathlib import Path
import csv
import json
import hashlib
import subprocess
import cv2
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'output/vision_assisted_trial'


def build():
    with (OUT/'results.csv').open(newline='') as stream:
        rows=list(csv.DictReader(stream))
    chosen=[r for r in rows if r['method']=='projective_consensus']
    metrics=json.loads((OUT/'metrics.json').read_text())
    ids=[r['case_id'] for r in chosen]
    plt.rcParams.update({'font.size':11,'axes.spines.top':False,'axes.spines.right':False})
    fig,ax=plt.subplots(figsize=(12,6.3))
    fig.subplots_adjust(bottom=.20,top=.89,left=.09,right=.99)
    x=np.arange(len(ids))
    ax.axhspan(-2,2,color='#2e7d32',alpha=.12,label='Requested +/-2 km/h band')
    methods=['local_affine','projective_single','projective_consensus','historical_pipeline']
    colors=['#7f8c8d','#36a3c7','#cb5a30','#6a50a7']
    names=['Local affine control','One screenshot scale','Five screenshot consensus','Historical pipeline*']
    for i,(method,color,name) in enumerate(zip(methods,colors,names)):
        values=[float(r['historical_pipeline_kmh'])-float(r['reference_cruise_setting_kmh']) for r in chosen] if i==3 else [
            float(next(r for r in rows if r['case_id']==cid and r['method']==method)['error_kmh']) for cid in ids]
        ax.bar(x+(i-1.5)*.19,values,.18,color=color,label=name)
    ax.set_xticks(x,[r['video'].replace('.MP4','').replace('MercedesAMG550_','Mercedes ').replace('KiaSportage_','Kia ') for r in chosen])
    ax.axhline(0,color='#555',lw=.8)
    ax.set_ylabel('Prediction minus cruise-control setting (km/h)')
    ax.set_title('Initial image-assisted trial: six separate clips, no speed labels in geometry')
    ax.legend(ncol=2,fontsize=9)
    fig.text(.02,.035,'*Historical pipeline uses other labelled passes and a different observation interval. Reused clips; no radar reference.',fontsize=9)
    fig.savefig(OUT/'speed_error_comparison.png',dpi=170)
    plt.close(fig)

    fig,axes=plt.subplots(2,3,figsize=(12,7),layout='constrained')
    for ax,row in zip(axes.ravel(),chosen):
        result=json.loads((OUT/row['case_id']/'prediction_projective_consensus.json').read_text())
        t=np.array(result['times_s']);position=np.array(result['position_m'])
        ax.plot(t-t[0],position,'o',color='#cb5a30',label='Mapped wheel contact')
        ax.plot(t-t[0],result['fitted_position_m'],'-',color='#23536d',label='Robust velocity fit')
        ax.set_title(f"{row['case_id']}: {float(row['estimated_kmh']):.1f} km/h; setting {float(row['reference_cruise_setting_kmh']):.0f}")
        ax.set_xlabel('Elapsed source time (s)');ax.set_ylabel('Relative mapped distance (m)')
        ax.grid(alpha=.15)
    axes[0,0].legend(fontsize=8)
    fig.suptitle('Speed stage after freezing image-based calibration')
    fig.savefig(OUT/'mapped_motion.png',dpi=170);plt.close(fig)

    tiles=[]
    for row in chosen:
        folder=OUT/row['case_id']
        image=cv2.imread(str(folder/'annotated_2.jpg'))
        calibration=json.loads((folder/'calibration_projective_consensus.json').read_text())
        vp=tuple(round(v) for v in calibration['road_vanishing_point_px'])
        cv2.line(image,(0,vp[1]),(1919,vp[1]),(255,170,0),2)
        cv2.circle(image,vp,12,(255,170,0),3)
        for segment in json.loads((folder/'annotations.json').read_text())['road_edge_segments_px']:
            cv2.line(image,vp,tuple(segment[-1]),(220,90,220),1)
        cv2.imwrite(str(folder/'calibration_review.jpg'),image)
        tile=cv2.resize(image,(768,432))
        tiles.append(tile)
    cv2.imwrite(str(OUT/'calibration_contact_sheet.jpg'),np.vstack([np.hstack(tiles[:3]),np.hstack(tiles[3:])]))

    table=['| Clip | Interval (s) | Cruise setting | Screenshot consensus | Error | Historical pipeline* |',
           '|---|---:|---:|---:|---:|---:|']
    for row in chosen:
        table.append(f"| {row['video']} | {float(row['start_s']):.3f}-{float(row['end_s']):.3f} | {float(row['reference_cruise_setting_kmh']):.0f} | {float(row['estimated_kmh']):.1f} | {float(row['error_kmh']):+.1f} | {float(row['historical_pipeline_kmh']):.1f} |")
    versions=['| Method | MAE (km/h) | Worst error | Within +/-2 |','|---|---:|---:|---:|']
    for method in methods[:3]:
        m=metrics['methods'][method+'/all']
        versions.append(f"| {method} | {m['mae_kmh']:.2f} | {m['maximum_absolute_error_kmh']:.2f} | {m['within_2_kmh']}/6 |")
    text='''# Assistant image-assisted calibration: first six-clip trial

Date: 21 October 2026. **Not promoted to the main workflow:** the preselected five-screenshot consensus has **6.85 km/h MAE, 0/6 within +/-2 km/h, and a worst error of 10.61 km/h**. The historical pipeline has **2.68 km/h MAE on these same six clips**, with extra reference-speed assistance from other passes. The single-screenshot variant has 6.12 km/h MAE. These findings do not support the proposed improvement in this initial implementation.

The user authorized this assistant's image analysis for the first trial. No external GPT/Claude API was called, and no claim is made about any named external model. All six videos were previously studied; this is a development experiment, not fresh independent validation. The assistant had prior conversation context. Label-free images and an API that excludes reference speeds reduce leakage; they do not make this a double-blind study.

## Each clip is a separate test

All speeds below are km/h. Reference values are user-confirmed constant cruise-control settings read from filenames **only by the evaluation command**. The label text files are ignored. Reference uncertainty is unknown: no independent radar/GPS measurement or calibrated speedometer record was supplied.

'''+ '\n'.join(table)+'''

*The historical values come from the existing Mercedes comparison and Kia validation CSVs. They use other known-speed passes and their original observation intervals. This is a comparison of available pipelines on the same constant-speed passages, not a controlled ablation of equal inputs.

![Signed prediction errors for all six tests](speed_error_comparison.png)

## What the assistant actually did

1. Selected six initial clips spanning low, middle and high cruise settings, three per vehicle. Selected five source frames per clip by untruncated detection-box heights nearest 180, 230, 280, 330 and 380 pixels. The geometry stage receives anonymous IDs M01-M03 and K01-K03, not filenames or reference speeds.
2. Inspected full road images and pixel-grid crops. Marked visible near-side front/rear tyre ground contacts and two road-edge segments. Reviewed enlarged wheel crops and corrected marks visually before any numerical prediction/error scoring. The final observations are in each `annotations.json`. Hidden far-side wheel locations are not invented.
3. Used approximate wheelbase priors: 2.85 m for a visually inferred Mercedes CLS family, 2.67 m for a visually inferred Kia Sportage QL family. The exact Mercedes trim and Kia year remain unconfirmed. Wheelbase means axle separation, **not overall body length**. No vehicle was physically measured.
4. Froze three calibration variants per clip: a local affine control; projective mapping scaled by the middle screenshot; and the preselected median scale across five screenshots. The default consensus was chosen before errors, not switched to whichever version looked closest afterward.
5. Saved calibration JSONs, then mapped five front-wheel contacts with their source timestamps and fitted speed. No neural model retraining was involved. Eighteen separate predictions were saved and SHA-256 bound in `prediction_freeze.json` before the evaluation command read filename speed labels.
6. Perturbed wheel points (8 px standard deviation for Mercedes, 10 px for the shadowed Kia), road points (8 px) and wheelbase (+/-3.5%, uniform), with 2,000 deterministic Monte Carlo draws per prediction. Reported 2.5th/97.5th percentiles are **conditional sensitivity**, not validated confidence bounds. They exclude wrong road/vehicle assumptions, rolling-shutter/lens bias, camera movement and reference-speed error.

## Calibration and speed mathematics

Two marked longitudinal road edges give their image vanishing point. Assuming zero camera roll and a planar road, its vertical coordinate `h` supplies a horizontal road horizon. For a ground contact `(x,y)`, define `u = 1 / (y-h)`. For front/rear same-side wheel contacts, `k = wheelbase / abs(u_front-u_rear)`. Use one `k`, or the median of five `k` values, and freeze it. Relative along-path distance is `s = k * (u-u_initial)`. Speed is `3.6 * abs(ds/dt)` from a robust straight-line fit.

This is a restricted longitudinal metrology experiment. A single longitudinal vanishing point does not identify a full 2-D metric road homography, camera height, focal length, true pitch, or the full road length. The zero-roll/planarity/parallel-path assumptions supply information missing from the image. If the road curves or the chosen edges are not parallel, the calculation can be consistently biased. This follows projective metrology principles; it is not a reproduction of a published trained calibration network.

'''+ '\n'.join(versions)+'''

![Calibration marks and assumed horizons, separately for all clips](calibration_contact_sheet.jpg)

## What the failure reveals

The problem is not confined to high speeds: the 30 km/h Mercedes produces the largest consensus error (40.6 km/h). The 100 km/h Mercedes is closer (97.3 km/h), while the 105 km/h Kia is overestimated (112.1 km/h). Several visible wheel separations are only a few tens of vertical pixels; small contact errors materially change the metre scale. Dark tyres merging with shadows and short source intervals make that worse. The projective correction also depends on which apparently parallel road edges the assistant marks.

The five-snapshot scale MAD can be small even when absolute speed is wrong: M01 passes internal consistency yet misses its cruise setting by 10.6 km/h. Multiple agreeing calibrations therefore do not establish correct metres. A language model can help propose points, vehicle hypotheses and regions, but this trial gives no evidence that its guessed road geometry replaces an independently measured scale reference.

Keep the existing multi-car CCTV calibration as the main workflow. Use assistant/manual observations as reviewable proposals; a measured road segment or confirmed vehicle wheelbase and precise ground contacts would supply stronger scale evidence. No empirical speed correction was tuned from these six labels, and the remaining clips were not added after this unsuccessful pilot. The earlier 25-clip Kia reserved study retains its historical meaning; the three Kia clips here are from its development subset.

![Mapped positions and velocity fits](mapped_motion.png)

## Files and reproduction

- `results.csv`: all 18 predictions, reference errors, intervals and sensitivity ranges.
- `metrics.json`: all methods and vehicle-specific summaries.
- `prediction_freeze.json`: hashes and pre-error method policy; `evaluation_sources.json`: filename mapping used only for preparation/evaluation.
- Each case folder: five raw frames, five annotated frames, pixel-grid sheet, `annotations.json`, `frames.json`, three calibration JSONs, three prediction JSONs and calibration review image.
- `model_smoke_check.json`: separate one-frame checkpoint smoke check. The screenshot trial itself uses assistant marks; it does not require detector weights at runtime.
- `verification.json`: checks and source/bundle validation recorded at handoff.

From the feature directory, reproduce a saved case without video/model downloads:

```powershell
python calibrate.py vision --annotations output/vision_assisted_trial/M01/annotations.json --method projective_consensus --output outputs/manual_M01/calibration.json
python estimate_speed.py vision --annotations output/vision_assisted_trial/M01/annotations.json --frames output/vision_assisted_trial/M01/frames.json --calibration outputs/manual_M01/calibration.json --output outputs/manual_M01/speed.json
python vision_trial.py evaluate
python -m unittest test_vision_calibration test_cctv
```

To rerun all numerical predictions, copy the six case input files/images to a **new experiment folder** before calling `vision_trial.py predict --folder <new folder>`. It refuses to overwrite a frozen experiment. `record_vision_annotations.py` records this assistant's fixed marks; rerunning it is not a fresh LLM inference. `prepare_vision_trial.py` re-extracts the original six cases when the private videos and saved detection tracks are available. No Kaggle job was launched for this trial; previous detector/geometry extraction used the documented Kaggle jobs. The numerical experiment runs locally from actual source frames and source timestamps.

## Research and model sources

- [Criminisi, Reid and Zisserman, Single View Metrology (2000)](https://ora.ox.ac.uk/objects/uuid%3A9b99df78-df75-49a9-a1b8-1b38e1b173a8): projective measurements require geometric constraints and scale information; this experiment uses a restricted 1-D form with extra assumptions.
- [Kia 2016 Sportage technical press kit](https://press.kia.com/ie/en/home/media-resouces/press-releases/2016/16_01_20_press-kit---kia-sportage-petd.html): 2.670 m wheelbase for that generation. The image-based generation identification remains a hypothesis.
- [Mercedes-Benz C219 archive](https://mercedes-benz-publicarchive.com/marsClassic/en/instance/ko/219-series-CLS-Coups-2004---2006.xhtml?oid=453318): vehicle-family appearance context; 2.85 m remains an approximate prior, not a confirmed measurement of this car.
- [Sochor et al. (2017)](https://arxiv.org/abs/1702.06451): full known-vehicle 3-D alignment differs from visually guessing a few wheel contacts.
- Actual project detector and cuboid weights are documented in [`model_manifest.json`](../../model_manifest.json). There is no separate `speed.pt` or `calibration.pt`.
'''
    (OUT/'README.md').write_text(text,encoding='utf-8')


if __name__=='__main__':
    build()
