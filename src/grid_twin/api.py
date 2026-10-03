import csv
import io
import json
import html
import os
import time
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, Depends, Query
from fastapi.responses import JSONResponse, StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, func, text
from sqlalchemy.exc import IntegrityError
from . import db, auth, service
from .domain import Network
from .plugins import registry
from .ingestion import parse_csv
from . import overview

class Body(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
class Login(Body):
    username: str
    password: str
class ProjectRequest(Body):
    name: str = Field(min_length=1, max_length=200)
class RevisionRequest(Body):
    name: str = Field(min_length=1, max_length=200)
    network: Network
    valid_from: str = "2020-01-01T00:00:00Z"
    valid_to: str | None = None
    parent_id: str | None = None
class ImportRequest(Body):
    filename: str = Field(max_length=200)
    raw_text: str = Field(max_length=8_000_000)
    mapping: dict
class SignalSnapshotRequest(Body):
    revision_id: str
    envelope: dict
    samples: dict
    max_age_s: float = Field(default=10,ge=0,le=3600)
    max_skew_s: float = Field(default=2,ge=0,le=3600)
    mode: str = "replay"
class StudyRequest(Body):
    revision_id: str
    kind: str
    import_id: str | None = None
    inputs: dict = Field(default_factory=dict)
    scenario: Network | None = None
    speed: float = Field(default=600, gt=0, le=100000)
    mode: str = "replay"
    asset_id: str = "TL_001"
    max_weighted_rmse: float = Field(default=3, gt=0)
class UserRequest(Body):
    username: str
    role: str
    project_ids: list[str]
class ControlRequest(Body):
    action: str
    speed: float | None = Field(default=None, gt=0, le=100000)
class AlarmPolicy(Body):
    high_kv: float = Field(gt=0)
    clear_kv: float = Field(ge=0)
    consecutive: int = Field(ge=1, le=1000)

class LocationsRequest(Body):
    locations: list[overview.AssetLocation] = Field(max_length=2000)

class ApplySimulation(Body):
    run_id: str
    name: str = Field(default='Reviewed simulation', min_length=1, max_length=200)

def create_app(database_url=None, frontend_dir=None):
    app = FastAPI(title="Power System Twin", version="0.1.0")
    engine = db.engine_for(database_url)
    app.state.engine = engine
    login_attempts = {}

    @app.exception_handler(ValueError)
    async def value_error(_, exc):
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    @app.exception_handler(IntegrityError)
    async def identity_error(_, exc):
        return JSONResponse(status_code=409, content={"detail": "Conflicting identity or referenced entity"})
    @app.exception_handler(OverflowError)
    async def overload(_, exc):
        return JSONResponse(status_code=429, content={"detail": str(exc)})

    def user(request: Request):
        header = request.headers.get("authorization", "")
        token = header[7:] if header.startswith("Bearer ") else None
        with engine.connect() as conn:
            result = auth.current_user(conn, token)
        if not result:
            raise HTTPException(401, "Login required")
        return result
    def access(conn, u, project_id, role="viewer"):
        if not auth.allowed(conn, u, project_id, role):
            raise HTTPException(403, "Project membership or role denied")

    @app.get("/api/health")
    def health():
        return {"status": "alive"}
    @app.get("/api/ready")
    def ready():
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT version_num FROM alembic_version"))
            return {"status": "ready", "database": engine.dialect.name}
        except Exception:
            raise HTTPException(503, "Database schema unavailable; run grid-twin init")
    @app.post("/api/auth/login")
    def login(body: Login, request: Request):
        key = request.client.host if request.client else "local"
        clock = time.monotonic()
        recent = [t for t in login_attempts.get(key, []) if clock-t < 60]
        if len(recent) >= 20:
            raise HTTPException(429, "Wait one minute before retrying login")
        login_attempts[key] = [*recent, clock]
        try:
            with engine.begin() as conn:
                token, account = auth.login(conn, body.username, body.password)
                db.audit_event(conn, account["id"], "login")
            return {"token": token, "user": account}
        except ValueError:
            raise HTTPException(401, "Invalid credentials")
    @app.get("/api/auth/me")
    def me(u=Depends(user)):
        return {k: u[k] for k in ("id", "username", "role")}
    @app.post("/api/auth/logout")
    def logout(request: Request, u=Depends(user)):
        import hashlib
        token = request.headers["authorization"][7:]
        with engine.begin() as conn:
            conn.execute(db.sessions.delete().where(db.sessions.c.token_hash == hashlib.sha256(token.encode()).hexdigest()))
        return {"status": "signed_out"}
    @app.get("/api/catalog")
    def catalog(u=Depends(user)):
        return registry.catalog()
    @app.get("/api/projects")
    def projects(u=Depends(user)):
        with engine.connect() as conn:
            return [dict(r) for r in conn.execute(select(db.projects).join(db.memberships).where(
                db.memberships.c.user_id == u["id"])).mappings()]
    @app.post("/api/projects")
    def new_project(body: ProjectRequest, u=Depends(user)):
        if u["role"] != "administrator":
            raise HTTPException(403, "Administrator required")
        with engine.begin() as conn:
            project_id = db.uid("project")
            conn.execute(db.projects.insert().values(id=project_id, name=body.name, created_at=db.now()))
            conn.execute(db.memberships.insert().values(user_id=u["id"], project_id=project_id))
            db.audit_event(conn, u["id"], "project.created", project_id)
        return {"id": project_id}
    @app.post("/api/users")
    def new_user(body: UserRequest, u=Depends(user)):
        if u["role"] != "administrator":
            raise HTTPException(403, "Administrator required")
        with engine.begin() as conn:
            for pid in body.project_ids:
                access(conn, u, pid, "administrator")
            account = auth.create_user(conn, body.username, body.role, body.project_ids)
            db.audit_event(conn, u["id"], "account.created", payload={"user_id": account["id"], "role": account["role"]})
        return account
    @app.get("/api/projects/{pid}/revisions")
    def revisions(pid: str, u=Depends(user)):
        with engine.connect() as conn:
            access(conn, u, pid)
            return service.rows(conn, db.revisions, db.revisions.c.project_id == pid, limit=1000)
    @app.get('/api/projects/{pid}/overview')
    def grid_overview(pid: str, mode: str = 'demo', source_id: str | None = None, u=Depends(user)):
        if mode not in ('demo', 'live'):
            raise ValueError('Overview source mode must be demo or live')
        with engine.connect() as conn:
            access(conn,u,pid)
            return overview.project_overview(conn,pid,mode,source_id)
    @app.put('/api/projects/{pid}/locations')
    def save_locations(pid: str, body: LocationsRequest, u=Depends(user)):
        with engine.begin() as conn:
            access(conn,u,pid,'engineer')
            active=overview.active_revision(conn,pid)
            assets={c['id'] for c in active['payload']['components']} if active else set()
            if len({l.asset_id for l in body.locations})!=len(body.locations):
                raise ValueError('Duplicate asset location')
            for location in body.locations:
                if location.asset_id not in assets:
                    raise ValueError('Location must reference an asset in the published project model')
                conn.execute(db.entities['asset_locations'].insert().values(id=db.uid('location'),
                    project_id=pid,version='1',created_at=db.now(),payload=location.model_dump()))
            db.audit_event(conn,u['id'],'locations.updated',pid,{'asset_ids':[v.asset_id for v in body.locations]})
        return {'saved':len(body.locations)}
    @app.post('/api/projects/{pid}/grid-observations')
    def grid_observation(pid: str, body: overview.GridObservation, u=Depends(user)):
        with engine.begin() as conn:
            access(conn,u,pid,'engineer')
            return overview.store_observation(conn,pid,body,u['id'])
    @app.post('/api/projects/{pid}/simulations/apply')
    def apply_simulation(pid: str, body: ApplySimulation, u=Depends(user)):
        with engine.begin() as conn:
            access(conn,u,pid,'administrator')
            return overview.apply_simulation(conn,pid,body.run_id,u['id'],body.name)
    @app.post("/api/projects/{pid}/revisions")
    def new_revision(pid: str, body: RevisionRequest, u=Depends(user)):
        with engine.begin() as conn:
            access(conn, u, pid, "engineer")
            if body.parent_id and not conn.scalar(select(db.revisions.c.id).where(db.revisions.c.id == body.parent_id, db.revisions.c.project_id == pid)):
                raise ValueError("Parent revision belongs to another project or is missing")
            revision_id = service.create_revision(conn, pid, body.network.model_dump(mode="json"),
                body.name, u["id"], body.valid_from, body.valid_to, body.parent_id)
        return {"id": revision_id}
    @app.get("/api/projects/{pid}/revisions/{rid}")
    def revision(pid: str, rid: str, u=Depends(user)):
        with engine.connect() as conn:
            access(conn, u, pid)
            record = conn.execute(select(db.revisions).where(db.revisions.c.id == rid, db.revisions.c.project_id == pid)).mappings().first()
            if not record:
                raise HTTPException(404, "Revision unavailable")
            return dict(record)
    @app.post("/api/projects/{pid}/revisions/{rid}/publish")
    def publish(pid: str, rid: str, u=Depends(user)):
        with engine.begin() as conn:
            access(conn, u, pid, "administrator")
            service.publish_revision(conn, pid, rid, u["id"])
        return {"status": "published"}
    @app.post("/api/projects/{pid}/imports/preview")
    def preview(pid: str, body: ImportRequest, u=Depends(user)):
        with engine.connect() as conn:
            access(conn, u, pid, "engineer")
        result = parse_csv(body.raw_text, body.mapping)
        return {"manifest": result["manifest"], "frames": result["frames"][:10], "rejects": result["rejects"][:100],
                "rejects_truncated": len(result["rejects"]) > 100}
    @app.post("/api/projects/{pid}/imports")
    def import_data(pid: str, body: ImportRequest, u=Depends(user)):
        with engine.connect() as conn:
            access(conn, u, pid, "engineer")
        result = parse_csv(body.raw_text, body.mapping)
        with engine.begin() as conn:
            import_id = db.uid("import")
            conn.execute(db.imports.insert().values(id=import_id, project_id=pid, filename=body.filename,
                checksum=result["manifest"]["dataset_id"][7:], raw_text=body.raw_text, mapping=body.mapping,
                manifest={**result["manifest"], "frames": result["frames"]}, rejects=result["rejects"], created_at=db.now()))
            conn.execute(db.entities["signal_mappings"].insert().values(id=import_id, project_id=pid,
                version=result["manifest"]["mapping_sha256"], created_at=db.now(), payload=body.mapping))
            conn.execute(db.entities["data_sources"].insert().values(id=import_id, project_id=pid,
                version="1", created_at=db.now(), payload={"source_id": body.mapping["source_id"], "origin": body.mapping["data_origin"]}))
            db.audit_event(conn, u["id"], "import.saved", pid, {"import_id": import_id, "checksum": result["manifest"]["dataset_id"]})
        return {"id": import_id, "manifest": result["manifest"], "rejects": result["rejects"][:100]}
    @app.get("/api/projects/{pid}/imports")
    def imports(pid: str, u=Depends(user)):
        with engine.connect() as conn:
            access(conn, u, pid)
            q = select(db.imports.c.id, db.imports.c.filename, db.imports.c.checksum, db.imports.c.created_at).where(db.imports.c.project_id == pid).limit(1000)
            return [dict(r) for r in conn.execute(q).mappings()]
    @app.get("/api/projects/{pid}/imports/{iid}/rejects")
    def rejects(pid: str, iid: str, offset: int = Query(0, ge=0), u=Depends(user)):
        with engine.connect() as conn:
            access(conn, u, pid)
            record = conn.execute(select(db.imports.c.rejects).where(db.imports.c.id == iid, db.imports.c.project_id == pid)).scalar()
            if record is None:
                raise HTTPException(404, "Import unavailable")
            return {"total": len(record), "items": record[offset:offset+100]}
    @app.post("/api/projects/{pid}/studies")
    def study(pid: str, body: StudyRequest, u=Depends(user)):
        if body.kind not in ("replay", "network", "scenario", "estimation", "thermal", "three_phase", "fault", "sag", "calibration"):
            raise ValueError("Study not integrated")
        if body.mode not in ("replay", "live", "offline"):
            raise ValueError("Invalid clock mode")
        with engine.begin() as conn:
            access(conn, u, pid, "engineer")
            manifest = service.run_manifest(conn, pid, body.revision_id, body.mode)
            payload = {"inputs": body.inputs}
            if body.kind in ("replay", "calibration"):
                imported = conn.execute(select(db.imports).where(db.imports.c.id == body.import_id, db.imports.c.project_id == pid)).mappings().first()
                if not imported:
                    raise ValueError("Import unavailable")
                payload.update(frames=imported["manifest"]["frames"], import_id=body.import_id,
                    asset_id=body.asset_id, acceptance_criteria={"max_weighted_rmse": body.max_weighted_rmse})
                if not payload["frames"]:
                    raise ValueError("No accepted rows to process")
                manifest["dataset_manifest"] = {k: v for k, v in imported["manifest"].items() if k != "frames"}
            if body.kind in ("network", "scenario"):
                registry.validate(Network.model_validate(manifest["network"]), study=True)
            if body.kind == "scenario":
                if body.scenario is None:
                    raise ValueError("Scenario network required")
                registry.validate(body.scenario, study=True)
                payload["network"] = body.scenario.model_dump(mode="json")
            return service.enqueue(conn, pid, body.kind, payload, manifest, u["id"], body.mode, body.speed)
    @app.post("/api/projects/{pid}/signal-snapshots")
    def signal_snapshot(pid: str,body: SignalSnapshotRequest,u=Depends(user)):
        from tl_twin.alignment import assemble_frame
        if body.mode not in ("replay","live","offline"):
            raise ValueError("Invalid clock mode")
        if sum(len(records) for records in body.samples.values())>10000:
            raise ValueError("Bounded signal snapshot accepts at most 10,000 samples")
        with engine.begin() as conn:
            access(conn,u,pid,"engineer")
            manifest=service.run_manifest(conn,pid,body.revision_id,body.mode)
            frame=assemble_frame(body.envelope,body.samples,body.max_age_s,body.max_skew_s)
            return service.enqueue(conn,pid,"replay",{"frames":[frame.model_dump(mode="json")],
                "raw_signal_samples":body.samples,"alignment":{"max_age_s":body.max_age_s,"max_skew_s":body.max_skew_s}},manifest,u["id"],body.mode)
    @app.get("/api/projects/{pid}/jobs")
    def jobs(pid: str, u=Depends(user)):
        with engine.connect() as conn:
            access(conn, u, pid)
            cols = [c for c in db.jobs.c if c.name != "payload"]
            return [dict(r) for r in conn.execute(select(*cols).where(db.jobs.c.project_id == pid).order_by(db.jobs.c.created_at.desc()).limit(1000)).mappings()]
    @app.post("/api/projects/{pid}/jobs/{jid}/control")
    def control(pid: str, jid: str, body: ControlRequest, u=Depends(user)):
        with engine.begin() as conn:
            access(conn, u, pid, "engineer")
            job = conn.execute(select(db.jobs).where(db.jobs.c.id == jid, db.jobs.c.project_id == pid).with_for_update()).mappings().first()
            if not job:
                raise HTTPException(404, "Job unavailable")
            transitions = {"pause": "paused", "resume": "queued", "cancel": "cancelled", "retry": "queued", "speed": job["status"]}
            if body.action not in transitions or job["status"] in ("completed", "cancelled"):
                raise ValueError("Invalid transition for job status")
            if body.action == "retry" and job["status"] != "failed":
                raise ValueError("Only a failed job may be retried")
            if body.action == "resume" and job["status"] != "paused":
                raise ValueError("Only a paused job may resume")
            values = {"status": transitions[body.action], "updated_at": db.now()}
            if body.action != "speed":
                values.update(owner=None, lease_until=None, next_due=0)
            if body.speed:
                values["speed"] = body.speed
            conn.execute(db.jobs.update().where(db.jobs.c.id == jid).values(**values))
            db.audit_event(conn, u["id"], "job."+body.action, pid, {"job_id": jid})
        return {"status": values["status"]}
    @app.get("/api/projects/{pid}/runs")
    def runs(pid: str, u=Depends(user)):
        with engine.connect() as conn:
            access(conn, u, pid)
            return service.rows(conn, db.runs, db.runs.c.project_id == pid, limit=1000)
    @app.get("/api/projects/{pid}/runs/{rid}/history")
    def history(pid: str, rid: str, offset: int = Query(0, ge=0), limit: int = Query(288, ge=1, le=1000), asset_id: str | None=None, u=Depends(user)):
        with engine.connect() as conn:
            access(conn, u, pid)
            if not conn.scalar(select(db.runs.c.id).where(db.runs.c.id == rid, db.runs.c.project_id == pid)):
                raise HTTPException(404, "Run unavailable")
            q = select(db.states).where(db.states.c.run_id == rid)
            if asset_id:
                q = q.where(db.states.c.asset_id == asset_id)
            total = conn.scalar(select(func.count()).select_from(q.subquery()))
            records = conn.execute(q.order_by(db.states.c.event_time, db.states.c.message_id).offset(offset).limit(limit)).mappings()
            items=[]
            for record in records:
                state=dict(record["payload"])
                if state.get("mode")=="live":
                    age=(db.now()-db.utc_time(state["event_time"])).total_seconds()
                    state.update(current_age_s=age,current_freshness="STALE" if age>120 else "FUTURE" if age < -5 else "FRESH")
                items.append(state)
            return {"total": total, "items": items}
    @app.get("/api/projects/{pid}/runs/{rid}/report")
    def report(pid: str, rid: str, u=Depends(user)):
        with engine.connect() as conn:
            access(conn, u, pid)
            return service.report_data(conn, pid, rid)
    @app.get("/api/projects/{pid}/runs/{rid}/export")
    def export(pid: str, rid: str, format: str="html", u=Depends(user)):
        with engine.connect() as conn:
            access(conn, u, pid)
            report = service.report_data(conn, pid, rid)
        if format == "html":
            safe = html.escape(json.dumps(report, indent=2, default=str))
            with engine.connect() as conn:
                points = conn.execute(select(db.states.c.payload).where(db.states.c.run_id == rid).order_by(db.states.c.event_time).limit(1000)).scalars().all()
            from .reports import report_figures
            figures = report_figures(points)
            return HTMLResponse('<!doctype html><meta charset="utf-8"><title>Validation report</title><style>body{font:16px system-ui;max-width:1100px;margin:40px auto;color:#243746}pre{white-space:pre-wrap;background:#f4f7f9;padding:20px}svg{width:100%;border:1px solid #dae4ea}h2{margin-top:35px}</style><h1>Power-system twin validation report</h1><p>Synthetic/reference study. UTC timestamps; inputs, assumptions, versions, failures and limitations follow.</p><p>Usable receiving-voltage observations: '+str(report["usable"])+', excluded: '+str(report["excluded"])+'.</p>'+figures+'<h2>Inputs, metrics, versions, failures and limitations</h2><pre>'+safe+'</pre>', headers={"Content-Disposition": f'attachment; filename="{rid}.html"'})
        if format != "csv":
            raise ValueError("Export format must be csv or html")
        def stream():
            channels=["vs_ll_kv","vr_ll_kv","p_recv_mw","q_recv_mvar","p_send_mw","q_send_mvar","is_a","ir_a","frequency_hz","conductor_temp_c"]
            fields = ["event_time", "asset_id", "origin", "status", "parameter_version", "topology_version", "vr_measured_kv", "vr_predicted_kv", "vr_residual_kv", "loss_mw", "loading_percent", "manifest_sha256"]
            fields += [prefix+key for key in channels for prefix in ("measured_","predicted_","residual_","quality_","sigma_")]
            fields += ["message_id","snapshot_id","received_at","processed_at","clock_time","source_id","dataset_id","source_metadata_json"]
            buffer = io.StringIO()
            writer = csv.DictWriter(buffer, fieldnames=fields)
            writer.writeheader()
            yield buffer.getvalue()
            offset = 0
            while True:
                with engine.connect() as conn:
                    records = conn.execute(select(db.states.c.payload).where(db.states.c.run_id == rid).order_by(db.states.c.event_time, db.states.c.id).offset(offset).limit(500)).scalars().all()
                if not records:
                    break
                for s in records:
                    buffer.seek(0); buffer.truncate(0)
                    p = s.get("prediction") or {}
                    values=dict(event_time=s["event_time"], asset_id=s["asset_id"], origin=s["data_origin"], status=s["model_status"],
                        parameter_version=s.get("parameter_version"), topology_version=s.get("topology_version"),
                        vr_measured_kv=s["measurement"].get("vr_ll_kv"), vr_predicted_kv=p.get("vr_ll_kv"),
                        vr_residual_kv=s["residual_physics"].get("vr_ll_kv"), loss_mw=p.get("loss_mw"), loading_percent=p.get("loading_percent"), manifest_sha256=s["manifest_sha256"])
                    m=s["measurement"]
                    for key in channels:
                        values.update({"measured_"+key:m.get(key),"predicted_"+key:p.get(key),"residual_"+key:s["residual_physics"].get(key),
                            "quality_"+key:m.get("signal_quality",{}).get(key,"GOOD" if m.get(key) is not None else "MISSING"),"sigma_"+key:m.get("uncertainty",{}).get(key)})
                    for key in ("message_id","snapshot_id","received_at","processed_at","clock_time"):
                        values[key]=s.get(key)
                    values.update(source_id=m["source_id"],dataset_id=m["dataset_id"],source_metadata_json=json.dumps(m.get("source_metadata",{}),sort_keys=True))
                    writer.writerow(values)
                    yield buffer.getvalue()
                offset += len(records)
        return StreamingResponse(stream(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{rid}.csv"'})
    @app.get("/api/projects/{pid}/alerts")
    def alerts(pid: str, u=Depends(user)):
        with engine.connect() as conn:
            access(conn, u, pid)
            return service.rows(conn, db.alarms, db.alarms.c.project_id == pid, limit=1000)
    @app.post("/api/projects/{pid}/alerts/{aid}/acknowledge")
    def acknowledge(pid: str, aid: str, u=Depends(user)):
        with engine.begin() as conn:
            access(conn, u, pid, "engineer")
            changed = conn.execute(db.alarms.update().where(db.alarms.c.id == aid, db.alarms.c.project_id == pid).values(acknowledged_by=u["id"]))
            if not changed.rowcount:
                raise HTTPException(404, "Alarm unavailable")
            db.audit_event(conn, u["id"], "alarm.acknowledged", pid, {"alarm_id": aid})
        return {"status": "acknowledged"}
    @app.get("/api/projects/{pid}/audit")
    def audit(pid: str, u=Depends(user)):
        with engine.connect() as conn:
            access(conn, u, pid)
            return service.rows(conn, db.audit, db.audit.c.project_id == pid, limit=1000)
    @app.get("/api/projects/{pid}/alarm-policy")
    def alarm_policy(pid: str,u=Depends(user)):
        with engine.connect() as conn:
            access(conn,u,pid)
            table=db.entities["alarm_policy_versions"]
            policy=conn.execute(select(table).where(table.c.project_id==pid).order_by(table.c.created_at.desc()).limit(1)).mappings().first()
            return {"id":policy["id"],"policy":policy["payload"]} if policy else {"id":"synthetic.default.v1","policy":{"high_kv":.08,"clear_kv":.04,"consecutive":3}}
    @app.post("/api/projects/{pid}/alarm-policy")
    def publish_policy(pid: str,body: AlarmPolicy,u=Depends(user)):
        if body.clear_kv>=body.high_kv:
            raise ValueError("Clear threshold must be below activation threshold")
        with engine.begin() as conn:
            access(conn,u,pid,"administrator")
            policy_id=db.uid("policy")
            conn.execute(db.entities["alarm_policy_versions"].insert().values(id=policy_id,project_id=pid,
                version="1",created_at=db.now(),payload=body.model_dump()))
            db.audit_event(conn,u["id"],"alarm.policy.published",pid,{"policy_id":policy_id,"policy":body.model_dump()})
        return {"id":policy_id}
    @app.get("/api/projects/{pid}/diagnostics")
    def diagnostics(pid: str, u=Depends(user)):
        began=time.perf_counter()
        with engine.connect() as conn:
            access(conn, u, pid)
            counts = {name: conn.scalar(select(func.count()).select_from(table).where(table.c.project_id == pid))
                for name, table in [("measurements", db.measurements), ("dead_letters", db.dead_letters), ("jobs", db.jobs)]}
            counts["unpublished_outbox"] = conn.scalar(select(func.count()).select_from(db.outbox).where(db.outbox.c.project_id == pid, db.outbox.c.published_at.is_(None)))
            counts["backlog_jobs"] = conn.scalar(select(func.count()).select_from(db.jobs).where(db.jobs.c.project_id == pid, db.jobs.c.status.in_(["queued", "running", "paused"])))
            counts["duplicate_deliveries"]=conn.scalar(select(func.count()).select_from(db.audit).where(db.audit.c.project_id==pid,db.audit.c.action=="measurement.duplicate"))
            project_runs=select(db.runs.c.id).where(db.runs.c.project_id==pid)
            counts["failed_snapshots"]=conn.scalar(select(func.count()).select_from(db.states).where(db.states.c.run_id.in_(project_runs),db.states.c.status!="SOLVED"))
            oldest=conn.scalar(select(func.min(db.jobs.c.created_at)).where(db.jobs.c.project_id==pid,db.jobs.c.status.in_(["queued","running","paused"])))
            latest=conn.scalar(select(func.max(db.measurements.c.event_time)).where(db.measurements.c.project_id==pid))
            latencies=conn.execute(select(db.states.c.payload["solve_latency_ms"].as_float()).where(db.states.c.run_id.in_(project_runs)).order_by(db.states.c.processed_at.desc()).limit(10000)).scalars().all()
            latencies=[v for v in latencies if v is not None]
            import numpy as np
            import shutil
            disk=shutil.disk_usage(Path.cwd())
            return {"database": engine.dialect.name, "utc": db.now(), "counts": counts,
                    "backlog_oldest_age_s":(db.now()-db.utc_time(db.iso(oldest))).total_seconds() if oldest else None,
                    "latest_observation_wall_age_s":(db.now()-db.utc_time(db.iso(latest))).total_seconds() if latest else None,
                    "solve_latency_ms_last_10000":{"p50":float(np.percentile(latencies,50)),"p95":float(np.percentile(latencies,95)),"p99":float(np.percentile(latencies,99))} if latencies else None,
                    "diagnostics_database_query_ms":(time.perf_counter()-began)*1000,
                    "disk":{"total_bytes":disk.total,"free_bytes":disk.free},
                    "worker_concurrency_per_process": 1, "job_backlog_limit": 100, "import_row_limit": 10000,
                    "mqtt": "disabled" if not os.getenv("MQTT_HOST") else "configured; consult bridge logs",
                    "production_scale_validated": False}

    dist = Path(frontend_dir or Path(os.getenv("GRID_TWIN_ROOT", str(Path.cwd()))).resolve()/"frontend"/"dist")
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app

app = create_app()
