"""A 15 minute forecast on exact 5 minute samples with purged time splits."""
import json
import hashlib
from pathlib import Path
import numpy as np
import joblib
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from .contracts import Measurement


def train_forecast(path, output_path):
    frames = sorted([Measurement.model_validate_json(x) for x in
        Path(path).read_text().splitlines() if x.strip()], key=lambda m: m.event_time)
    if len({m.asset_id for m in frames}) != 1 or len(frames) < 240:
        raise ValueError("Need one asset and at least 240 exact 5 minute records")
    horizon, history = 3, 6
    x, y, persistence, indexes = [], [], [], []
    for i in range(history - 1, len(frames) - horizon):
        window = frames[i-history+1:i+horizon+1]
        if any((b.event_time - a.event_time).total_seconds() != 300
               for a, b in zip(window, window[1:])):
            continue
        if not all(m.usable("p_recv_mw") and m.connection_state == "CONNECTED"
                   for m in window):
            continue
        minute = frames[i].event_time.hour * 60 + frames[i].event_time.minute
        values = [m.p_recv_mw for m in window[:history]]
        values += [np.sin(2*np.pi*minute/1440), np.cos(2*np.pi*minute/1440)]
        x.append(values); y.append(frames[i+horizon].p_recv_mw)
        persistence.append(frames[i].p_recv_mw); indexes.append(i)
    x, y, persistence, indexes = map(np.asarray, (x, y, persistence, indexes))
    cut1, cut2 = int(len(frames)*0.6), int(len(frames)*0.8)
    train = indexes + horizon < cut1
    calibrate = (indexes >= cut1) & (indexes + horizon < cut2)
    test = indexes >= cut2
    if min(train.sum(), calibrate.sum(), test.sum()) < 20:
        raise ValueError("Insufficient valid records in one split")
    model = make_pipeline(StandardScaler(), Ridge(alpha=1.0))
    model.fit(x[train], y[train])
    half_width = float(np.quantile(np.abs(y[calibrate] - model.predict(x[calibrate])),
                                   0.95, method="higher"))
    errors = y[test] - model.predict(x[test])
    metrics = {"horizon_minutes": 15, "history_minutes": 25, "history_samples": 6,
        "model_version": "pr.forecast.ridge.v1", "asset_id": frames[0].asset_id,
        "dataset_ids": sorted({m.dataset_id for m in frames}),
        "input_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        "train_label_end": frames[cut1-1].event_time.isoformat(),
        "calibration_label_end": frames[cut2-1].event_time.isoformat(),
        "test_end": frames[-1].event_time.isoformat(),
        "bounds_low": x[train].min(axis=0).tolist(),
        "bounds_high": x[train].max(axis=0).tolist(),
        "feature_order": [f"p_recv_lag_{i}_mw" for i in range(5, -1, -1)] +
                         ["sin_time_utc", "cos_time_utc"],
        "data_origin": sorted({m.data_origin for m in frames}),
        "train_count": int(train.sum()), "calibration_count": int(calibrate.sum()),
        "test_count": int(test.sum()),
        "forecast_mae_mw": float(np.mean(np.abs(errors))),
        "persistence_mae_mw": float(np.mean(np.abs(y[test] - persistence[test]))),
        "empirical_half_width_mw": half_width,
        "test_interval_coverage": float(np.mean(np.abs(errors) <= half_width)),
        "automatic_promotion": False}
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "metadata": metrics}, output_path)
    Path(str(output_path)+".json").write_text(json.dumps(metrics, indent=2))
    return metrics
