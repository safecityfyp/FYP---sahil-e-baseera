"""Stage 1: detect and track vehicles, saving ground geometry and source timestamps."""
import argparse


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video',required=True)
    parser.add_argument('--camera',required=True,help='Camera key in configs/cameras.json')
    parser.add_argument('--profiles',help='Optional alternative camera-profile JSON')
    parser.add_argument('--output',required=True,help='Folder for extracted measurements')
    parser.add_argument('--models',help='Verified checkpoint folder; defaults to models/')
    parser.add_argument('--device',default='0',help='GPU index or cpu')
    parser.add_argument('--duration',type=float,help='Optional stop time in source seconds')
    parser.add_argument('--resume-s',type=float,default=0,help='Start a separate measurement segment at this source time')
    args=parser.parse_args()
    from speed_estimation.inference import inference
    inference(args.video,args.output,args.camera,args.duration,args.resume_s,args.device,args.models,args.profiles)


if __name__=='__main__':
    main()
