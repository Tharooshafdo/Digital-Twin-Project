import copy
import json
import time
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
import pytest
from sqlalchemy import select, func, text
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from grid_twin import db, auth, service
from grid_twin.demo import demo_network
from grid_twin.domain import Network, Registry
from grid_twin.plugins import registry, TransformerPlugin, BasePlugin
from grid_twin.solver import solve_network
from grid_twin.worker import run_one, claim, calculate_frame, claim_outbox, complete_outbox
from grid_twin.mqtt import DurableInbox, commit_delivery
from grid_twin.ingestion import parse_csv
from tl_twin.alignment import assemble_frame
from tl_twin.contracts import Measurement
from conftest import make_job

def drain(platform, job_id):
    for _ in range(100):
        run_one(platform["engine"], "test-worker")
        with platform["engine"].connect() as conn:
            j = conn.execute(select(db.jobs).where(db.jobs.c.id == job_id)).mappings().one()
        if j["status"] in ("completed", "failed", "cancelled"):
            return dict(j)
        time.sleep(.005)
    raise AssertionError("Job did not finish")

def test_migrations_populated_upgrade(platform):
    cfg = Config("alembic.ini"); cfg.set_main_option("sqlalchemy.url", platform["url"])
    command.downgrade(cfg, "db9c94423c4d")
    command.upgrade(cfg, "head")
    with platform["engine"].connect() as conn:
        assert conn.scalar(select(func.count()).select_from(db.users)) == 1
        assert conn.scalar(select(func.count()).select_from(db.revisions)) == 1
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "0005"

def test_roles_and_project_scoping(platform):
    c = platform["client"]
    for role in ("viewer", "engineer"):
        created = c.post("/api/users", json={"username": role, "role": role, "project_ids": ["demo"]}).json()
        token = c.post("/api/auth/login", json={"username": role, "password": created["password"]}).json()["token"]
        client = TestClient(c.app); client.headers["Authorization"] = "Bearer "+token
        assert client.get("/api/projects/demo/revisions").status_code == 200
        assert client.get("/api/projects/other/revisions").status_code == 403
        body = {"name": role, "network": demo_network()}
        saved = client.post("/api/projects/demo/revisions", json=body)
        assert saved.status_code == (403 if role == "viewer" else 200)
        assert client.post(f"/api/projects/demo/revisions/{platform['rid']}/publish").status_code == 403
        assert client.post("/api/users", json={"username": "blocked", "role": "administrator", "project_ids": []}).status_code == 403
    assert TestClient(c.app).get("/api/projects").status_code == 401

@pytest.mark.parametrize("mutation", ["voltage", "missing_bus", "duplicate", "self_loop", "phase"])
def test_network_preflight(mutation):
    n = demo_network()
    line = next(c for c in n["components"] if c["type_id"] == "ac.line")
    if mutation == "voltage": line["terminals"][1]["bus_id"] = "BUS_D"
    if mutation == "missing_bus": line["terminals"][1]["bus_id"] = "MISSING"
    if mutation == "duplicate": n["components"].append(copy.deepcopy(line))
    if mutation == "self_loop": line["terminals"][1]["bus_id"] = line["terminals"][0]["bus_id"]
    if mutation == "phase": line["terminals"][0]["phases"] = "abc"
    with pytest.raises(ValueError): registry.validate(Network.model_validate(n))

def test_plugins_compatibility_and_real_transformer():
    r = Registry()
    incompatible = TransformerPlugin(); incompatible.platform = ">=10"
    with pytest.raises(ValueError): r.register(incompatible)
    result = solve_network(demo_network(), "snapshot")
    assert abs(result["active_power_balance_error_mw"]) < 1e-6
    assert result["components"]["TR_001"]["loading_percent"] > 0
    assert len({v["snapshot_id"] for v in result["components"].values()}) == 1

def test_plugin_extension_without_solver_edit():
    from grid_twin.domain import ShuntParameters
    class ReviewedCapacitor(BasePlugin):
        type_id = "example.capacitor"
        parameters = ShuntParameters
        terminal_names = ("bus",)
        adapter_method = "shunt"
    plugin = ReviewedCapacitor()
    registry.register(plugin)
    try:
        n = demo_network()
        t = copy.deepcopy(next(c for c in n["components"] if c["type_id"] == "ac.load_pq")["terminals"])
        n["components"].append({"id": "CAP", "name": "CAP", "type_id": plugin.type_id,
            "parameters": {"q_mvar": -2}, "terminals": t, "in_service": True, "position": {"x": 0, "y": 0}})
        result = solve_network(n, "plugin-example")
        assert result["components"]["CAP"]["q_mvar"] < 0
        assert abs(result["active_power_balance_error_mw"]) < 1e-6
    finally:
        del registry.plugins[plugin.type_id]

