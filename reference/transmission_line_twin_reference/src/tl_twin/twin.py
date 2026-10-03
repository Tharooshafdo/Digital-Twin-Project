import math
from datetime import datetime, timezone
from .contracts import INPUTS, OUTPUTS, parameter_for, utc
from .physics import solve_line
from .storage import timestamp


def evaluate(m, configs, run_id, mode, clock_time=None, max_age_s=120):
    """Physics inputs are Vs and receiving P/Q; other signals are held out."""
    now = utc(clock_time or (m.event_time if mode != "live"
                            else datetime.now(timezone.utc)))
    age = (now - m.event_time).total_seconds()
    s = {
        "schema_version": "line.state.v1", "run_id": run_id,
        "message_id": m.message_id, "asset_id": m.asset_id,
        "event_time": timestamp(m.event_time), "received_at": timestamp(),
        "processed_at": timestamp(), "clock_time": timestamp(now),
        "dataset_id": m.dataset_id, "data_origin": m.data_origin,
        "model_status": "INPUTS_INSUFFICIENT", "assessment": "UNASSESSED",
        "flags": [], "freshness": "FRESH", "age_s": age,
        "prediction": None, "residual_physics": {},
        "signal_quality": m.signal_quality, "uncertainty": m.uncertainty,
        "connection_state": m.connection_state,
    }
    if age > max_age_s:
        s["freshness"] = "STALE"
        s["flags"].append("STALE_FOR_CURRENT_CLOCK")
    if age < -5:
        s["freshness"] = "FUTURE"
        s["flags"].append("EVENT_IN_FUTURE")
    try:
        cfg = parameter_for(configs, m.asset_id, m.event_time)
    except ValueError as exc:
        s["model_status"] = "PARAMETERS_UNAVAILABLE"
        s["flags"].append(str(exc))
        return s
    s.update(parameter_version=cfg.parameter_version,
             topology_version=cfg.topology_version)
    if m.connection_state in ("UNKNOWN", "DEENERGIZED"):
        s["model_status"] = ("TOPOLOGY_UNKNOWN" if m.connection_state == "UNKNOWN"
                              else "NOT_ENERGIZED")
        return s
    if not cfg.in_service:
        s["model_status"] = "TOPOLOGY_MISMATCH"
        return s
    required = ("vs_ll_kv",) if m.connection_state == "RECEIVING_OPEN" else INPUTS
    if not all(m.usable(k) for k in required):
        s["flags"].append("MISSING_OR_UNUSABLE_BOUNDARY_INPUT")
        return s
    if m.vs_ll_kv <= 0:
        s["model_status"] = "TOPOLOGY_MISMATCH"
        s["flags"].append("ENERGIZED_STATE_WITH_ZERO_SENDING_VOLTAGE")
        return s
    if m.usable("frequency_hz") and abs(
            m.frequency_hz - cfg.nominal_frequency_hz) > 0.5:
        s["model_status"] = "MODEL_DOMAIN_EXCEEDED"
        return s
    temp = None
    if cfg.use_measured_temperature:
        if not m.usable("conductor_temp_c"):
            s["flags"].append("CONDUCTOR_TEMPERATURE_REQUIRED")
            return s
        temp = m.conductor_temp_c
    p, q = (0.0, 0.0) if m.connection_state == "RECEIVING_OPEN" else (
        m.p_recv_mw, m.q_recv_mvar)
    if m.connection_state == "RECEIVING_OPEN" and any(
        m.usable(k) and abs(getattr(m, k)) > 0.01
        for k in ("p_recv_mw", "q_recv_mvar")
    ):
        s["model_status"] = "TOPOLOGY_MISMATCH"
        s["flags"].append("OPEN_END_HAS_NONZERO_RECEIVING_POWER")
        return s
    try:
        predicted = solve_line(cfg, m.vs_ll_kv, p, q, temp)
    except Exception as exc:
        s["model_status"] = "MODEL_FAILED"
        s["flags"].append(f"{type(exc).__name__}: {exc}")
        return s
    s["prediction"] = predicted
    s["model_status"] = "SOLVED"
    for k in OUTPUTS:
        if m.usable(k):
            s["residual_physics"][k] = getattr(m, k) - predicted[k]
    # A measurement sigma alone is NOT total model uncertainty.
    s["measurement_sigma_units"] = "same units as corresponding signal"
    if m.usable("p_send_mw") and m.usable("p_recv_mw"):
        measured_loss = m.p_send_mw - m.p_recv_mw
        s["measured_loss_mw"] = measured_loss
        s["loss_residual_mw"] = measured_loss - predicted["loss_mw"]
        if "p_send_mw" in m.uncertainty and "p_recv_mw" in m.uncertainty:
            # Assumes independent errors; include covariance if meters share errors.
            s["loss_measurement_sigma_mw"] = math.hypot(
                m.uncertainty["p_send_mw"], m.uncertainty["p_recv_mw"])
    for suffix, vkey, ikey, pkey, qkey in [
        ("send", "vs_ll_kv", "is_a", "p_send_mw", "q_send_mvar"),
        ("recv", "vr_ll_kv", "ir_a", "p_recv_mw", "q_recv_mvar")]:
        if all(m.usable(k) for k in (vkey, ikey, pkey, qkey)):
            vi = math.sqrt(3) * getattr(m, vkey) * getattr(m, ikey) / 1000
            pq = math.hypot(getattr(m, pkey), getattr(m, qkey))
            # Demo tolerance, not a substitute for CT/PT uncertainty propagation.
            if abs(vi - pq) > max(0.2, 0.03 * pq):
                s["flags"].append(f"POWER_CURRENT_INCONSISTENT_{suffix.upper()}")
    residual = s["residual_physics"].get("vr_ll_kv")
    if residual is not None and cfg.voltage_warn_kv and cfg.voltage_alarm_kv:
        s["assessment"] = ("ALARM" if abs(residual) >= cfg.voltage_alarm_kv
            else "WARNING" if abs(residual) >= cfg.voltage_warn_kv else "WITHIN_LIMIT")
    if s["flags"] or any(q != "GOOD" for q in m.signal_quality.values()):
        s["assessment"] = "DATA_REVIEW"
    if s["freshness"] != "FRESH":
        s["assessment"] = "STALE_DATA"
    return s
