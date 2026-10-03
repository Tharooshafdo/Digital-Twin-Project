import json
from datetime import timedelta
from pathlib import Path
import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from tl_twin.contracts import Measurement, load_configs, parameter_for
from tl_twin.physics import solve_line, solve_abcd, resistance
from tl_twin.storage import Store, states, dead_letters
from tl_twin.twin import evaluate
from tl_twin.cli import generate, process, report
from tl_twin.api import create_app
from tl_twin.importer import import_csv
from tl_twin import advanced
from tl_twin.network import load_network, solve_network

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def configs():
    return load_configs(ROOT / "config/lines.json")


@pytest.fixture
def frame(tmp_path, configs):
    path = tmp_path / "input.jsonl"
    generate(ROOT / "config/lines.json", path, 1)
    return Measurement.model_validate_json(path.read_text().strip())


@pytest.mark.parametrize("p,q,vs", [(66.8,13.5,132.1),(0,0,132),(40,8,133),(-30,-5,132)])
def test_independent_physics(configs, p, q, vs):
    a, b = solve_line(configs[0], vs, p, q), solve_abcd(configs[0], vs, p, q)
    for key in ("vr_ll_kv", "is_a", "ir_a", "p_send_mw", "q_send_mvar", "loss_mw"):
        assert a[key] == pytest.approx(b[key], rel=1e-7, abs=1e-7)
    assert b["abcd_determinant_error"] < 1e-12
    assert a["loss_mw"] >= 0


def test_reference_case(configs):
    r = solve_line(configs[0], 132.1, 66.8, 13.5)
    assert r["vr_ll_kv"] == pytest.approx(126.69751408584)
    assert r["loss_mw"] == pytest.approx(1.49234828494)
    assert r["p_send_mw"] - r["p_recv_mw"] == pytest.approx(r["loss_mw"])


def test_loading_parallel_and_temperature(configs):
    cfg = configs[0]
    cfg2 = cfg.model_copy(update={"parallel_circuits": 2})
    r = solve_line(cfg2, 132.1, 66.8, 13.5)
    assert r["loading_percent"] < 30
    assert resistance(cfg, 80) == pytest.approx(0.099344)
    assert solve_line(cfg,132.1,66.8,13.5,80)["loss_mw"] > 1.4923


@pytest.mark.parametrize("bad", ["vs_ll_kv", "p_recv_mw", "q_recv_mvar"])
def test_bad_input_blocks_solve(frame, configs, bad):
    frame.signal_quality[bad] = "BAD"
    s = evaluate(frame, configs, "test", "offline")
    assert s["model_status"] == "INPUTS_INSUFFICIENT"
    assert s["assessment"] != "WITHIN_LIMIT"
    assert s["prediction"] is None


@pytest.mark.parametrize("state,expected", [("UNKNOWN","TOPOLOGY_UNKNOWN"),
                                            ("DEENERGIZED","NOT_ENERGIZED")])
def test_topology_gate(frame, configs, state, expected):
    frame.connection_state = state
    assert evaluate(frame, configs, "test", "offline")["model_status"] == expected


def test_one_end_open_has_charging(frame, configs):
    frame.connection_state = "RECEIVING_OPEN"
    frame.p_recv_mw = frame.q_recv_mvar = 0
    frame.signal_quality["p_send_mw"] = "BAD"
    s = evaluate(frame, configs, "test", "offline")
    assert s["model_status"] == "SOLVED"
    assert s["prediction"]["is_a"] > 10
    assert s["prediction"]["ir_a"] < 1e-6


def test_open_inconsistent_and_inactive(frame, configs):
    frame.connection_state = "RECEIVING_OPEN"
    assert evaluate(frame,configs,"test","offline")["model_status"] == "TOPOLOGY_MISMATCH"
    frame.connection_state = "CONNECTED"
    cfg = configs[0].model_copy(update={"in_service":False})
    assert evaluate(frame,[cfg],"test","offline")["model_status"] == "TOPOLOGY_MISMATCH"


def test_failure_is_explicit(frame, configs):
    frame.p_recv_mw = 2000
    s = evaluate(frame,configs,"test","offline")
    assert s["model_status"] == "MODEL_FAILED"
    assert s["prediction"] is None


