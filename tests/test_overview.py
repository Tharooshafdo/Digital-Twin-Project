import copy
from datetime import timedelta
import pytest
from sqlalchemy import select, func
from grid_twin import db, overview, worker, auth

BASE='/api/projects/demo'

def observation(platform, **changes):
    return {'snapshot_id':db.uid('sample'),'revision_id':platform['rid'],
        'event_time':db.iso(db.now()),'source_id':'test.readonly.gateway','data_origin':'field',
        'frequency_hz':{'value':49.97,'quality':'GOOD'},
        'total_demand_mw':{'value':68.25,'quality':'GOOD'},
        'bus_voltages_kv':[{'asset_id':'BUS_A','value':132.1,'quality':'GOOD'},
            {'asset_id':'BUS_D','value':32.2,'quality':'GOOD'}],**changes}

def scenario(platform, factor=1.2):
    client=platform['client']
    network=client.get(BASE+'/revisions/'+platform['rid']).json()['payload']
    for c in network['components']:
        if c['type_id']=='ac.load_pq':
            c['parameters']['p_mw']*=factor;c['parameters']['q_mvar']*=factor
    response=client.post(BASE+'/studies',json={'revision_id':platform['rid'],'kind':'scenario',
        'scenario':network,'mode':'offline'})
    assert response.status_code==200,response.text
    return response.json(),network

def test_overview_synthetic_stream_locations_and_cadence(platform):
    client=platform['client'];clock=db.now()
    initial=client.get(BASE+'/overview').json()
    assert len(initial['components'])==11 and initial['unlocated_assets']==0
    assert all(c['location']['provenance']=='illustrative' for c in initial['components'])
    assert initial['telemetry']['status']=='NO_SOURCE'
    overview.tick_demo(platform['engine'],clock);overview.tick_demo(platform['engine'],clock)
    result=client.get(BASE+'/overview').json()
    assert result['telemetry']['status']=='FRESH'
    assert 65 < result['telemetry']['total_demand_mw'] < 71
    assert 49.97 < result['telemetry']['frequency_hz'] < 50.03
    assert result['telemetry']['snapshot']['simulation']['model_status']=='SOLVED'
    assert len([c for c in result['components'] if c['voltage_kv'] is not None])==4
    with platform['engine'].connect() as conn:
        assert conn.scalar(select(func.count()).select_from(db.entities['grid_observations']))==1
    live=client.get(BASE+'/overview?mode=live').json()['telemetry']
    assert live['status']=='NO_SOURCE' and live['total_demand_mw'] is None

@pytest.mark.parametrize('delta,status',[(0,'FRESH'),(-121,'STALE'),(6,'FUTURE')])
def test_live_grid_freshness_and_unavailable_values(platform,delta,status):
    payload=observation(platform,event_time=db.iso(db.now()+timedelta(seconds=delta)))
    client=platform['client'];assert client.post(BASE+'/grid-observations',json=payload).status_code==200
    result=client.get(BASE+'/overview?mode=live').json()
    assert result['telemetry']['status']==status
    assert result['telemetry']['data_origin']=='field'
    assert result['telemetry']['total_demand_mw']==(68.25 if status=='FRESH' else None)
    assert next(c for c in result['components'] if c['id']=='BUS_A')['voltage_kv']==(132.1 if status=='FRESH' else None)

@pytest.mark.parametrize('quality',['BAD','SUSPECT','MISSING'])
def test_newest_bad_grid_sample_does_not_use_previous_good(platform,quality):
    client=platform['client'];clock=db.now()
    old=observation(platform,event_time=db.iso(clock-timedelta(seconds=2)))
    recent=observation(platform,event_time=db.iso(clock-timedelta(seconds=1)),
        frequency_hz={'value':50,'quality':quality},total_demand_mw={'value':70,'quality':quality},
        bus_voltages_kv=[{'asset_id':'BUS_A','value':0,'quality':quality}])
    for payload in (old,recent):assert client.post(BASE+'/grid-observations',json=payload).status_code==200
    result=client.get(BASE+'/overview?mode=live').json()
    assert result['telemetry']['frequency_hz'] is None and result['telemetry']['total_demand_mw'] is None
    assert result['telemetry']['frequency_quality']==quality
    assert next(c for c in result['components'] if c['id']=='BUS_A')['voltage_kv'] is None

