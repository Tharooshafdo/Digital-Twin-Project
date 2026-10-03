"""Constrained example fit of R and X to independent receiving voltage."""
import json
from pathlib import Path
import numpy as np
from scipy.optimize import least_squares
from .contracts import Measurement, INPUTS
from .physics import solve_abcd


def fit_rx(path, cfg, output_path):
    if cfg.use_measured_temperature:
        raise ValueError("Temperature-dependent calibration needs a temperature-aware fit")
    frames=sorted([Measurement.model_validate_json(s) for s in
        Path(path).read_text().splitlines() if s.strip()], key=lambda m:m.event_time)
    frames=[m for m in frames if m.asset_id==cfg.asset_id and
        cfg.valid_from<=m.event_time and (cfg.valid_to is None or m.event_time<cfg.valid_to) and
        m.connection_state=="CONNECTED" and all(m.usable(k) for k in (*INPUTS,"vr_ll_kv"))]
    if len(frames)<60:
        raise ValueError("Need at least 60 frames and varying operating points")
    cut=int(0.7*len(frames))
    def errors(values, subset):
        candidate=cfg.model_copy(update={"r_ohm_per_km":values[0],"x_ohm_per_km":values[1]})
        return np.asarray([(m.vr_ll_kv-solve_abcd(candidate,m.vs_ll_kv,
            m.p_recv_mw,m.q_recv_mvar)["vr_ll_kv"])/m.uncertainty.get("vr_ll_kv",0.1)
            for m in subset])
    lower=[max(1e-6,cfg.r_ohm_per_km*0.5),cfg.x_ohm_per_km*0.5]
    upper=[cfg.r_ohm_per_km*1.5,cfg.x_ohm_per_km*1.5]
    fit=least_squares(lambda values:errors(values,frames[:cut]),
        [cfg.r_ohm_per_km,cfg.x_ohm_per_km],bounds=(lower,upper),loss="soft_l1",
        max_nfev=100)
    singular=np.linalg.svd(fit.jac,compute_uv=False)
    report={"candidate_r_ohm_per_km":float(fit.x[0]),
        "candidate_x_ohm_per_km":float(fit.x[1]),"fit_success":bool(fit.success),
        "weighted_test_rmse":float(np.sqrt(np.mean(errors(fit.x,frames[cut:])**2))),
        "jacobian_condition_number":float(singular[0]/max(singular[-1],1e-15)),
        "at_bound":bool(np.any(np.isclose(fit.x,lower)) or np.any(np.isclose(fit.x,upper))),
        "automatic_parameter_update":False,
        "note":"Voltage-only fit can confuse meter bias with impedance error"}
    Path(output_path).parent.mkdir(parents=True,exist_ok=True)
    Path(output_path).write_text(json.dumps(report,indent=2))
    return report
