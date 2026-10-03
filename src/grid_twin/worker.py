"""Separate bounded worker. One CPU solve per process; transactional leases."""
import json
import os
import time
from pathlib import Path
from sqlalchemy import select, or_, and_, func
from . import db, service
from .solver import solve_network, line_config
from tl_twin.contracts import Measurement
from tl_twin.twin import evaluate

LEASE_S = float(os.getenv("GRID_TWIN_JOB_LEASE_S", "300"))
if not 5 <= LEASE_S <= 3600:
    raise ValueError("Job lease must be between 5 and 3600 seconds")

def claim(engine, owner):
    clock = time.time()
    with engine.begin() as conn:
        q = select(db.jobs).where(db.jobs.c.status.in_(["queued", "running"]), db.jobs.c.next_due <= clock,
            or_(db.jobs.c.owner.is_(None), db.jobs.c.lease_until < clock)).order_by(db.jobs.c.created_at).limit(1)
        if engine.dialect.name == "postgresql":
            q = q.with_for_update(skip_locked=True)
        job = conn.execute(q).mappings().first()
        if not job:
            return None
        changed = conn.execute(db.jobs.update().where(db.jobs.c.id == job["id"],
            db.jobs.c.status.in_(["queued", "running"]),
            or_(db.jobs.c.owner.is_(None), db.jobs.c.lease_until < clock)).values(
                owner=owner, lease_until=clock+LEASE_S, status="running", attempts=db.jobs.c.attempts+1, updated_at=db.now()))
        return dict(job) if changed.rowcount == 1 else None

def calculate_frame(frame, manifest, run_id, mode):
    m = Measurement.model_validate(frame)
    selected_network=manifest["network"]
    revision_id,valid_from,valid_to=manifest["revision_id"],manifest["valid_from"],manifest["valid_to"]
    if manifest.get("revision_policy")=="published_event_time":
        eligible=[v for v in manifest["timeline"]["intervals"] if db.utc_time(v["valid_from"])<=m.event_time and (v["valid_to"] is None or m.event_time<db.utc_time(v["valid_to"]))]
        if len(eligible)==1:
            v=eligible[0];revision_id,valid_from,valid_to=v["revision_id"],v["valid_from"],v["valid_to"]
            selected_network=manifest["timeline_networks"][revision_id]
        else:selected_network={"components":[]}
    configs = [line_config(c, revision_id, valid_from, valid_to)
        for c in selected_network["components"] if c["type_id"] == "ac.line"]
    component = next((c for c in selected_network["components"] if c["id"] == m.asset_id and c["type_id"] == "ac.line"), None)
    independent_cache = {}
    def boundary_solver(cfg, vs, p, q, temp):
        from .electrical import solve_sectioned
        predicted, independent = solve_sectioned(component,cfg,vs,p,q,temp)
        independent_cache.update(independent)
        return predicted
    state = evaluate(m, configs, run_id, mode, solver=boundary_solver if component else None)
    state["mode"] = mode
    if state["model_status"] == "SOLVED" and component:
        from .electrical import solve_sectioned
        cfg = next(c for c in configs if c.asset_id == m.asset_id)
        temp = m.conductor_temp_c if cfg.use_measured_temperature else None
        p, q = (0, 0) if m.connection_state == "RECEIVING_OPEN" else (m.p_recv_mw, m.q_recv_mvar)
        try:
            independent = independent_cache
            state["independent_abcd"] = independent
            for key in ("vr_ll_kv", "is_a", "ir_a", "p_send_mw", "q_send_mvar", "loss_mw"):
                if abs(state["prediction"][key]-independent[key]) > max(1e-7,abs(independent[key])*1e-7):
                    raise ValueError(f"Independent ABCD disagreement for {key}")
        except Exception as exc:
            state.update(model_status="MODEL_FAILED",prediction=None,residual_physics={},assessment="UNASSESSED")
            state["flags"].append(str(exc))
    # Correct reference behaviour: stale/future boundaries must not become fresh scientific predictions.
    if state["freshness"] != "FRESH":
        state["prediction"], state["residual_physics"] = None, {}
        state["model_status"] = "DATA_UNAVAILABLE"
        state["assessment"] = "STALE_DATA"
    if state.get("loss_measurement_sigma_mw") is not None:
        rho = float(m.source_metadata.get("power_error_correlation", 0))
        if not -1 <= rho <= 1:
            raise ValueError("Power error correlation must be in [-1,1]")
        a, b = m.uncertainty["p_send_mw"], m.uncertainty["p_recv_mw"]
        state["loss_measurement_sigma_mw"] = max(0, a*a+b*b-2*rho*a*b)**0.5
        state["power_error_correlation"] = rho
    return m, state

