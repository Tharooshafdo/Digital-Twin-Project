import json,importlib.metadata
from pathlib import Path
root=Path(__file__).resolve().parents[1]
python=[]
for file in ('requirements.lock','requirements-dev.lock'):
    for line in (root/file).read_text().splitlines():
        if not line.strip() or line.startswith('#'):continue
        name=line.split('==')[0]
        meta=importlib.metadata.metadata(name)
        python.append({'name':name,'version':importlib.metadata.version(name),'license_expression':meta.get('License-Expression'),'license_metadata':meta.get('License'),'license_classifiers':[c for c in meta.get_all('Classifier',[]) if c.startswith('License ::')],'project_urls':meta.get_all('Project-URL',[])})
node=[]
lock=json.loads((root/'frontend/package-lock.json').read_text())
for path,entry in lock['packages'].items():
    if path:node.append({'package_path':path,'version':entry.get('version'),'license':entry.get('license'),'resolved':entry.get('resolved')})
(root/'docs/evidence/dependency-licenses.json').write_text(json.dumps({'python':python,'npm':node},indent=2),encoding='utf8')
print('Recorded installed Python license metadata and locked npm package license metadata.')
