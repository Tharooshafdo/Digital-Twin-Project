"""Windows API/worker process recreation with persistent checkpoint and session."""
import json,time,subprocess,os
from pathlib import Path
import httpx
from grid_twin.demo import demo_csv
root=Path(__file__).resolve().parents[1]
test_env={**os.environ,'GRID_TWIN_JOB_LEASE_S':'15'}
def services(action,env):
    with (root/'data/runtime-launch.log').open('a') as log:
        subprocess.run(['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(root/f'tools/{action}.ps1')],check=True,cwd=root,stdout=log,stderr=subprocess.STDOUT,env=env)
# Use an explicit short qualification lease for subsecond fixture solves.
# Restore the normal environment after the check. Scientific tolerances are unchanged.
services('stop',os.environ);services('start',test_env)
credential=json.loads((root/'data/initial-credentials.json').read_text())
client=httpx.Client(base_url='http://127.0.0.1:8000',timeout=30)
token=client.post('/api/auth/login',json={'username':credential['username'],'password':credential['password']}).json()['token']
client.headers['Authorization']='Bearer '+token
before=client.get('/api/projects/demo/runs').json();immutable={r['id']:r['manifest'] for r in before}
revision=next(r for r in client.get('/api/projects/demo/revisions').json() if r['status']=='published')
raw,mapping=demo_csv(6)
imp=client.post('/api/projects/demo/imports',json={'filename':'runtime-recovery.csv','raw_text':raw,'mapping':mapping}).json()
job=client.post('/api/projects/demo/studies',json={'kind':'replay','revision_id':revision['id'],'import_id':imp['id'],'speed':600}).json()
for _ in range(120):
    state=next(j for j in client.get('/api/projects/demo/jobs').json() if j['id']==job['job_id'])
    if 0<state['checkpoint']<6:break
    time.sleep(.25)
assert 0<state['checkpoint']<6,state
checkpoint=state['checkpoint']
services('stop',test_env);services('start',test_env)
client.close();client=httpx.Client(base_url='http://127.0.0.1:8000',headers={'Authorization':'Bearer '+token},timeout=30)
for _ in range(1600):
    state=next(j for j in client.get('/api/projects/demo/jobs').json() if j['id']==job['job_id'])
    if state['status'] in ('completed','failed'):break
    time.sleep(.25)
assert state['status']=='completed',state
history=client.get('/api/projects/demo/runs/'+job['run_id']+'/history').json()
assert history['total']==6 and len({s['message_id'] for s in history['items']})==6
after=client.get('/api/projects/demo/runs').json()
assert all(r['manifest']==immutable[r['id']] for r in after if r['id'] in immutable)
result={'platform':'Windows','status':'PASS','qualification_job_lease_s':15,'default_job_lease_s':300,'checkpoint_before_restart':checkpoint,'checkpoint_after_restart':state['checkpoint'],'committed_states':history['total'],'duplicate_state_ids':0,'prior_manifests_unchanged':True,'session_survived_recreation':True,'run_id':job['run_id'],'database':'SQLite'}
(root/'docs/evidence/runtime-recovery.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
client.close();services('stop',test_env);services('start',os.environ)