@pytest.mark.parametrize("case", ["island", "multiple_sources", "unsupported"])
def test_unsupported_island_reference_policy(case):
    n = demo_network()
    if case == "island": next(c for c in n["components"] if c["id"] == "TL_001")["in_service"] = False
    if case == "multiple_sources":
        source = copy.deepcopy(next(c for c in n["components"] if c["type_id"] == "ac.external_grid"))
        source["id"] = "GRID_2"; n["components"].append(source)
    if case == "unsupported":
        n["components"].append({"id": "BAT", "name": "Battery", "type_id": "catalog.battery", "parameters": {}, "terminals": [], "in_service": True})
    with pytest.raises(ValueError): solve_network(n, "failed")

def test_topology_save_reload_immutable_run(platform, dataset):
    c = platform["client"]
    n = demo_network()
    saved = c.post("/api/projects/demo/revisions", json={"name": "Draft", "network": n}).json()["id"]
    reloaded = next(r for r in c.get("/api/projects/demo/revisions").json() if r["id"] == saved)
    assert reloaded["payload"]["components"][0]["parameters"] == n["components"][0]["parameters"]
    j, manifest = make_job(platform, dataset[2]["frames"][:1])
    n["components"][0]["parameters"]["nominal_kv"] = 220
    with platform["engine"].connect() as conn:
        run = conn.execute(select(db.runs).where(db.runs.c.id == j["run_id"])).mappings().one()
    assert run["manifest"] == manifest | {"kind": "replay", "request_sha256": db.digest({"frames": dataset[2]["frames"][:1]})}
    assert c.put(f"/api/projects/demo/revisions/{platform['rid']}", json={}).status_code == 405
    assert c.post(f"/api/projects/demo/revisions/{saved}/publish").status_code == 422 # overlap

def test_csv_mapping_zero_bad_reject_and_timezone():
    raw = 't;v;p;q;quality\n01/01/2026 05:30;132100;0;0;ok\n01/01/2026 05:35;NA;0;0;bad\nbroken;1;1;1;ok\n'
    mapping = {"timezone": "Asia/Colombo", "date_format": "%d/%m/%Y %H:%M", "delimiter": ";",
        "timestamp_column": "t", "asset_id": "TL_001", "source_id": "test", "data_origin": "laboratory", "connection_state": "CONNECTED",
        "signals": {"vs_ll_kv": {"column": "v", "scale": .001, "missing_sentinels": ["NA"], "quality_column": "quality", "quality_map": {"ok": "GOOD", "bad": "BAD"}}, "p_recv_mw": {"column": "p"}, "q_recv_mvar": {"column": "q"}}}
    result = parse_csv(raw, mapping)
    assert len(result["frames"]) == 2 and len(result["rejects"]) == 1
    assert result["frames"][0]["event_time"] == "2026-01-01T00:00:00Z"
    assert result["frames"][0]["p_recv_mw"] == 0
    assert result["frames"][1]["vs_ll_kv"] is None
    assert result["manifest"]["rejected_rows"] == 1

def test_asof_does_not_hide_recent_bad(dataset):
    frame = dataset[2]["frames"][0]
    time0 = frame["event_time"]
    samples = {"vs_ll_kv": [{"event_time": "2025-12-31T23:59:59Z", "value": 132, "quality": "GOOD"},
        {"event_time": time0, "value": 133, "quality": "BAD"}]}
    result = assemble_frame(frame, samples)
    assert result.vs_ll_kv == 133 and result.signal_quality["vs_ll_kv"] == "BAD"
    assert "vs_ll_kv" in result.source_metadata["per_signal_event_time"]

@pytest.mark.parametrize("mode,delta,expected", [("live", -3600, "DATA_UNAVAILABLE"), ("live", 3600, "DATA_UNAVAILABLE"), ("replay", -3600, "SOLVED")])
def test_current_utc_freshness(platform, dataset, mode, delta, expected):
    _, manifest = make_job(platform, [], mode=mode)
    frame = copy.deepcopy(dataset[2]["frames"][0]); frame["event_time"] = (db.now()+timedelta(seconds=delta)).isoformat()
    _, s = calculate_frame(frame, manifest, "run", mode)
    assert s["model_status"] == expected
    if expected != "SOLVED": assert s["prediction"] is None and not s["residual_physics"]