def test_zero_voltage_grid_identity_validation_and_source_selection(platform):
    client=platform['client'];payload=observation(platform,bus_voltages_kv=[{'asset_id':'BUS_A','value':0}])
    assert client.post(BASE+'/grid-observations',json=payload).status_code==200
    assert client.post(BASE+'/grid-observations',json=payload).json()['duplicate'] is True
    changed=copy.deepcopy(payload);changed['total_demand_mw']['value']=900
    assert client.post(BASE+'/grid-observations',json=changed).status_code==422
    result=client.get(BASE+'/overview?mode=live&source_id=test.readonly.gateway').json()
    assert next(c for c in result['components'] if c['id']=='BUS_A')['voltage_kv']==0
    assert client.get(BASE+'/overview?mode=live&source_id=absent').json()['telemetry']['status']=='NO_SOURCE'
    invalid=observation(platform,bus_voltages_kv=[{'asset_id':'TL_001','value':132}])
    assert client.post(BASE+'/grid-observations',json=invalid).status_code==422
    invalid=observation(platform,event_time='2026-10-03T12:00:00')
    assert client.post(BASE+'/grid-observations',json=invalid).status_code==422
    invalid=observation(platform,bus_voltages_kv=[{'asset_id':'BUS_A','value':1},{'asset_id':'BUS_A','value':2}])
    assert client.post(BASE+'/grid-observations',json=invalid).status_code==422

def test_coordinates_persist_without_changing_topology(platform):
    client=platform['client'];before=client.get(BASE+'/revisions/'+platform['rid']).json()
    payload={'locations':[{'asset_id':'BUS_A','latitude':6.91,'longitude':79.84,'label':'User location','provenance':'surveyed'}]}
    assert client.put(BASE+'/locations',json=payload).status_code==200
    result=client.get(BASE+'/overview').json()
    assert next(c for c in result['components'] if c['id']=='BUS_A')['location']['latitude']==6.91
    assert client.get(BASE+'/revisions/'+platform['rid']).json()==before
    payload['locations'][0]['latitude']=91
    assert client.put(BASE+'/locations',json=payload).status_code==422
    payload['locations'][0].update(latitude=6.9,asset_id='unknown')
    assert client.put(BASE+'/locations',json=payload).status_code==422

def test_successful_simulation_apply_preserves_history_and_is_idempotent(platform):
    client=platform['client'];study,network=scenario(platform)
    assert client.post(BASE+'/simulations/apply',json={'run_id':study['run_id']}).status_code==422
    worker.run_one(platform['engine'],'test-overview')
    report=client.get(BASE+'/runs/'+study['run_id']+'/report').json()
    assert report['research_results'][0]['payload']['scenario']['demand_mw']==pytest.approx(81.6)
    original_manifest=copy.deepcopy(report['manifest'])
    response=client.post(BASE+'/simulations/apply',json={'run_id':study['run_id'],'name':'Test reviewed change'})
    assert response.status_code==200,response.text
    applied=response.json();assert applied['physical_commands'] is False
    revision=client.get(BASE+'/revisions/'+applied['revision_id']).json()
    assert revision['status']=='published' and revision['parent_id']==platform['rid']
    assert next(c for c in revision['payload']['components'] if c['id']=='LOAD_C')['parameters']['p_mw']==48
    assert client.get(BASE+'/overview').json()['revision_id']==applied['revision_id']
    assert client.get(BASE+'/runs/'+study['run_id']+'/report').json()['manifest']==original_manifest
    again=client.post(BASE+'/simulations/apply',json={'run_id':study['run_id']}).json()
    assert again['revision_id']==applied['revision_id'] and again['already_applied']