def research(kind, payload, manifest):
    from tl_twin import advanced
    from tl_twin.mechanical import sag_catenary
    if kind == "sag":
        return {**sag_catenary(**payload["inputs"]), "clearance_status": "UNAVAILABLE", "data_origin": "synthetic"}
    functions = {"estimation": advanced.estimate_demo, "thermal": advanced.thermal_demo,
                 "three_phase": advanced.three_phase_demo, "fault": advanced.fault_demo}
    if kind in functions:
        result = functions[kind]()
        result["input_requirements"] = payload.get("input_requirements", [])
        result["reference_inputs"] = "config/network.json and config/lines.json; bundled synthetic fixtures"
        if kind == "thermal":
            result.update(initial_temperature_c=35, elapsed_s=600, heat_model="Educational empirical heat balance; not certified IEEE 738")
        if kind == "estimation":
            result.update(observability="Successful WLS on noiseless fixture; measurement count is not a general observability proof",
                          roles={"v_bus": "estimator observation sigma=0.002 pu", "pq_line_from": "estimator observation sigma=0.1 MW/MVAr"})
        return result
    if kind == "calibration":
        import tempfile
        from tl_twin.calibration import fit_rx
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.jsonl"
            path.write_text("".join(json.dumps(m)+"\n" for m in payload["frames"]), encoding="utf-8")
            component = next(c for c in manifest["network"]["components"] if c["id"] == payload["asset_id"])
            result = fit_rx(path, line_config(component, manifest["revision_id"], manifest["valid_from"], manifest["valid_to"]), Path(directory)/"candidate.json")
            result.update(split="chronological 70% fit / 30% holdout", acceptance_criteria=payload["acceptance_criteria"],
                          accepted=result["weighted_test_rmse"] <= payload["acceptance_criteria"]["max_weighted_rmse"])
            return result
    raise ValueError("Research study not integrated")

