"""Download and SHA-256 verify the two actual inference checkpoints."""
from pathlib import Path
import argparse
import hashlib
import json
import urllib.request
import time


def sha(path):
    checksum=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):
            checksum.update(chunk)
    return checksum.hexdigest()


def download(output,verify_only=False):
    output=Path(output)
    output.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((Path(__file__).parent/'model_manifest.json').read_text())
    verified=[]
    for model in manifest['models']:
        target=output/model['filename']
        if target.exists():
            if sha(target)!=model['sha256']:
                raise ValueError(f'Existing checkpoint hash mismatch: {target}; retain it elsewhere before downloading.')
        elif verify_only:
            raise FileNotFoundError(target)
        else:
            partial=target.with_suffix('.pt.partial')
            request=urllib.request.Request(model['url'],headers={'User-Agent':'FYP-speed-checkpoint-downloader/1'})
            checksum=hashlib.sha256()
            written=0
            last=time.monotonic()
            with urllib.request.urlopen(request,timeout=60) as response,partial.open('wb') as stream:
                while True:
                    chunk=response.read(1024*1024)
                    if not chunk:break
                    stream.write(chunk)
                    checksum.update(chunk)
                    written+=len(chunk)
                    if time.monotonic()-last>10:
                        print(model['filename'],f'{written/1e6:.1f}/{model["bytes"]/1e6:.1f} MB',flush=True)
                        last=time.monotonic()
            if written!=model['bytes'] or checksum.hexdigest()!=model['sha256']:
                raise ValueError(f'Download verification failed: {partial}')
            partial.replace(target)
        print('Verified',target.name,model['sha256'],flush=True)
        verified.append(dict(filename=target.name,bytes=target.stat().st_size,sha256=model['sha256']))
    (output/'verified_models.json').write_text(json.dumps(verified,indent=2)+'\n')
    return verified


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',default='models')
    p.add_argument('--verify-only',action='store_true')
    a=p.parse_args()
    download(a.output,a.verify_only)