def test_simulation_cannot_apply_against_a_changed_baseline(platform):
    client=platform['client'];one,_=scenario(platform);two,_=scenario(platform,1.1)
    worker.run_one(platform['engine'],'first');worker.run_one(platform['engine'],'second')
    assert client.post(BASE+'/simulations/apply',json={'run_id':one['run_id']}).status_code==200
    rejected=client.post(BASE+'/simulations/apply',json={'run_id':two['run_id']})
    assert rejected.status_code==422 and 'baseline changed' in rejected.text

def test_overview_permissions_and_project_scope(platform):
    client=platform['client']
    with platform['engine'].begin() as conn:
        viewer=auth.create_user(conn,'overview_viewer','viewer',['demo'])
    login=client.post('/api/auth/login',json={'username':viewer['username'],'password':viewer['password']}).json()
    client.headers['Authorization']='Bearer '+login['token']
    assert client.get(BASE+'/overview').status_code==200
    assert client.post(BASE+'/grid-observations',json=observation(platform)).status_code==403
    assert client.put(BASE+'/locations',json={'locations':[]}).status_code==403
    assert client.post(BASE+'/simulations/apply',json={'run_id':'unknown'}).status_code==403
    assert client.get('/api/projects/other/overview').status_code==403

def test_grid_overview_populated_upgrade(platform):
    from alembic.config import Config
    from alembic import command
    config=Config('alembic.ini');config.set_main_option('sqlalchemy.url',platform['url'])
    with platform['engine'].connect() as conn:
        original=conn.scalar(select(db.revisions.c.payload_hash).where(db.revisions.c.id==platform['rid']))
    command.downgrade(config,'0005');command.upgrade(config,'head')
    with platform['engine'].connect() as conn:
        assert conn.scalar(select(db.revisions.c.payload_hash).where(db.revisions.c.id==platform['rid']))==original
        assert conn.scalar(select(func.count()).select_from(db.users))==1
        overview.seed_demo_locations(conn)

def test_legacy_published_baseline_without_timeline_is_visible(platform):
    with platform['engine'].begin() as conn:
        conn.execute(db.entities['topology_timelines'].delete().where(db.entities['topology_timelines'].c.project_id=='demo'))
    response=platform['client'].get(BASE+'/overview').json()
    assert response['revision_id']==platform['rid'] and len(response['components'])==11
    overview.tick_demo(platform['engine'])
    assert platform['client'].get(BASE+'/overview').json()['telemetry']['status']=='FRESH'

def test_failed_simulation_cannot_be_applied(platform):
    client=platform['client'];network=client.get(BASE+'/revisions/'+platform['rid']).json()['payload']
    next(c for c in network['components'] if c['id']=='TL_002')['in_service']=False
    response=client.post(BASE+'/studies',json={'revision_id':platform['rid'],'kind':'scenario','scenario':network,'mode':'offline'})
    assert response.status_code==200
    run=response.json()['run_id'];worker.run_one(platform['engine'],'failed-simulation')
    job=next(j for j in client.get(BASE+'/jobs').json() if j['run_id']==run)
    assert job['status']=='failed' and 'external reference' in job['error']
    assert client.post(BASE+'/simulations/apply',json={'run_id':run}).status_code==422
    assert client.get(BASE+'/overview').json()['revision_id']==platform['rid']

def test_observation_revision_is_selected_as_of_event_time(platform):
    client=platform['client'];study,_=scenario(platform);worker.run_one(platform['engine'],'apply-time')
    applied=client.post(BASE+'/simulations/apply',json={'run_id':study['run_id']}).json()['revision_id']
    stale_revision=observation(platform)
    response=client.post(BASE+'/grid-observations',json=stale_revision)
    assert response.status_code==422 and 'event time' in response.text
    assert client.post(BASE+'/grid-observations',json=observation(platform,revision_id=applied)).status_code==200
