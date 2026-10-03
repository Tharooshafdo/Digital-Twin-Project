"""Transactional platform workflows shared by API, CLI and worker."""
import importlib.metadata
import math
import time
from datetime import timedelta
from sqlalchemy import select, update, func, and_, or_
from . import db
from .domain import Network
from .plugins import registry
from .solver import line_config

def rows(conn, table, *where, limit=100):
    return [dict(r) for r in conn.execute(select(table).where(*where).limit(limit)).mappings()]

def freeze(network, revision_id):
    payload = Network.model_validate(network).model_dump(mode="json")
    for c in payload["components"]:
        c["parameter_version"] = revision_id + "." + c["id"]
    return payload

def create_revision(conn, project_id, network, name, actor, valid_from, valid_to=None, parent_id=None):
    registry.validate(Network.model_validate(network))
    start, end = db.utc_time(valid_from), db.utc_time(valid_to) if valid_to else None
    if end and end <= start:
        raise ValueError("Invalid half-open validity interval")
    revision_id = db.uid("rev")
    payload = freeze(network, revision_id)
    conn.execute(db.revisions.insert().values(id=revision_id, project_id=project_id,
        name=name, status="draft", payload=payload, payload_hash=db.digest(payload),
        created_at=db.now(), valid_from=start, valid_to=end, parent_id=parent_id))
    db.audit_event(conn, actor, "draft.created", project_id, {"revision_id": revision_id})
    return revision_id

def publish_revision(conn, project_id, revision_id, actor):
    # Lock project first so overlapping publication cannot race on PostgreSQL.
    project = conn.execute(select(db.projects).where(db.projects.c.id == project_id).with_for_update()).first()
    if not project:
        raise ValueError("Project unavailable")
    r = conn.execute(select(db.revisions).where(db.revisions.c.id == revision_id,
        db.revisions.c.project_id == project_id)).mappings().first()
    if not r or r["status"] != "draft":
        raise ValueError("Only a draft may be published")
    registry.validate(Network.model_validate(r["payload"]))
    table = db.entities["topology_timelines"]
    previous = conn.execute(select(table).where(table.c.project_id == project_id).order_by(table.c.created_at.desc(),table.c.id.desc()).limit(1)).mappings().first()
    if previous:
        intervals = list(previous["payload"]["intervals"])
    else:
        # Upgrade existing data without rewriting published revisions.
        intervals = [{"revision_id":v["id"],"valid_from":db.iso(v["valid_from"]),"valid_to":db.iso(v["valid_to"]) if v["valid_to"] else None}
            for v in rows(conn,db.revisions,db.revisions.c.project_id==project_id,db.revisions.c.status=="published",limit=10000)]
    start,end=db.iso(r["valid_from"]),db.iso(r["valid_to"]) if r["valid_to"] else None
    timeline=[]
    for other in intervals:
        os,oe=other["valid_from"],other["valid_to"]
        if start < (oe or "9999") and os < (end or "9999"):
            # A later effective publication closes an open predecessor in a NEW
            # timeline version. The original revision/timeline and old runs stay immutable.
            if oe is None and start > os and end is None:
                timeline.append({**other,"valid_to":start})
            else:
                raise ValueError("Published validity intervals overlap; a superseding open version must start later than its predecessor")
        else:timeline.append(other)
    timeline.append({"revision_id":revision_id,"valid_from":start,"valid_to":end})
    timeline.sort(key=lambda interval:interval["valid_from"])
    timeline_id=db.uid("timeline")
    conn.execute(table.insert().values(id=timeline_id,project_id=project_id,version="1",created_at=db.now(),payload={"intervals":timeline,"previous_timeline_id":previous["id"] if previous else None}))
    conn.execute(db.revisions.update().where(db.revisions.c.id == revision_id).values(status="published"))
    for c in r["payload"]["components"]:
        for table_name, entity_id, payload in [("assets", revision_id+"."+c["id"], c),
            ("parameter_versions", c["parameter_version"], {"asset_id": c["id"], "parameters": c["parameters"],
             "valid_from": db.iso(r["valid_from"]), "valid_to": db.iso(r["valid_to"]) if r["valid_to"] else None})]:
            conn.execute(db.entities[table_name].insert().values(id=entity_id, project_id=project_id,
                version="1", created_at=db.now(), payload=payload))
        for terminal in c["terminals"]:
            conn.execute(db.entities["terminals"].insert().values(id=revision_id+"."+c["id"]+"."+terminal["name"],
                project_id=project_id, version="1", created_at=db.now(), payload=terminal))
    db.audit_event(conn, actor, "revision.published", project_id, {"revision_id": revision_id})