def test_duplicate_conflicting_identity_restart_alarm_outbox(platform, dataset):
    frames = dataset[2]["frames"]
    conflict = copy.deepcopy(frames[0]); conflict["vs_ll_kv"] = 140
    j, _ = make_job(platform, [frames[0], frames[0], conflict, *frames[1:]])
    run_one(platform["engine"], "first-process")
    # Recreate engine: checkpoint survives process replacement.
    platform["engine"].dispose(); platform["engine"] = db.engine_for(platform["url"])
    job = drain(platform, j["job_id"])
    assert job["status"] == "completed" and job["checkpoint"] == 7
    with platform["engine"].connect() as conn:
        assert conn.scalar(select(func.count()).select_from(db.states)) == 5
        assert conn.scalar(select(func.count()).select_from(db.outbox)) == 5
        assert conn.scalar(select(func.count()).select_from(db.dead_letters)) == 1
        alarm = conn.execute(select(db.alarms)).mappings().one()
        assert alarm["active"] == 1 and alarm["count"] == 5

def test_job_ownership_race_and_expired_lease(platform, dataset):
    j, _ = make_job(platform, dataset[2]["frames"][:1])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda x: claim(platform["engine"], x), ["owner1", "owner2"]))
    assert sum(r is not None for r in results) == 1
    with platform["engine"].begin() as conn:
        conn.execute(db.jobs.update().where(db.jobs.c.id == j["job_id"]).values(lease_until=time.time()-1))
    assert claim(platform["engine"], "replacement")["id"] == j["job_id"]

def test_outbox_recovery_ownership(platform, dataset):
    j, _ = make_job(platform, dataset[2]["frames"][:1]); drain(platform, j["job_id"])
    out = claim_outbox(platform["engine"], "one")
    assert out and claim_outbox(platform["engine"], "two") is None
    assert complete_outbox(platform["engine"], "wrong-owner", out["id"]) == 0
    with platform["engine"].begin() as conn:
        conn.execute(db.outbox.update().values(lease_until=time.time()-1))
    assert claim_outbox(platform["engine"], "two")["id"] == out["id"]
    assert complete_outbox(platform["engine"], "two", out["id"]) == 1

def test_raw_residual_and_covariance(platform, dataset):
    _, manifest = make_job(platform, [])
    frame = copy.deepcopy(dataset[2]["frames"][0]); frame["uncertainty"]={"p_send_mw": .03, "p_recv_mw": .03}
    frame["source_metadata"]["power_error_correlation"] = 1
    _, state = calculate_frame(frame, manifest, "run", "replay")
    changed = copy.deepcopy(frame); changed["vr_ll_kv"] += 10
    _, second = calculate_frame(changed, manifest, "run", "replay")
    assert state["prediction"] == second["prediction"]
    assert second["residual_physics"]["vr_ll_kv"]-state["residual_physics"]["vr_ll_kv"] == pytest.approx(10)
    assert state["loss_measurement_sigma_mw"] == 0

def test_alarm_missing_late_duplicate_do_not_clear(platform, dataset):
    frames=copy.deepcopy(dataset[2]["frames"])
    j,_=make_job(platform,frames[:3]);drain(platform,j["job_id"])
    with platform["engine"].begin() as conn:
        old=conn.execute(select(db.alarms)).mappings().one()
        missing={"run_id":j["run_id"],"asset_id":"TL_001","event_time":frames[3]["event_time"],"model_status":"INPUTS_INSUFFICIENT","freshness":"FRESH","residual_physics":{}}
        service.update_alarm(conn,"demo",missing,{"high_kv":.08,"clear_kv":.04,"consecutive":3})
        late={**missing,"event_time":frames[0]["event_time"],"model_status":"SOLVED","residual_physics":{"vr_ll_kv":0}}
        service.update_alarm(conn,"demo",late,{"high_kv":.08,"clear_kv":.04,"consecutive":3})
    with platform["engine"].connect() as conn:
        alarm=conn.execute(select(db.alarms)).mappings().one()
        assert alarm["active"]==1 and alarm["count"]==3 and alarm["payload"]["data_quality_condition"]

def test_mqtt_durable_commit_dead_letter_and_overload(platform,dataset):
    j,_=make_job(platform,[])
    frame=dataset[2]["frames"][0]
    topic='dt/v1/project/demo/input/line/TL_001/measurement'
    assert commit_delivery(platform["engine"],"demo",j["run_id"],topic,json.dumps(frame))=='committed'
    assert commit_delivery(platform["engine"],"demo",j["run_id"],topic,json.dumps(frame))=='committed'
    changed={**frame,"vs_ll_kv":140}
    assert commit_delivery(platform["engine"],"demo",j["run_id"],topic,json.dumps(changed))=='dead_letter'
    assert commit_delivery(platform["engine"],"demo",j["run_id"],topic,'broken')=='dead_letter'
    inbox=DurableInbox(1)
    assert inbox.receive(object()) and not inbox.receive(object()) and inbox.overloaded.is_set()

