"""A small generated scene with known geometry; no recorded footage."""
import numpy as np
from speed_estimation.geometry import project


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