def run_manifest(conn, project_id, revision_id, mode):
    revision = conn.execute(select(db.revisions).where(db.revisions.c.id == revision_id,
        db.revisions.c.project_id == project_id)).mappings().first()
    if not revision:
        raise ValueError("Revision unavailable")
    timeline_table=db.entities["topology_timelines"]
    timeline=conn.execute(select(timeline_table).where(timeline_table.c.project_id==project_id).order_by(timeline_table.c.created_at.desc(),timeline_table.c.id.desc()).limit(1)).mappings().first()
    timeline_networks={}
    if timeline:
        for interval in timeline["payload"]["intervals"]:
            v=conn.execute(select(db.revisions.c.payload).where(db.revisions.c.id==interval["revision_id"],db.revisions.c.project_id==project_id)).scalar_one()
            timeline_networks[interval["revision_id"]]=v
    policies=db.entities["alarm_policy_versions"]
    policy=conn.execute(select(policies).where(policies.c.project_id==project_id).order_by(policies.c.created_at.desc()).limit(1)).mappings().first()
    return {"platform_version": "0.1.0", "schema_version": "platform.run.v1", "adapter_version": "2.0",
        "physics_version": "balanced.pi.pandapower3.5.5.v1", "clock_mode": mode,
        "revision_id": revision_id, "revision_status": revision["status"], "network": revision["payload"],
        "valid_from": db.iso(revision["valid_from"]), "valid_to": db.iso(revision["valid_to"]) if revision["valid_to"] else None,
        "network_sha256": revision["payload_hash"], "plugins": {p.type_id: p.version for p in registry.plugins.values()},
        "timeline_id":timeline["id"] if timeline else None,
        "timeline":timeline["payload"] if timeline else None,
        "timeline_networks":timeline_networks,
        "revision_policy":"published_event_time" if revision["status"]=="published" and timeline else "explicit_revision",
        "dependencies": {p: importlib.metadata.version(p) for p in ("pandapower", "numpy", "pydantic", "SQLAlchemy")},
        "input_roles": ["vs_ll_kv", "p_recv_mw", "q_recv_mvar"],
        "validation_roles": ["vr_ll_kv", "is_a", "ir_a", "p_send_mw", "q_send_mvar"],
        "assumptions": ["Balanced nominal pi", "Total 3-phase receiving P/Q positive OUT", "Circuit ratings are illustrative"],
        "alarm_policy_version":policy["id"] if policy else "synthetic.default.v1",
        "alarm_policy": policy["payload"] if policy else {"high_kv": 0.08, "clear_kv": 0.04, "consecutive": 3}}

def enqueue(conn, project_id, kind, payload, manifest, actor, mode="replay", speed=600):
    if not 0 < speed <= 100000:
        raise ValueError("Replay speed must be in (0,100000]")
    pending = conn.scalar(select(func.count()).select_from(db.jobs).where(
        db.jobs.c.status.in_(["queued", "running", "paused"])))
    if pending >= 100:
        raise OverflowError("Job backlog limit reached (100); wait or cancel")
    run_id, job_id = db.uid("run"), db.uid("job")
    manifest = {**manifest, "kind": kind, "request_sha256": db.digest(payload)}
    conn.execute(db.runs.insert().values(id=run_id, project_id=project_id,
        kind=kind, mode=mode, manifest=manifest, created_at=db.now()))
    total = len(payload.get("frames", [])) if kind == "replay" else 1
    conn.execute(db.jobs.insert().values(id=job_id, project_id=project_id, run_id=run_id,
        kind=kind, status="queued", payload=payload, checkpoint=0, total=total, attempts=0,
        speed=speed, next_due=0, created_at=db.now(), updated_at=db.now()))
    db.audit_event(conn, actor, "study.created", project_id, {"run_id": run_id, "job_id": job_id})
    return {"run_id": run_id, "job_id": job_id}

