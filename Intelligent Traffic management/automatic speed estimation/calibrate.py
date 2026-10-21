"""Stage 2: compare road mappings and save camera-specific calibration."""
import argparse
from speed_estimation.calibration import calibrate


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs',nargs='+',required=True,help='Measurement folders from extract_tracks.py')
    parser.add_argument('--camera',required=True,help='Camera key in configs/cameras.json')
    parser.add_argument('--profiles',help='Optional alternative camera-profile JSON')
    parser.add_argument('--output',required=True,help='Folder for calibration.json and diagnostics')
    args=parser.parse_args()
    result=calibrate(args.inputs,args.camera,args.output,args.profiles)
    if not result['all_regions_accepted']:
        raise SystemExit('Some road regions lack reliable calibration; review calibration.json before estimating speed.')


if __name__=='__main__':
    main()
