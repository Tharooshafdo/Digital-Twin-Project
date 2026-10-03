import argparse
import hashlib
import importlib.metadata
import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import numpy as np
from .contracts import Measurement, load_configs
from .physics import solve_abcd
from .storage import Store
from .twin import evaluate


def generate(config_path, output_path, rows=288):
    cfg = load_configs(config_path)[0]
    rng = np.random.default_rng(42)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    frames = []
    for i in range(rows):
        vs = 132.1 + 0.5 * math.sin(2 * math.pi * i / 288)
        p = 66.8 + 20 * math.sin(2 * math.pi * i / 288)
        q = 13.5 + 4 * math.sin(2 * math.pi * i / 288)
        prediction = solve_abcd(cfg, vs, p, q)
        # Reproducible sensor bias/noise for software exercises, not field evidence.
        observed = {k: prediction[k] for k in
                    ("vr_ll_kv", "ir_a", "is_a", "p_send_mw", "q_send_mvar")}
        observed["vr_ll_kv"] += -0.12 + 0.001 * (p - 66.8) + rng.normal(0, 0.02)
        observed["p_send_mw"] += rng.normal(0, 0.03)
        m = Measurement(message_id=f"synthetic-v2-{i:06}", asset_id=cfg.asset_id,
            event_time=start + timedelta(minutes=5 * i), source_id="demo.generator.v2",
            dataset_id="synthetic.day.v2", data_origin="synthetic", sequence_no=i,
            connection_state="CONNECTED", vs_ll_kv=vs, p_recv_mw=p, q_recv_mvar=q,
            frequency_hz=50, signal_quality={k: "GOOD" for k in
                ("vs_ll_kv", "p_recv_mw", "q_recv_mvar", *observed)},
            uncertainty={"vr_ll_kv": 0.02, "p_send_mw": 0.03,
                         "p_recv_mw": 0.03}, **observed)
        frames.append(m)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text("".join(m.model_dump_json() + "\n"
        for m in frames), encoding="utf-8")
    return len(frames)


def manifest(configs):
    return {"code_version": "2.0.0", "schema_version": "line.state.v1",
        "dependencies": {name: importlib.metadata.version(name) for name in
                         ("pandapower", "pydantic", "SQLAlchemy")},
        "configs": [cfg.model_dump(mode="json") for cfg in configs],
        "input_roles": ["vs_ll_kv", "p_recv_mw", "q_recv_mvar"],
        "validation_roles": ["vr_ll_kv", "ir_a", "is_a", "p_send_mw", "q_send_mvar"]}


def process(path, store, configs, run_id, mode="offline"):
    store.init()
    store.register_parameters(configs)
    store.ensure_run(run_id, mode, manifest(configs))
    accepted = rejected = duplicate = 0
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            m = Measurement.model_validate_json(line)
            state = evaluate(m, configs, run_id, mode)
            state["mode"] = mode
            if store.commit_frame(m, state):
                accepted += 1
            else:
                duplicate += 1
        except ValueError as exc:
            store.dead_letter(exc, line)
            rejected += 1
    return {"accepted": accepted, "duplicate": duplicate, "rejected": rejected}


def report(store, run_id):
    rows = store.history(run_id, limit=100000)
    good = [r["payload"] for r in rows if r["model_status"] == "SOLVED"]
    keys = ("vr_ll_kv", "ir_a", "is_a", "p_send_mw", "q_send_mvar")
    result = {"run_id": run_id, "states": len(rows), "solved": len(good),
              "origin_counts": {x: sum(r["data_origin"] == x for r in rows)
                                for x in ("synthetic", "utility", "laboratory")}}
    for key in keys:
        errors = np.array([s["residual_physics"][key] for s in good
                           if key in s["residual_physics"]])
        if len(errors):
            result[key] = {"count": len(errors), "bias": float(errors.mean()),
                "mae": float(np.abs(errors).mean()),
                "rmse": float(np.sqrt(np.mean(errors ** 2)))}
    return result


def main():
    parser = argparse.ArgumentParser(description="Transmission line twin research reference")
    parser.add_argument("--config", default="config/lines.json")
    parser.add_argument("--db", default=os.getenv("DATABASE_URL", "sqlite:///twin.db"))
    sub = parser.add_subparsers(dest="command", required=True)
    g = sub.add_parser("generate-demo")
    g.add_argument("--out", default="data/demo.jsonl")
    g.add_argument("--rows", type=int, default=288)
    imp = sub.add_parser("import-csv")
    imp.add_argument("--input", required=True)
    imp.add_argument("--mapping", default="config/csv_mapping.json")
    imp.add_argument("--out", default="data/imported.jsonl")
    for name in ("process", "report", "consume"):
        p = sub.add_parser(name)
        p.add_argument("--run-id", required=True)
        if name == "process":
            p.add_argument("--input", required=True)
        if name == "consume":
            p.add_argument("--stream", default="demo")
            p.add_argument("--mode", choices=("replay", "live"), default="replay")
    replay_parser = sub.add_parser("replay")
    replay_parser.add_argument("--input", required=True)
    replay_parser.add_argument("--stream", default="demo")
    replay_parser.add_argument("--speed", type=float, default=60)
    replay_parser.add_argument("--checkpoint", default="data/replay.checkpoint.json")
    for name in ("network-demo", "estimate-demo", "three-phase-demo", "fault-demo", "thermal-demo"):
        sub.add_parser(name)
    ml = sub.add_parser("train-residual")
    ml.add_argument("--input", required=True)
    ml.add_argument("--out", default="models/residual.joblib")
    fc = sub.add_parser("train-forecast")
    fc.add_argument("--input", required=True)
    fc.add_argument("--out", default="models/forecast.joblib")
    args = parser.parse_args()
    if args.command == "generate-demo":
        output = {"generated": generate(args.config, args.out, args.rows)}
    elif args.command == "import-csv":
        from .importer import import_csv
        a, r = import_csv(args.input, args.mapping, args.out)
        output = {"accepted": a, "rejected": r}
    elif args.command in ("process", "report", "consume"):
        store = Store(args.db)
        configs = load_configs(args.config)
        if args.command == "process":
            output = process(args.input, store, configs, args.run_id)
        elif args.command == "report":
            output = report(store, args.run_id)
        else:
            from .mqtt_io import consume
            store.init()
            store.register_parameters(configs)
            store.ensure_run(args.run_id, args.mode, manifest(configs))
            consume(store, configs, args.run_id, args.stream, args.mode)
            return
    elif args.command == "replay":
        from .mqtt_io import replay
        replay(args.input, args.stream, args.speed, args.checkpoint)
        output = {"status": "broker_acknowledged"}
    elif args.command == "train-residual":
        from .learning import train_residual
        output = train_residual(args.input, load_configs(args.config), args.out)
    elif args.command == "train-forecast":
        from .forecast import train_forecast
        output = train_forecast(args.input, args.out)
    else:
        from . import advanced
        output = getattr(advanced, args.command.replace("-", "_"))()
    print(json.dumps(output, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