def update_alarm(conn, project_id, state, policy):
    key = state["run_id"] + "." + state["asset_id"]
    old = conn.execute(select(db.alarms).where(db.alarms.c.id == key).with_for_update()).mappings().first()
    event = db.utc_time(state["event_time"])
    if old and old["last_event_time"] and db.iso(event) <= db.iso(old["last_event_time"]):
        return # late/duplicate delivery does not advance hysteresis counters
    count, active = (old["count"], old["active"]) if old else (0, 0)
    residual = state.get("residual_physics", {}).get("vr_ll_kv")
    data_issue = state["model_status"] != "SOLVED" or state.get("freshness") != "FRESH" or residual is None or state.get("assessment")=="DATA_REVIEW"
    if not data_issue:
        if abs(residual) >= policy["high_kv"]:
            count += 1
            if count >= policy["consecutive"]:
                active = 1
        elif abs(residual) <= policy["clear_kv"]:
            active, count = 0, 0
        else:
            count = 0
    payload = {"condition": "RAW_VOLTAGE_DISCREPANCY", "data_quality_condition": data_issue,
               "residual_kv": residual, "policy": policy, "diagnosis": "No physical diagnosis inferred"}
    values = dict(project_id=project_id, run_id=state["run_id"], asset_id=state["asset_id"],
        active=active, count=count, last_event_time=event, payload=payload)
    if old:
        if active and not old["active"]:
            values["acknowledged_by"] = None
        conn.execute(db.alarms.update().where(db.alarms.c.id == key).values(**values))
    else:
        conn.execute(db.alarms.insert().values(id=key, **values))

def commit_state(conn, project_id, measurement, state, manifest):
    m = measurement.model_dump(mode="json")
    old = conn.execute(select(db.measurements).where(db.measurements.c.project_id == project_id,
        db.measurements.c.message_id == m["message_id"])).mappings().first()
    if old and old["payload_hash"] != db.digest(m):
        raise ValueError("Message identity reused with changed content")
    natural_key=db.digest([m[k] for k in ("dataset_id","source_id","asset_id","event_time","sequence_no")])
    alternate=conn.execute(select(db.measurements.c.message_id).where(db.measurements.c.project_id==project_id,
        db.measurements.c.natural_key==natural_key)).scalar()
    if alternate and alternate != m["message_id"]:
        raise ValueError("Source identity reused under a different message ID")
    if not old:
        conn.execute(db.measurements.insert().values(id=project_id+"."+m["message_id"],
            project_id=project_id, message_id=m["message_id"], asset_id=m["asset_id"],
            event_time=db.utc_time(m["event_time"]), received_at=db.now(), payload_hash=db.digest(m), payload=m,natural_key=natural_key))
    key = state["run_id"] + "." + m["message_id"]
    if conn.scalar(select(db.states.c.id).where(db.states.c.id == key)):
        db.audit_event(conn,"worker","measurement.duplicate",project_id,{"message_id":m["message_id"],"run_id":state["run_id"]})
        return False
    state["snapshot_id"] = key
    state["measurement"] = m
    state["manifest_sha256"] = db.digest(manifest)
    conn.execute(db.states.insert().values(id=key, run_id=state["run_id"], message_id=m["message_id"],
        asset_id=m["asset_id"], event_time=db.utc_time(m["event_time"]), processed_at=db.now(),
        status=state["model_status"], voltage_residual=state.get("residual_physics", {}).get("vr_ll_kv"), payload=state))
    conn.execute(db.entities["snapshots"].insert().values(id=key, project_id=project_id, version="1",
        created_at=db.now(), payload={"run_id": state["run_id"], "event_time": m["event_time"],
            "clock_time": state["clock_time"], "manifest_sha256": db.digest(manifest)}))
    conn.execute(db.outbox.insert().values(id=key, project_id=project_id,
        topic=f"dt/v1/project/{project_id}/run/{state['run_id']}/line/{m['asset_id']}/state",
        payload=state, attempts=0))
    update_alarm(conn, project_id, state, manifest["alarm_policy"])
    return True

