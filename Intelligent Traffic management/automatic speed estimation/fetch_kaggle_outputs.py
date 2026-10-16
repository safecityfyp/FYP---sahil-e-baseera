"""Download selected authorized private Kaggle outputs without exposing URLs."""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import re
import time

import requests
from kaggle.api.kaggle_api_extended import KaggleApi,ApiListKernelSessionOutputRequest


def fetch(kernel,output,pattern):
    api=KaggleApi();api.authenticate();owner,slug,_=api.parse_kernel_string(kernel)
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    pattern=re.compile(pattern);items=[];token=None
    while True:
        request=ApiListKernelSessionOutputRequest();request.user_name=owner;request.kernel_slug=slug
        api._set_paging(request,100,token)
        with api.build_kaggle_client() as client:
            response=client.kernels.kernels_api_client.list_kernel_session_output(request)
        items.extend(item for item in response.files or [] if pattern.search(item.file_name) and not item.file_name.endswith('.pt'))
        token=response.next_page_token
        if not token:break
    def download(item):
        target=(output/item.file_name).resolve();assert target.is_relative_to(output)
        for attempt in range(3):
            try:
                response=requests.get(item.url,timeout=180);response.raise_for_status()
                target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(response.content)
                return len(response.content)
            except Exception:
                if attempt==2:raise RuntimeError('Download failed for '+item.file_name) from None
                time.sleep(attempt+1)
    size=0
    with ThreadPoolExecutor(max_workers=6) as pool:
        for future in as_completed([pool.submit(download,item) for item in items]):size+=future.result()
    print('Downloaded',len(items),'files,',size,'bytes from',kernel,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--kernel',required=True)
    p.add_argument('--output',required=True);p.add_argument('--pattern',default=r'cctv_outputs/.*\.(json|gz|csv|jpg|yaml|mp4)$')
    a=p.parse_args();fetch(a.kernel,a.output,a.pattern)
