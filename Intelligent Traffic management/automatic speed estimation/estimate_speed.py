"""Stage 2: calculate decimal km/h from observations and an existing calibration."""
import argparse


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='mode',required=True)
    auto=sub.add_parser('cctv',help='Use saved multi-car ground-plane mappings')
    auto.add_argument('--inputs',nargs='+',required=True)
    auto.add_argument('--calibration',required=True)
    auto.add_argument('--output',required=True,help='Folder for CSV/JSON speed samples')
    vision=sub.add_parser('vision',help='Use assistant/manual wheel contacts and source timestamps')
    vision.add_argument('--annotations',required=True)
    vision.add_argument('--frames',required=True)
    vision.add_argument('--calibration',required=True)
    vision.add_argument('--output',required=True,help='Prediction JSON file')
    args=parser.parse_args()
    if args.mode=='cctv':
        from cctv_speed import calculate
        calculate(args.inputs,args.calibration,args.output)
    else:
        from vision_calibration import estimate
        result=estimate(args.annotations,args.calibration,args.frames,args.output)
        print(result['case_id'],result['display_speed'])


if __name__=='__main__':
    main()
