import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from sqlalchemy import select,func
from grid_twin import db,service
from conftest import make_job
from test_platform import drain

def test_sqlite_backup_restore_isolated(platform,dataset):
    j,_=make_job(platform,dataset[2]['frames'][:2]);drain(platform,j['job_id'])
    backup=platform['tmp']/'backup.db';restored=platform['tmp']/'restored.db'
    subprocess.run([sys.executable,'-m','grid_twin.cli','--db',platform['url'],'backup','--out',str(backup)],check=True,capture_output=True)
    subprocess.run([sys.executable,'-m','grid_twin.cli','--db','sqlite:///'+str(restored).replace('\\','/'),'restore','--input',str(backup)],check=True,capture_output=True)
    with db.engine_for('sqlite:///'+str(restored).replace('\\','/')).connect() as conn:
        assert conn.scalar(select(func.count()).select_from(db.states))==2
        assert conn.scalar(select(func.count()).select_from(db.outbox))==2
    denied=subprocess.run([sys.executable,'-m','grid_twin.cli','--db','sqlite:///'+str(restored).replace('\\','/'),'restore','--input',str(backup)],capture_output=True)
    assert denied.returncode!=0

def test_versioned_alarm_policy_and_asof_snapshot(platform,dataset):
    c=platform['client'];prefix='/api/projects/demo'
    with platform['engine'].connect() as conn:old=service.run_manifest(conn,'demo',platform['rid'],'replay')
    assert c.post(prefix+'/alarm-policy',json={'high_kv':.5,'clear_kv':.6,'consecutive':3}).status_code==422
    published=c.post(prefix+'/alarm-policy',json={'high_kv':.5,'clear_kv':.2,'consecutive':4})
    assert published.status_code==200
    with platform['engine'].connect() as conn:new=service.run_manifest(conn,'demo',platform['rid'],'replay')
    assert old['alarm_policy']['high_kv']==.08 and new['alarm_policy']['high_kv']==.5
    assert new['alarm_policy_version']==published.json()['id']
    frame=dataset[2]['frames'][0]
    samples={k:[{'event_time':frame['event_time'],'value':frame[k],'quality':'GOOD'}] for k in ('vs_ll_kv','p_recv_mw','q_recv_mvar','vr_ll_kv')}
    response=c.post(prefix+'/signal-snapshots',json={'revision_id':platform['rid'],'envelope':frame,'samples':samples})
    assert response.status_code==200
    j=response.json();assert drain(platform,j['job_id'])['status']=='completed'
    h=c.get(prefix+f"/runs/{j['run_id']}/history").json()['items'][0]
    assert h['model_status']=='SOLVED' and len(h['measurement']['source_metadata']['per_signal_event_time'])==4

def test_retention_archive_blocks_unpublished_and_preserves_manifest(platform,dataset):
    from grid_twin.retention import archive_runs
    import gzip
    j,_=make_job(platform,dataset[2]['frames'][:2]);drain(platform,j['job_id'])
    result=archive_runs(platform['engine'],'demo',0,platform['tmp']/'archive',False)
    assert any(r['run_id']==j['run_id'] for r in result['skipped'])
    with platform['engine'].begin() as conn:conn.execute(db.outbox.update().values(published_at=db.now()))
    plan=archive_runs(platform['engine'],'demo',0,platform['tmp']/'archive',False)
    assert plan['eligible'][0]['states']==2 and not plan['archived']
    archived=archive_runs(platform['engine'],'demo',0,platform['tmp']/'archive',True)
    with gzip.open(archived['archived'][0]['file'],'rt') as handle:records=[json.loads(s) for s in handle]
    assert records[0]['run']['manifest'] and len(records)==3
    with platform['engine'].connect() as conn:
        assert conn.scalar(select(func.count()).select_from(db.states))==0
        assert service.report_data(conn,'demo',j['run_id'])['archival_history'][0]['report']['usable']==2

def test_calibration_candidate_complete_path(platform):
    from grid_twin.demo import demo_csv
    raw,mapping=demo_csv(80);c=platform['client']
    imp=c.post('/api/projects/demo/imports',json={'filename':'calibration.csv','raw_text':raw,'mapping':mapping}).json()
    r=c.post('/api/projects/demo/studies',json={'revision_id':platform['rid'],'kind':'calibration','import_id':imp['id'],'asset_id':'TL_001','max_weighted_rmse':3}).json()
    outcome=drain(platform,r['job_id']);assert outcome['status']=='completed',outcome['error']
    report=c.get('/api/projects/demo/runs/'+r['run_id']+'/report').json()
    fit=report['research_results'][0]['payload']
    assert fit['fit_success'] and not fit['automatic_parameter_update']
    assert fit['acceptance_criteria']=={'max_weighted_rmse':3}
    assert report['manifest']['dataset_manifest']['accepted_rows']==80
    assert len(c.get('/api/projects/demo/revisions').json())==1

def test_bounded_job_backlog(platform,dataset):
    with platform['engine'].begin() as conn:
        manifest=service.run_manifest(conn,'demo',platform['rid'],'replay')
        for _ in range(100):service.enqueue(conn,'demo','replay',{'frames':dataset[2]['frames'][:1]},manifest,'test')
        import pytest
        with pytest.raises(OverflowError):service.enqueue(conn,'demo','replay',{'frames':[]},manifest,'test')

def test_noneditable_package_layout_finds_runtime_resources(tmp_path):
    import shutil,os
    root=Path(__file__).resolve().parents[1]
    installed=tmp_path/'site-packages'
    for package in ('grid_twin','tl_twin'):shutil.copytree(root/'src'/package,installed/package)
    env={**os.environ,'PYTHONPATH':str(installed),'GRID_TWIN_ROOT':str(root)}
    url='sqlite:///'+str(tmp_path/'packaged.db').replace('\\','/')
    result=subprocess.run([sys.executable,'-m','grid_twin.cli','--db',url,'init'],cwd=root,env=env,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)['status']=='initialized'
    with db.engine_for(url).connect() as conn:
        assert conn.scalar(select(func.count()).select_from(db.revisions))==1
