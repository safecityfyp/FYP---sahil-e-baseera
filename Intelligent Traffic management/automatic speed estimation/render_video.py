"""Stage 4: export separate calibration and annotated speed videos."""
import argparse
from speed_estimation.rendering import render


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video',required=True)
    parser.add_argument('--inputs',nargs='+',required=True)
    parser.add_argument('--calibration',required=True)
    parser.add_argument('--speed',required=True,help='Speed-results folder from estimate_speed.py')
    parser.add_argument('--output',required=True,help='Video destination folder')
    parser.add_argument('--duration',type=float,help='Optional preview duration; omit for the complete source')
    parser.add_argument('--encoder',choices=['libx264','h264_nvenc'],default='libx264')
    args=parser.parse_args()
    render(args.video,args.inputs,args.calibration,args.speed,args.output,args.duration,args.encoder)


if __name__=='__main__':
    main()