def report_data(conn, project_id, run_id):
    run = conn.execute(select(db.runs).where(db.runs.c.id == run_id,
        db.runs.c.project_id == project_id)).mappings().first()
    if not run:
        raise ValueError("Run unavailable")
    total = conn.scalar(select(func.count()).select_from(db.states).where(db.states.c.run_id == run_id))
    usable = conn.scalar(select(func.count()).select_from(db.states).where(db.states.c.run_id == run_id,
        db.states.c.voltage_residual.is_not(None)))
    stats = conn.execute(select(func.avg(db.states.c.voltage_residual),
        func.avg(func.abs(db.states.c.voltage_residual)),
        func.avg(db.states.c.voltage_residual * db.states.c.voltage_residual)).where(
        db.states.c.run_id == run_id, db.states.c.voltage_residual.is_not(None))).first()
    # Exact p95 is bounded in the initial release; never pretend a sample is the full history.
    values = conn.execute(select(func.abs(db.states.c.voltage_residual)).where(db.states.c.run_id == run_id,
        db.states.c.voltage_residual.is_not(None)).order_by(func.abs(db.states.c.voltage_residual)).limit(10001)).scalars().all()
    import numpy as np
    channels = {}
    for key in ("vr_ll_kv", "is_a", "ir_a", "p_send_mw", "q_send_mvar"):
        field = db.states.c.payload["residual_physics"][key].as_float()
        a = conn.execute(select(func.count(field),func.avg(field),func.avg(func.abs(field)),func.avg(field*field)).where(db.states.c.run_id == run_id)).one()
        channels[key] = {"usable":a[0],"excluded":total-a[0],"bias":a[1],"mae":a[2],"rmse":math.sqrt(a[3]) if a[3] is not None else None}
    return {"run_id": run_id, "manifest": run["manifest"], "states": total, "usable": usable,
        "archival_history":[v["payload"] for v in rows(conn,db.audit,db.audit.c.project_id==project_id,db.audit.c.action=="run.archived",limit=1000) if v["payload"].get("run_id")==run_id],
        "excluded": total-usable, "voltage_kv": {"bias": stats[0], "mae": stats[1],
            "rmse": math.sqrt(stats[2]) if stats[2] is not None else None,
            "p95_absolute": float(np.quantile(values, 0.95)) if 0 < len(values) <= 10000 else None},
        "p95_limit": "Exact p95 available up to 10,000 usable samples",
        "independent_validation_channels": channels,
        "job_outcomes": [{k:v for k,v in row.items() if k != "payload"} for row in rows(conn,db.jobs,db.jobs.c.run_id == run_id)],
        "input_examples": [row["payload"] for row in rows(conn,db.states,db.states.c.run_id == run_id,limit=3)],
        "failures": rows(conn, db.states, db.states.c.run_id == run_id, db.states.c.status != "SOLVED", limit=100),
        "research_results": rows(conn, db.entities["validation_reports"],
            db.entities["validation_reports"].c.project_id == project_id,
            db.entities["validation_reports"].c.id == run_id, limit=1),
        "limitations": ["Synthetic/reference evidence does not establish field accuracy", "Balanced steady-state only",
            "No operational ratings, cable thermal physics, protection or equipment commands"]}