def test_parameter_selection(frame, configs):
    cfg = configs[0]
    cut = frame.event_time + timedelta(hours=1)
    old = cfg.model_copy(update={"valid_to":cut})
    new = cfg.model_copy(update={"valid_from":cut,"parameter_version":"v2"})
    assert parameter_for([old,new],cfg.asset_id,cut).parameter_version == "v2"
    with pytest.raises(ValueError):
        parameter_for([cfg,new],cfg.asset_id,cut)


def test_explicit_utc_and_finite(frame):
    payload = frame.model_dump(mode="json")
    payload["event_time"] = "2026-01-01T00:00:00"
    with pytest.raises(ValueError):
        Measurement.model_validate(payload)
    payload["event_time"] = "2026-01-01T05:30:00+05:30"
    assert Measurement.model_validate(payload).event_time.hour == 0
    payload["p_recv_mw"] = float("nan")
    with pytest.raises(ValueError):
        Measurement.model_validate(payload)


def test_freshness_uses_run_clock(frame, configs):
    s = evaluate(frame, configs, "test", "replay")
    assert s["freshness"] == "FRESH"
    s = evaluate(frame, configs, "test", "live", frame.event_time+timedelta(minutes=3))
    assert s["assessment"] == "STALE_DATA"


def test_zero_voltage_preserved_for_outage(frame, configs):
    frame=Measurement.model_validate({**frame.model_dump(),"vs_ll_kv":0,
                                      "connection_state":"DEENERGIZED"})
    assert evaluate(frame,configs,"test","offline")["model_status"]=="NOT_ENERGIZED"
    frame.connection_state="CONNECTED"
    assert evaluate(frame,configs,"test","offline")["model_status"]=="TOPOLOGY_MISMATCH"


def test_residuals_remain_independent(frame, configs):
    s = evaluate(frame,configs,"test","offline")
    frame.vr_ll_kv += 1
    changed = evaluate(frame,configs,"test","offline")
    assert s["prediction"] == changed["prediction"]
    assert changed["residual_physics"]["vr_ll_kv"] - s["residual_physics"]["vr_ll_kv"] == pytest.approx(1)


def test_runs_dedup_conflict_late_and_api(tmp_path, frame, configs):
    store = Store("sqlite:///"+str(tmp_path/"twin.db")); store.init()
    store.ensure_run("r1","offline",{}); store.ensure_run("r2","offline",{})
    s = evaluate(frame,configs,"r1","offline"); s["mode"]="offline"
    assert store.commit_frame(frame,s)
    assert not store.commit_frame(frame,s)
    s2 = evaluate(frame,configs,"r2","offline")
    assert store.commit_frame(frame,s2)
    changed = frame.model_copy(update={"p_recv_mw":1})
    with pytest.raises(ValueError):
        store.commit_frame(changed,s)
    late = frame.model_copy(update={"message_id":"late","sequence_no":1,
                                    "event_time":frame.event_time-timedelta(hours=1)})
    store.commit_frame(late,evaluate(late,configs,"r1","offline"))
    assert store.history("r1",frame.asset_id,1)[0]["message_id"] == frame.message_id
    assert len(store.outbox("r1")) == 2
    store.mark_published("r1",frame.message_id)
    assert len(store.outbox("r1")) == 1
    client = TestClient(create_app(str(store.engine.url)))
    assert client.get("/health").status_code == 200
    path = f"/v1/runs/r1/lines/{frame.asset_id}"
    assert client.get(path+"/latest").json()["message_id"] == frame.message_id
    assert len(client.get(path+"/history").json()) == 2
    assert client.get(path+"/history?limit=0").status_code == 422


def test_immutable_parameter_registry(tmp_path, configs):
    store = Store("sqlite:///"+str(tmp_path/"twin.db"));store.init()
    store.register_parameters(configs)
    store.register_parameters([configs[0].model_copy(update={"valid_to":configs[0].valid_from+timedelta(days=1)})])
    with pytest.raises(ValueError):
        store.register_parameters([configs[0].model_copy(update={"r_ohm_per_km":0.2})])


