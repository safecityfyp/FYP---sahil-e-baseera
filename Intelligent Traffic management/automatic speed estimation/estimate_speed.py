"""Stage 3: load saved calibration and calculate decimal km/h from ground motion."""
import argparse
from speed_estimation.speed import calculate


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs',nargs='+',required=True,help='Measurement folders from extract_tracks.py')
    parser.add_argument('--calibration',required=True,help='Camera-specific calibration JSON')
    parser.add_argument('--output',required=True,help='Folder for speed CSV/JSON files')
    args=parser.parse_args()
    calculate(args.inputs,args.calibration,args.output)


if __name__=='__main__':
    main()
