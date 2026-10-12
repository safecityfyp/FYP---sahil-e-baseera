"""Convert percent-cell Python source into a plain Kaggle notebook."""
import ast
import json
from pathlib import Path
import sys

source_path=Path(sys.argv[1])
source=source_path.read_text(encoding='utf-8')
ast.parse(source)
cells=[]
for index,section in enumerate(source.split('# %%')[1:]):
    markdown=section.startswith(' markdown')
    body=section.split('\n',1)[1].strip('\n')
    if markdown:
        body='\n'.join(line[2:] if line.startswith('# ') else line[1:] if line.startswith('#') else line for line in body.splitlines())
        cell={'cell_type':'markdown','metadata':{},'source':body+'\n'}
    else:
        ast.parse(body)
        cell={'cell_type':'code','execution_count':None,'metadata':{},'outputs':[],'source':body+'\n'}
    cell['id']=f'cell-{index:02d}';cells.append(cell)
notebook={'cells':cells,'metadata':{'kernelspec':{'display_name':'Python 3','language':'python','name':'python3'},'language_info':{'name':'python'}},'nbformat':4,'nbformat_minor':5}
target=source_path.with_suffix('.ipynb')
target.write_text(json.dumps(notebook,indent=2),encoding='utf-8')
print('Built:',target,'Cells:',len(cells))