def test_real_api_import_replay_report_lineage_export(platform,dataset):
    c=platform["client"];raw,mapping,_=dataset
    body={"filename":"demo.csv","raw_text":raw,"mapping":mapping}
    preview=c.post('/api/projects/demo/imports/preview',json=body).json()
    assert preview["manifest"]["accepted_rows"]==5 and preview["manifest"]["rejected_rows"]==1
    imported=c.post('/api/projects/demo/imports',json=body).json()
    assert len(c.get(f"/api/projects/demo/imports/{imported['id']}/rejects").json()["items"])==1
    study=c.post('/api/projects/demo/studies',json={"revision_id":platform["rid"],"kind":"replay","import_id":imported["id"],"speed":100000}).json()
    assert drain(platform,study["job_id"])["status"]=='completed'
    prefix=f"/api/projects/demo/runs/{study['run_id']}"
    h=c.get(prefix+'/history?limit=2&offset=1').json();assert h["total"]==5 and len(h["items"])==2
    report=c.get(prefix+'/report').json();assert report["usable"]==5 and report["voltage_kv"]["mae"]>.08
    assert 'dataset_manifest' in report["manifest"]
    assert 'manifest_sha256' in c.get(prefix+'/export?format=csv').text
    assert 'Synthetic/reference' in c.get(prefix+'/export?format=html').text
    assert c.get('/api/projects/other/runs/'+study['run_id']+'/export').status_code==403
    alarm=c.get('/api/projects/demo/alerts').json()[0]
    assert c.post(f"/api/projects/demo/alerts/{alarm['id']}/acknowledge").status_code==200

@pytest.mark.parametrize('kind',['network','scenario','estimation','thermal','three_phase','fault','sag'])
def test_persisted_research_and_scenario(platform,kind):
    n=demo_network()
    payload={'network':n,'inputs':{'span_m':300,'weight_n_per_m':12,'horizontal_tension_n':20000}}
    if kind=='scenario':
        for c in n['components']:
            if c['type_id']=='ac.load_pq':c['parameters']['p_mw']*=1.1
    j,_=make_job(platform,[],kind,payload)
    job=drain(platform,j['job_id']);assert job['status']=='completed',job['error']
    with platform['engine'].connect() as conn:
        report=conn.execute(select(db.entities['validation_reports']).where(db.entities['validation_reports'].c.id==j['run_id'])).mappings().one()
    assert report['payload']['manifest_sha256']
    if kind=='scenario':assert report['payload']['loss_delta_mw']>0
    if kind=='sag':assert report['payload']['clearance_status']=='UNAVAILABLE'
    if kind=='thermal':assert report['payload']['elapsed_s']==600

def test_pause_resume_cancel_and_backlog(platform,dataset):
    j,_=make_job(platform,dataset[2]['frames'])
    c=platform['client'];prefix=f"/api/projects/demo/jobs/{j['job_id']}/control"
    assert c.post(prefix,json={'action':'pause'}).json()['status']=='paused'
    assert claim(platform['engine'],'paused-worker') is None
    assert c.post(prefix,json={'action':'resume','speed':1000}).status_code==200
    assert c.post(prefix,json={'action':'cancel'}).json()['status']=='cancelled'
    assert claim(platform['engine'],'cancelled-worker') is None

def test_new_immutable_timeline_and_event_selection(platform,dataset):
    c=platform['client'];n=demo_network()
    line=next(v for v in n['components'] if v['id']=='TL_001');line['parameters']['r_ohm_per_km']=.09
    # New effective revision starts between the first and second measurement.
    j,old_manifest=make_job(platform,dataset[2]['frames'][:1])
    saved=c.post('/api/projects/demo/revisions',json={'name':'Later approved parameters','network':n,'valid_from':'2026-01-01T00:05:00Z'}).json()['id']
    assert c.post(f'/api/projects/demo/revisions/{saved}/publish').status_code==200
    with platform['engine'].connect() as conn:
        new=service.run_manifest(conn,'demo',saved,'replay')
        old_run=conn.execute(select(db.runs.c.manifest).where(db.runs.c.id==j['run_id'])).scalar_one()
        assert old_run['timeline_id']==old_manifest['timeline_id']
        assert len(old_run['timeline']['intervals'])==1
        assert len(new['timeline']['intervals'])==2
    _,first=calculate_frame(dataset[2]['frames'][0],new,'run','replay')
    _,second=calculate_frame(dataset[2]['frames'][1],new,'run','replay')
    assert first['topology_version']==platform['rid']
    assert second['topology_version']==saved
    assert second['prediction']['r_used_ohm_per_km']==.09

