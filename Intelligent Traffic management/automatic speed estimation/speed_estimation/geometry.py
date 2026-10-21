"""Projective geometry and robust multi-car rectangle fitting."""
import math
from collections import defaultdict
import cv2
import numpy as np
from scipy.optimize import least_squares

LENGTH_M, WIDTH_M = 4.5, 1.8


def project(points, H):
    p = np.asarray(points, dtype=float)
    flat = p.reshape(-1,2)
    result = np.c_[flat,np.ones(len(flat))] @ H.T
    denominator = result[:,2]
    safe = np.where(np.abs(denominator)<1e-8, np.where(denominator>=0,1e-8,-1e-8),denominator)
    return (result[:,:2]/safe[:,None]).reshape(p.shape)


def compose(theta, normalizer):
    p,q,a,b = theta
    return np.array([[np.exp(a),b,0],[0,1,0],[p,q,1]]) @ normalizer


def measures(quads):
    edges = np.roll(quads,-1,axis=1)-quads
    sizes = np.linalg.norm(edges,axis=2)+1e-9
    unit = edges/sizes[:,:,None]
    cosines = np.sum(unit*np.roll(unit,-1,axis=1),axis=2)
    opposite = unit[:,:2,0]*unit[:,2:,1]-unit[:,:2,1]*unit[:,2:,0]
    lengths=(sizes[:,0]+sizes[:,2])/2
    widths=(sizes[:,1]+sizes[:,3])/2
    return cosines,opposite,lengths,widths


def fit_mapping(records, width, height, length_m=LENGTH_M, width_m=WIDTH_M, fast=False, legacy_normalization=False):
    quads=np.array([r['quad'] for r in records],dtype=float)
    ids=np.array([r['track_id'] for r in records])
    unique=np.unique(ids)
    center=np.median(quads.reshape(-1,2),axis=0)
    normalizer=np.array([[2/width,0,-2*center[0]/width],[0,2/width,-2*center[1]/width],[0,0,1]])
    if legacy_normalization:
        normalizer=np.array([[2/width,0,-1],[0,2/width,-height/width],[0,0,1]])
    weights=np.array([1/math.sqrt(np.sum(ids==i)) for i in ids])
    weights/=np.mean(weights)
    groups=[np.flatnonzero(ids==i) for i in unique]

    def residual(theta):
        H=compose(theta,normalizer)
        world=project(quads,H)
        angles,parallel,lengths,widths=measures(world)
        rigidity=np.zeros(len(records))
        for group in groups:
            rigidity[group]=np.log(lengths[group]/np.median(lengths[group]))
        shape=np.log((lengths/widths)/(length_m/width_m))
        geometric=np.c_[angles,parallel*0.5,shape*0.65,rigidity*0.5]*weights[:,None]
        den=(np.c_[quads.reshape(-1,2),np.ones(len(quads)*4)]@H.T)[:,2]
        pole=np.maximum(0,0.08-den)*15
        return np.r_[geometric.ravel(),pole]

    q_starts=([0,1,2] if not fast else [1,2]) if legacy_normalization else ([0,2,5,10,20] if not fast else [2,10])
    aspect_starts=([0,0.7] if not fast else [0]) if legacy_normalization else ([-3,0] if not fast else [-2])
    starts=[(0,q,a,0) for q in q_starts for a in aspect_starts]
    fits=[]
    for theta in starts:
        bound=4 if legacy_normalization else 100
        shape_bound=2.5 if legacy_normalization else 7
        shear_bound=4 if legacy_normalization else 30
        result=least_squares(residual,theta,bounds=([-bound,-bound,-shape_bound,-shear_bound],[bound,bound,shape_bound,shear_bound]),
                             loss='soft_l1',f_scale=0.12,max_nfev=500)
        fits.append((float(np.mean(residual(result.x)**2)),result))
    _,result=min(fits,key=lambda item:item[0])
    H=compose(result.x,normalizer)
    world=project(quads,H)
    _,_,lengths,_=measures(world)
    # Give each track one vote; correlated video frames do not count as independent cars.
    scale=length_m/np.median([np.median(lengths[g]) for g in groups])
    H=np.diag([scale,scale,1])@H
    world=project(quads,H)
    directions=world[:,1]-world[:,0]
    directions/=np.linalg.norm(directions,axis=1)[:,None]
    directions[directions[:,1]<0]*=-1
    direction=np.median(directions,axis=0)
    angle=math.pi/2-math.atan2(direction[1],direction[0])
    rotation=np.array([[math.cos(angle),-math.sin(angle),0],[math.sin(angle),math.cos(angle),0],[0,0,1]])
    H=rotation@H
    center=np.median(project(quads,H).mean(axis=1),axis=0)
    H=np.array([[1,0,-center[0]],[0,1,-center[1]],[0,0,1]])@H
    H/=np.linalg.norm(H[2,:2]) if np.linalg.norm(H[2,:2])>0 else H[2,2]
    angle_error,_,lengths,widths=measures(project(quads,H))
    singular=np.linalg.svd(result.jac,compute_uv=False)
    diagnostics={'fit_track_ids':[int(i) for i in unique],'fit_observations':len(records),
       'median_angle_error_deg':float(np.median(np.degrees(np.arcsin(np.clip(np.abs(angle_error),0,1))))),
       'median_length_m':float(np.median(lengths)),'median_width_m':float(np.median(widths)),
       'parameter_condition_number':float(singular[0]/max(singular[-1],1e-12)),
       'optimizer_success':bool(result.success),'theta':result.x.tolist(),
       'dimension_prior_length_m':length_m,'dimension_prior_width_m':width_m}
    return H,diagnostics


def sample_balanced(records, maximum=10):
    groups=defaultdict(list)
    for r in records:groups[r['track_id']].append(r)
    return [group[i] for group in groups.values() for i in np.unique(np.linspace(0,len(group)-1,min(len(group),maximum)).astype(int))]


def overlaps(a,b):
    lo=np.maximum(a[:,None,:2],b[None,:,:2]);hi=np.minimum(a[:,None,2:],b[None,:,2:])
    intersection=np.prod(np.maximum(0,hi-lo),axis=2)
    return intersection/(np.prod(a[:,2:]-a[:,:2],axis=1)[:,None]+
                         np.prod(b[:,2:]-b[:,:2],axis=1)[None,:]-intersection+1e-9)
