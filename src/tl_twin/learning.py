"""Optional bounded residual correction; raw physics alarms stay authoritative."""
import hashlib
import json
import platform
from pathlib import Path
import numpy as np
import joblib
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from .contracts import Measurement, parameter_for
from .physics import MODEL_VERSION, solve_line

FEATURES = ["vs_ll_kv", "p_recv_mw", "q_recv_mvar"]


def train_residual(path, configs, output_path):
    frames = [Measurement.model_validate_json(x) for x in
              Path(path).read_text().splitlines() if x.strip()]
    frames.sort(key=lambda m: m.event_time)
    eligible = [m for m in frames if m.connection_state == "CONNECTED"
                and all(m.usable(k) for k in FEATURES + ["vr_ll_kv"])]
    assets = {m.asset_id for m in eligible}
    if len(assets) != 1 or len(eligible) < 120:
        raise ValueError("Train one asset with at least 120 valid chronological frames")
    params = {parameter_for(configs, m.asset_id, m.event_time).parameter_version
              for m in eligible}
    if len(params) != 1:
        raise ValueError("Train one parameter regime; split versions explicitly")
    xs, residuals, times = [], [], []
    for m in eligible:
        cfg = parameter_for(configs, m.asset_id, m.event_time)
        if cfg.use_measured_temperature:
            raise ValueError("Extend features and validate temperature role before training")
        yphysics = solve_line(cfg, m.vs_ll_kv, m.p_recv_mw, m.q_recv_mvar)["vr_ll_kv"]
        xs.append([getattr(m, k) for k in FEATURES])
        residuals.append(m.vr_ll_kv - yphysics)
        times.append(m.event_time.isoformat())
    x, y = np.asarray(xs), np.asarray(residuals)
    a, b = int(len(x) * 0.6), int(len(x) * 0.8)
    model = make_pipeline(StandardScaler(), Ridge(alpha=1.0))
    model.fit(x[:a], y[:a])
    calibration_error = np.abs(y[a:b] - model.predict(x[a:b]))
    quantile = float(np.quantile(calibration_error, 0.95, method="higher"))
    # This is empirical holdout coverage; time dependence can invalidate exchangeability.
    test_error = y[b:] - model.predict(x[b:])
    in_domain = np.all((x[b:] >= x[:a].min(axis=0)) &
                       (x[b:] <= x[:a].max(axis=0)), axis=1)
    guarded_error = np.where(in_domain, test_error, y[b:])
    metadata = {"features": FEATURES, "target": "measured Vr minus raw physics Vr",
        "asset_id": next(iter(assets)), "parameter_version": next(iter(params)),
        "physics_version": MODEL_VERSION,
        "data_origin": sorted({m.data_origin for m in eligible}),
        "dataset_ids": sorted({m.dataset_id for m in eligible}),
        "input_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        "python_version": platform.python_version(),
        "train_end": times[a-1], "calibration_end": times[b-1], "test_end": times[-1],
        "counts": {"train": a, "calibration": b-a, "test": len(x)-b},
        "bounds_low": x[:a].min(axis=0).tolist(),
        "bounds_high": x[:a].max(axis=0).tolist(),
        "empirical_95_percent_error_half_width_kv": quantile,
        "physics_test_mae_kv": float(np.mean(np.abs(y[b:]))),
        "unguarded_hybrid_test_mae_kv": float(np.mean(np.abs(test_error))),
        "guarded_hybrid_test_mae_kv": float(np.mean(np.abs(guarded_error))),
        "test_ml_coverage_fraction": float(np.mean(in_domain)),
        "test_interval_coverage": float(np.mean(np.abs(test_error) <= quantile)),
        "automatic_promotion": False}
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "metadata": metadata}, output_path)
    Path(str(output_path) + ".json").write_text(json.dumps(metadata, indent=2))
    return metadata


def corrected_voltage(artifact, cfg, measurement, raw_voltage_kv):
    meta = artifact["metadata"]
    if (cfg.asset_id != meta["asset_id"] or cfg.parameter_version != meta["parameter_version"]
            or meta["physics_version"] != MODEL_VERSION
            or measurement.connection_state != "CONNECTED"
            or not all(measurement.usable(k) for k in FEATURES)):
        return {"voltage_kv": raw_voltage_kv, "used_ml": False, "reason": "INCOMPATIBLE"}
    x = np.array([getattr(measurement, k) for k in FEATURES])
    if np.any(x < meta["bounds_low"]) or np.any(x > meta["bounds_high"]):
        return {"voltage_kv": raw_voltage_kv, "used_ml": False, "reason": "OUT_OF_DOMAIN"}
    correction = float(artifact["model"].predict(x.reshape(1, -1))[0])
    return {"voltage_kv": raw_voltage_kv + correction, "used_ml": True,
        "correction_kv": correction,
        "empirical_half_width_kv": meta["empirical_95_percent_error_half_width_kv"]}