def test_csv_units_timezone_and_rejects(tmp_path):
    csv_path = tmp_path/"export.csv"
    csv_path.write_text("timestamp,Vs_V,Pr_kW,Qr_kvar\n2026-01-01T05:30:00,132100,66800,13500\nbad,1,2,3\n")
    mapping = {"timestamp_column":"timestamp","timezone":"Asia/Colombo",
        "asset_id":"TL_001","source_id":"test","data_origin":"laboratory",
        "connection_state":"CONNECTED","signals":{
        "vs_ll_kv":{"column":"Vs_V","scale":0.001},
        "p_recv_mw":{"column":"Pr_kW","scale":0.001},
        "q_recv_mvar":{"column":"Qr_kvar","scale":0.001}}}
    mp=tmp_path/"map.json";mp.write_text(json.dumps(mapping))
    out=tmp_path/"out.jsonl"
    assert import_csv(csv_path,mp,out)==(1,1)
    m=Measurement.model_validate_json(out.read_text().strip())
    assert m.event_time.hour==0 and m.p_recv_mw==66.8
    assert m.dataset_id.startswith("sha256:")


def test_batch_and_duplicate_replay(tmp_path, configs):
    path=tmp_path/"day.jsonl";generate(ROOT/"config/lines.json",path,24)
    store=Store("sqlite:///"+str(tmp_path/"twin.db"))
    assert process(path,store,configs,"day")["accepted"]==24
    assert process(path,store,configs,"day")["duplicate"]==24
    result=report(store,"day")
    assert result["solved"]==24 and result["vr_ll_kv"]["mae"]<0.2


def test_connected_network_balance_and_island():
    result=advanced.network_demo()
    assert abs(result["active_power_balance_error_mw"])<1e-6
    spec=load_network();spec["lines"][0]["in_service"]=False
    with pytest.raises(ValueError):
        solve_network(spec)


def test_state_estimation():
    result=advanced.estimate_demo()
    assert result["success"] and result["max_voltage_error_pu"]<1e-6


def test_three_phase_and_fault():
    result=advanced.three_phase_demo()
    assert 0<result["voltage_unbalance_percent"]<1
    sc=advanced.fault_demo()
    assert sc["ip_ka"]>sc["ikss_ka"]>0
    assert not sc["waveforms_computed"]


def test_thermal():
    result=advanced.thermal_demo()
    assert 35<result["pandapower_600s_temperature_c"]<80
    assert result["teaching_heat_model_steady_temperature_c"]>result["teaching_heat_model_600s_temperature_c"]
    assert not result["operational_rating_validated"]


def test_learning_and_forecast(tmp_path, configs):
    from tl_twin.learning import train_residual,corrected_voltage
    from tl_twin.forecast import train_forecast
    import joblib
    path=tmp_path/"training.jsonl";generate(ROOT/"config/lines.json",path,576)
    output=tmp_path/"residual.joblib"
    meta=train_residual(path,configs,output)
    assert meta["guarded_hybrid_test_mae_kv"]<meta["physics_test_mae_kv"]
    assert not meta["automatic_promotion"]
    m=Measurement.model_validate_json(path.read_text().splitlines()[0])
    m.vs_ll_kv=200
    assert not corrected_voltage(joblib.load(output),configs[0],m,126)["used_ml"]
    forecast=train_forecast(path,tmp_path/"forecast.joblib")
    assert forecast["forecast_mae_mw"]<forecast["persistence_mae_mw"]


def test_alignment_rejects_future_and_skew(frame):
    from tl_twin.alignment import assemble_frame
    envelope=frame.model_dump(mode="json")
    for key in ("vs_ll_kv","p_recv_mw","q_recv_mvar"):
        envelope.pop(key)
    samples={"vs_ll_kv":[{"event_time":"2026-01-01T00:00:01+00:00",
        "value":200,"quality":"GOOD"},{"event_time":"2025-12-31T23:59:59+00:00",
        "value":132.1,"quality":"GOOD"}],
        "p_recv_mw":[{"event_time":"2025-12-31T23:59:55+00:00",
        "value":66.8,"quality":"GOOD"}]}
    m=assemble_frame(envelope,samples)
    assert m.vs_ll_kv==132.1
    assert m.signal_quality["vs_ll_kv"]=="SUSPECT"
    assert m.source_metadata["alignment_skew_s"]==4


def test_mechanical_known_tension_and_calibration(tmp_path, configs):
    from tl_twin.mechanical import sag_catenary
    from tl_twin.calibration import fit_rx
    s=sag_catenary(300,12,20000)
    assert s["sag_parabolic_m"]==pytest.approx(6.75)
    assert 6.75<s["sag_catenary_m"]<6.76
    path=tmp_path/"calibration.jsonl";generate(ROOT/"config/lines.json",path,80)
    result=fit_rx(path,configs[0],tmp_path/"candidate.json")
    assert result["fit_success"] and not result["automatic_parameter_update"]
