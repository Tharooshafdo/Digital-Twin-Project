import json
from pathlib import Path

variables = [
    ("run", "SELECT DISTINCT run_id FROM twin_states ORDER BY run_id"),
    ("asset", "SELECT DISTINCT asset_id FROM twin_states ORDER BY asset_id")]
panels = []
series = [
    ("Measured and predicted receiving voltage", "vr_measured_kv AS measured, vr_predicted_kv AS predicted", "kvolt"),
    ("Raw physics voltage residual", "vr_residual_kv AS residual", "kvolt"),
    ("Active loss", "loss_predicted_mw AS loss", "mwatt"),
    ("Line loading", "loading_percent AS loading", "percent")]
for i, (title, columns, unit) in enumerate(series):
    panels.append({"id":i+1,"type":"timeseries","title":title,
        "datasource":{"type":"postgres","uid":"twin-postgres"},
        "gridPos":{"x":(i%2)*12,"y":(i//2)*8,"w":12,"h":8},
        "fieldConfig":{"defaults":{"unit":unit},"overrides":[]},
        "targets":[{"refId":"A","format":"time_series","rawQuery":True,
            "rawSql": "SELECT event_time::timestamptz AS time, " + columns +
                " FROM twin_states WHERE run_id=${run:sqlstring} AND " +
                "asset_id=${asset:sqlstring} AND $__timeFilter(event_time::timestamptz) " +
                "ORDER BY event_time::timestamptz"}]})
panels.append({"id":5,"type":"table","title":"Latest status and origin",
    "datasource":{"type":"postgres","uid":"twin-postgres"},
    "gridPos":{"x":0,"y":16,"w":24,"h":6},
    "targets":[{"refId":"A","format":"table","rawQuery":True,"rawSql":
        "SELECT event_time, data_origin, model_status, assessment, parameter_version, " +
        "topology_version FROM twin_states WHERE run_id=${run:sqlstring} AND " +
        "asset_id=${asset:sqlstring} ORDER BY event_time DESC LIMIT 1"}]})
dashboard={"uid":"transmission-twin-v2","title":"Transmission line twin v2",
    "schemaVersion":39,"version":1,"refresh":"5s","panels":panels,
    "time":{"from":"2026-01-01T00:00:00Z","to":"2026-01-02T00:00:00Z"},
    "templating":{"list":[{"name":name,"type":"query","query":sql,
        "datasource":{"type":"postgres","uid":"twin-postgres"},
        "refresh":1,"multi":False,"includeAll":False} for name,sql in variables]}}
path=Path("deploy/grafana/dashboards/transmission-line.json")
path.parent.mkdir(parents=True,exist_ok=True)
path.write_text(json.dumps(dashboard,indent=2))
print(path)
