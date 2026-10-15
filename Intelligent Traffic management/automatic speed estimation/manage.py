"""Read Kaggle experiment status or download its latest outputs without changing the saved snapshot."""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    # Kaggle writes Unicode notebook logs using the system encoding on Windows.
    if os.name == 'nt' and not sys.flags.utf8_mode:
        raise SystemExit(subprocess.call([sys.executable, '-X', 'utf8', *sys.argv]))
    config = json.loads((ROOT / 'experiments.json').read_text(encoding='utf-8'))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['status', 'download'], nargs='?', default='status')
    parser.add_argument('--experiment', choices=list(config['experiments']), default='baseline')
    args = parser.parse_args()
    from kaggle.api.kaggle_api_extended import KaggleApi

    experiment = config['experiments'][args.experiment]
    api = KaggleApi()
    api.authenticate()
    result = api.kernels_status(experiment['notebook'])
    status = result.status.name if hasattr(result.status, 'name') else str(result.status)
    print('Notebook:', 'https://www.kaggle.com/code/' + experiment['notebook'])
    print('Latest session status:', status)
    if result.failure_message:
        print('Failure:', result.failure_message)
    if args.action == 'download':
        if status.upper() != 'COMPLETE':
            raise SystemExit('Download after the notebook completes successfully.')
        output = ROOT / 'outputs'
        output.mkdir(parents=True, exist_ok=True)
        files, token = api.kernels_output(
            experiment['notebook'], str(output), force=True,
            file_pattern=experiment['output_pattern'])
        while token:
            more, token = api.kernels_output(
                experiment['notebook'], str(output), force=True, page_token=token,
                file_pattern=experiment['output_pattern'])
            files.extend(more)
        print('Downloaded files:', len(files))
        print('Runtime output folder:', output)
        print('The versioned output/ snapshot is unchanged.')


if __name__ == '__main__':
    main()
