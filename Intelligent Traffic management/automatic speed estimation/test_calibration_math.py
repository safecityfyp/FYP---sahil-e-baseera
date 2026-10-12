"""Synthetic geometry checks with known projection, vehicle dimensions and velocity."""
import numpy as np
from calibrate_speed import project, fit_mapping, estimate_track, measures


def synthetic():
    image_from_world=np.array([[120,20,1200],[0,-12,800],[0,0.02,1]],dtype=float)
    records=[]
    for tid in range(6):
        for t in np.linspace(0,3,12):
            x=-4+tid*1.5;y=2+tid*2+4*t
            quad=np.array([[x-.9,y-2.25],[x-.9,y+2.25],
                           [x+.9,y+2.25],[x+.9,y-2.25]])
            records.append({'track_id':tid,'time_s':float(t),'quad':project(quad,image_from_world).tolist()})
    return records


def main():
    records=synthetic()
    H,diagnostics=fit_mapping(records,2560,1440)
    _,_,lengths,widths=measures(project(np.array([r['quad'] for r in records]),H))
    assert np.allclose(lengths,4.5,rtol=.01),lengths
    assert np.allclose(widths,1.8,rtol=.01),widths
    track=[r for r in records if r['track_id']==2]
    estimated=estimate_track(track,H)
    assert abs(estimated['experimental_kmh']-14.4)<.1,estimated
    scaled,_=fit_mapping(records,2560,1440,3.6,1.44)
    scaled_speed=estimate_track(track,scaled)['experimental_kmh']
    assert abs(scaled_speed/estimated['experimental_kmh']-.8)<.01,scaled_speed
    rng=np.random.default_rng(5)
    noisy=[{**r,'quad':(np.array(r['quad'])+rng.normal(0,.5,(4,2))).tolist()} for r in records]
    noisy_H,_=fit_mapping(noisy,2560,1440)
    noisy_speed=estimate_track([r for r in noisy if r['track_id']==2],noisy_H)['experimental_kmh']
    assert abs(noisy_speed-14.4)/14.4<.05,noisy_speed
    print('PASS: metric geometry recovered from a known perspective projection.')
    print('PASS: known 14.4 km/h synthetic motion recovered.')
    print('PASS: dimension-scale change propagates proportionally to speed.')
    print('PASS: subpixel corner noise stays within 5% in the synthetic case.')


if __name__=='__main__':main()