def test_natural_identity_conflict(platform,dataset):
    j,_=make_job(platform,dataset[2]['frames'][:1]);drain(platform,j['job_id'])
    frame=copy.deepcopy(dataset[2]['frames'][0]);frame['message_id']='different-message-same-source-identity'
    assert commit_delivery(platform['engine'],'demo',j['run_id'],'dt/v1/project/demo/input/line/TL_001/measurement',json.dumps(frame))=='dead_letter'

@pytest.mark.parametrize('p,q',[(66.8,13.5),(-30,-5),(0,0)])
def test_sectioned_electrical_cascade_and_connected(p,q):
    from grid_twin.electrical import solve_sectioned
    from grid_twin.solver import line_config
    n=demo_network();c=next(v for v in n['components'] if v['id']=='TL_001')
    c['parameters']['sections']=[dict(name='overhead',line_type='ol',length_km=40,r_ohm_per_km=.08,x_ohm_per_km=.35,c_nf_per_km=9,max_i_ka=.6,parameter_source='Synthetic overhead section',rating_source='Illustrative overhead circuit rating'),dict(name='cable',line_type='cs',length_km=25,r_ohm_per_km=.07,x_ohm_per_km=.15,c_nf_per_km=80,max_i_ka=.5,parameter_source='Synthetic cable electrical section',rating_source='Separate illustrative cable rating; no cable thermal model')]
    cfg=line_config(c,'sections')
    a,b=solve_sectioned(c,cfg,132.1,p,q)
    for key in ('vr_ll_kv','is_a','ir_a','p_send_mw','q_send_mvar','loss_mw'):
        assert a[key]==pytest.approx(b[key],rel=1e-7,abs=1e-7)
    assert a['sections'][1]['line_type']=='cs'
    connected=solve_network(n,'sections.connected')
    assert abs(connected['active_power_balance_error_mw'])<1e-6

def test_populated_natural_identity_upgrade(tmp_path,dataset):
    cfg=Config('alembic.ini');url='sqlite:///'+str(tmp_path/'populated.db').replace('\\','/');cfg.set_main_option('sqlalchemy.url',url)
    command.upgrade(cfg,'0002')
    engine=db.engine_for(url)
    with engine.begin() as conn:
        conn.execute(db.projects.insert().values(id='demo',name='Populated migration',created_at=db.now()))
        m=dataset[2]['frames'][0]
        conn.execute(text('INSERT INTO measurements(id,project_id,message_id,asset_id,event_time,received_at,payload_hash,payload) VALUES(:id,:pid,:mid,:asset,:event,:received,:hash,:payload)'),{'id':'legacy','pid':'demo','mid':m['message_id'],'asset':m['asset_id'],'event':m['event_time'],'received':m['event_time'],'hash':db.digest(m),'payload':json.dumps(m)})
    command.upgrade(cfg,'head')
    with engine.connect() as conn:
        row=conn.execute(select(db.measurements)).mappings().one()
        assert row['natural_key']==db.digest([m[k] for k in ('dataset_id','source_id','asset_id','event_time','sequence_no')])

def test_transformer_taps_and_simulated_switch():
    n=demo_network();baseline=solve_network(n,'baseline')
    next(c for c in n['components'] if c['id']=='TR_001')['parameters']['tap_pos']=2
    tapped=solve_network(n,'tapped')
    assert tapped['components']['BUS_D']['voltage_kv']<baseline['components']['BUS_D']['voltage_kv']
    first=next(c for c in n['components'] if c['id']=='TL_001');first['in_service']=False
    switch={'id':'SIM_COUPLER','name':'Simulation bus coupler','type_id':'ac.switch','parameters':{'closed':True},'terminals':first['terminals'],'in_service':True}
    n['components'].append(switch)
    assert solve_network(n,'closed')['components']['SIM_COUPLER']['closed']
    switch['parameters']['closed']=False
    with pytest.raises(ValueError):solve_network(n,'open')

def test_installed_approved_example_plugin():
    from grid_twin.plugins import enable_reviewed_plugins
    enable_reviewed_plugins(['teaching_capacitor'])
    try:assert registry.plugins['example.teaching_capacitor'].platform=='>=0.1,<0.2'
    finally:del registry.plugins['example.teaching_capacitor']
    with pytest.raises(ValueError):enable_reviewed_plugins(['unreviewed_missing_plugin'])
