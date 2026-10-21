"""Stage 1: create a saved road calibration, automatically or from image observations."""
import argparse


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='mode',required=True)
    auto=sub.add_parser('cctv',help='Compare three mappings per configured road region')
    auto.add_argument('--inputs',nargs='+',required=True)
    auto.add_argument('--camera',required=True)
    auto.add_argument('--output',required=True,help='Folder for calibration.json and diagnostics')
    vision=sub.add_parser('vision',help='Fit experimental 1-D calibration from marked wheel/road points')
    vision.add_argument('--annotations',required=True)
    vision.add_argument('--method',choices=['local_affine','projective_single','projective_consensus'],
                        default='projective_consensus')
    vision.add_argument('--output',required=True,help='Calibration JSON file')
    args=parser.parse_args()
    if args.mode=='cctv':
        from cctv_calibration import calibrate
        calibrate(args.inputs,args.camera,args.output)
    else:
        from vision_calibration import fit
        result=fit(args.annotations,args.output,args.method)
        print('Saved calibration:',result['case_id'],result['method'])


if __name__=='__main__':
    main()