def run_one(engine, owner="local-worker"):
    job = claim(engine, owner)
    if not job:
        return False
    began = time.perf_counter()
    with engine.connect() as conn:
        run = conn.execute(select(db.runs).where(db.runs.c.id == job["run_id"])).mappings().one()
    manifest = run["manifest"]
    try:
        if job["kind"] == "replay" and job["checkpoint"] < job["total"]:
            frame = job["payload"]["frames"][job["checkpoint"]]
            m, state = calculate_frame(frame, manifest, job["run_id"], run["mode"])
            state["solve_latency_ms"] = (time.perf_counter()-began)*1000
            with engine.begin() as conn:
                current = conn.execute(select(db.jobs).where(db.jobs.c.id == job["id"]).with_for_update()).mappings().one()
                if current["owner"] != owner or current["status"] != "running":
                    return True
                try:
                    with conn.begin_nested():
                        service.commit_state(conn, job["project_id"], m, state, manifest)
                except ValueError as exc:
                    conn.execute(db.dead_letters.insert().values(id=db.uid("dead"), project_id=job["project_id"],
                        created_at=db.now(), reason=str(exc), raw=db.canonical(frame)))
                index = job["checkpoint"] + 1
                delay = 0
                if index < job["total"]:
                    next_time = db.utc_time(job["payload"]["frames"][index]["event_time"])
                    delay = max(0, (next_time-m.event_time).total_seconds()/current["speed"])
                conn.execute(db.jobs.update().where(db.jobs.c.id == job["id"], db.jobs.c.owner == owner).values(
                    checkpoint=index, status="completed" if index >= job["total"] else "queued",
                    owner=None, lease_until=None, next_due=time.time()+delay, updated_at=db.now()))
        else:
            if job["kind"] == "network":
                result = solve_network(manifest["network"], job["run_id"])
            elif job["kind"] == "scenario":
                baseline = solve_network(manifest["network"], job["run_id"]+".baseline")
                scenario = solve_network(job["payload"]["network"], job["run_id"]+".scenario")
                result = {"baseline": baseline, "scenario": scenario, "loss_delta_mw": scenario["loss_mw"]-baseline["loss_mw"],
                          "scenario_sha256": db.digest(job["payload"]["network"]), "physical_commands": False}
            elif job["kind"] == "replay":
                result = {"empty_dataset": True}
            else:
                result = research(job["kind"], job["payload"], manifest)
            result["solve_latency_ms"] = (time.perf_counter()-began)*1000
            result["manifest_sha256"] = db.digest(manifest)
            with engine.begin() as conn:
                current = conn.execute(select(db.jobs).where(db.jobs.c.id == job["id"]).with_for_update()).mappings().one()
                if current["owner"] != owner or current["status"] != "running":
                    return True
                conn.execute(db.entities["validation_reports"].insert().values(id=job["run_id"],
                    project_id=job["project_id"], version="1", created_at=db.now(), payload=result))
                snapshots=[]
                if job["kind"]=="network":snapshots=[result]
                elif job["kind"]=="scenario":snapshots=[result["baseline"],result["scenario"]]
                for snapshot in snapshots:
                    conn.execute(db.entities["snapshots"].insert().values(id=snapshot["snapshot_id"],project_id=job["project_id"],version="1",created_at=db.now(),
                        payload={"run_id":job["run_id"],"mode":"connected_network","manifest_sha256":db.digest(manifest),"component_states":snapshot["components"]}))
                conn.execute(db.jobs.update().where(db.jobs.c.id == job["id"], db.jobs.c.owner == owner).values(
                    checkpoint=job["total"], status="completed", owner=None, lease_until=None, updated_at=db.now()))
    except Exception as exc:
        with engine.begin() as conn:
            conn.execute(db.jobs.update().where(db.jobs.c.id == job["id"], db.jobs.c.owner == owner).values(
                status="failed", error=f"{type(exc).__name__}: {exc}", owner=None, lease_until=None, updated_at=db.now()))
        print(json.dumps({"level": "error", "job_id": job["id"], "error": str(exc)}), flush=True)
    return True

def claim_outbox(engine, owner):
    clock = time.time()
    with engine.begin() as conn:
        query = select(db.outbox).where(db.outbox.c.published_at.is_(None),
            or_(db.outbox.c.owner.is_(None), db.outbox.c.lease_until < clock)).limit(1)
        if engine.dialect.name == "postgresql":
            query = query.with_for_update(skip_locked=True)
        row = conn.execute(query).mappings().first()
        if not row:
            return None
        changed = conn.execute(db.outbox.update().where(db.outbox.c.id == row["id"],
            or_(db.outbox.c.owner.is_(None), db.outbox.c.lease_until < clock)).values(owner=owner,
                lease_until=clock+30, attempts=db.outbox.c.attempts+1))
        return dict(row) if changed.rowcount == 1 else None

def complete_outbox(engine, owner, key):
    with engine.begin() as conn:
        return conn.execute(db.outbox.update().where(db.outbox.c.id == key, db.outbox.c.owner == owner,
            db.outbox.c.lease_until >= time.time()).values(published_at=db.now(), owner=None, lease_until=None)).rowcount

def main():
    engine = db.engine_for()
    owner = db.uid("worker")
    print(json.dumps({"event": "worker.started", "owner": owner, "concurrency": 1}), flush=True)
    while True:
        if not run_one(engine, owner):
            time.sleep(0.1)

if __name__ == "__main__":
    main()
