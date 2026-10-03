import csv
import io
import json
import tempfile
import os
from pathlib import Path
from . import db, auth, service
from tl_twin.cli import generate

ROOT = Path(os.getenv("GRID_TWIN_ROOT", str(Path.cwd()))).resolve()

def demo_network():
    spec = json.loads((ROOT/"config/network.json").read_text())
    line_configs = json.loads((ROOT/"config/lines.json").read_text())
    components = []
    buses = {b["id"]: b["nominal_kv"] for b in spec["buses"]}
    def terminal(name, bus):
        return {"name": name, "bus_id": bus, "nominal_kv": buses[bus], "domain": "AC", "phases": "positive_sequence"}
    def component(id, type_id, parameters, terminals, x, y):
        components.append({"id": id, "name": id, "type_id": type_id, "parameters": parameters,
            "terminals": terminals, "in_service": True, "position": {"x": x, "y": y}})
    for i, b in enumerate(spec["buses"]):
        component(b["id"], "ac.bus", {"nominal_kv": b["nominal_kv"]}, [], i*230, 100 if i < 3 else 330)
    for i, line in enumerate(spec["lines"]):
        p = {k: v for k, v in line_configs[i].items() if k not in ("asset_id", "parameter_version", "topology_version", "valid_from", "valid_to", "from_bus", "to_bus", "in_service")}
        component(line["id"], "ac.line", p, [terminal("from", line["from_bus"]), terminal("to", line["to_bus"])], 100+i*230, 200)
    for i, tr in enumerate(spec["transformers"]):
        component(tr["id"], "ac.transformer2w", {k: v for k, v in tr.items() if k not in ("id", "hv_bus", "lv_bus")},
            [terminal("hv", tr["hv_bus"]), terminal("lv", tr["lv_bus"])], 400, 330)
    for i, load in enumerate(spec["loads"]):
        component(load["id"], "ac.load_pq", {"p_mw": load["p_mw"], "q_mvar": load["q_mvar"]},
            [terminal("bus", load["bus"])], 230+i*210, 480)
    source = spec["sources"][0]
    component("GRID_001", "ac.external_grid", {"vm_pu": source["vm_pu"]}, [terminal("bus", source["bus"])], 0, -60)
    return {"frequency_hz": 50, "components": components, "provenance": "synthetic"}

def demo_csv(rows=288):
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder)/"demo.jsonl"
        generate(ROOT/"config/lines.json", path, rows)
        frames = [json.loads(s) for s in path.read_text().splitlines()]
    fields = ["timestamp", "Vs_kV", "Vr_kV", "Pr_MW", "Qr_MVAr", "Ps_MW", "Qs_MVAr", "Is_A", "Ir_A", "connection_state"]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    for m in frames:
        writer.writerow(dict(zip(fields, [m["event_time"], m["vs_ll_kv"], m["vr_ll_kv"], m["p_recv_mw"], m["q_recv_mvar"],
            m["p_send_mw"], m["q_send_mvar"], m["is_a"], m["ir_a"], "CONNECTED"])))
    # An intentionally invalid row makes reject inspection part of every demo.
    writer.writerow({"timestamp": "invalid-demo-time", "Vs_kV": 132.1})
    mapping = json.loads((ROOT/"config/csv_mapping.json").read_text())
    mapping.update(data_origin="synthetic", source_id="demo.generator.v2", connection_state="CONNECTED")
    return buffer.getvalue(), mapping

def initialize(engine, credentials_path="data/initial-credentials.json"):
    from sqlalchemy import select
    with engine.begin() as conn:
        if conn.scalar(select(db.users.c.id).limit(1)):
            if conn.scalar(select(db.projects.c.id).where(db.projects.c.id=="demo")) and not conn.scalar(select(db.runs.c.id).where(db.runs.c.id=="stream_demo")):
                rid=conn.scalar(select(db.revisions.c.id).where(db.revisions.c.project_id=="demo",db.revisions.c.status=="published"))
                conn.execute(db.runs.insert().values(id="stream_demo",project_id="demo",kind="mqtt_stream",mode="replay",created_at=db.now(),manifest=service.run_manifest(conn,"demo",rid,"replay")))
            return {"status": "already_initialized", "credentials": str(credentials_path)}
        conn.execute(db.projects.insert().values(id="demo", name="Transmission research • synthetic", created_at=db.now()))
        account = auth.create_user(conn, "admin", "administrator", ["demo"])
        rid = service.create_revision(conn, "demo", demo_network(), "Synthetic connected baseline", account["id"], "2020-01-01T00:00:00Z")
        service.publish_revision(conn, "demo", rid, account["id"])
        conn.execute(db.runs.insert().values(id="stream_demo",project_id="demo",kind="mqtt_stream",mode="replay",created_at=db.now(),manifest=service.run_manifest(conn,"demo",rid,"replay")))
        for entry in __import__("grid_twin.plugins", fromlist=["registry"]).registry.catalog():
            conn.execute(db.entities["asset_types"].insert().values(id=entry["type_id"], project_id=None, version=entry["plugin_version"], created_at=db.now(), payload=entry))
    path = Path(credentials_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(account, indent=2), encoding="utf-8")
    raw, mapping = demo_csv()
    (path.parent/"demo.csv").write_text(raw, encoding="utf-8")
    (path.parent/"demo-mapping.json").write_text(json.dumps(mapping, indent=2), encoding="utf-8")
    return {"status": "initialized", "credentials": str(path), "project_id": "demo", "revision_id": rid}
