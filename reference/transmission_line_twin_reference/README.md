# Transmission line twin reference version 2

Read `docs/handbook.md` or the accompanying Word handbook. This project is an inspectable research starting point for a read-only transmission-line twin. Every demonstration asset and operating dataset is synthetic. It includes independent pi verification, quality/topology/time gates, versioned SQLite/PostgreSQL storage, a read-only API, MQTT replay with a transactional outbox, a Grafana dashboard, and separate advanced electrical/thermal/learning exercises.

Requires Python 3.12. Run commands from this directory.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock -r requirements-dev.lock
python -m pip install --no-deps -e .
python -m pytest
python -m tl_twin.cli generate-demo --out data/demo.jsonl
python -m tl_twin.cli process --input data/demo.jsonl --run-id offline-v2
python -m tl_twin.cli report --run-id offline-v2
python -m uvicorn tl_twin.api:app --host 127.0.0.1 --port 8000
```

On Windows use `py -3.12 -m venv .venv`, then the explicit executable `.\.venv\Scripts\python.exe` instead of `python`. Activation is optional. API docs are at http://127.0.0.1:8000/docs. Stop the local API before starting the Compose API on the same port.

```bash
python tools/configure.py
python tools/make_dashboard.py
docker compose config --quiet
docker compose pull
docker compose build
docker compose up -d
python tools/replay_docker.py --input data/demo.jsonl --speed 600
```

Grafana is at http://127.0.0.1:3000. Private generated credentials are in `.env`; never commit it. The dashboard starts with a historical 1 January 2026 UTC time window. The replay worker uses run `replay-v2` and stream `demo`. PostgreSQL 18 persists at `/var/lib/postgresql`. Do not regenerate `.env` for existing volumes.

```bash
python -m tl_twin.cli network-demo
python -m tl_twin.cli estimate-demo
python -m tl_twin.cli thermal-demo
python -m tl_twin.cli three-phase-demo
python -m tl_twin.cli fault-demo
python -m tl_twin.cli train-residual --input data/demo.jsonl
python -m tl_twin.cli train-forecast --input data/demo.jsonl
```

The thermal-rating example uses a teaching heat model and is not an operational rating. ML candidates are not automatically enabled. Actual utility validation requires approved parameters, measurements, topology and uncertainty evidence. The handbook specifies the deployment, restart, reconciliation and recovery checks. See `VERIFICATION.md` for the precise checks executed for this edition and the remaining container/field validation boundary.
