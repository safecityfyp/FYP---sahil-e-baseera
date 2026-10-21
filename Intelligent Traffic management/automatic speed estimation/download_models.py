"""Download the pinned vehicle detector and geometry checkpoints, or verify local copies."""
import argparse
from speed_estimation.models import download


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='models')
    parser.add_argument('--verify-only',action='store_true')
    args=parser.parse_args()
    download(args.output,args.verify_only)


if __name__=='__main__':
    main()
