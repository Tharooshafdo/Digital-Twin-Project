#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data
.venv/bin/python -m grid_twin.cli init
.venv/bin/python -m grid_twin.worker >data/worker.log 2>&1 &
task_worker=$!
.venv/bin/python -m uvicorn grid_twin.api:app --host 127.0.0.1 --port 8000 >data/api.log 2>&1 &
task_api=$!
trap 'kill "$task_api" "$task_worker" 2>/dev/null || true' EXIT INT TERM
echo 'Open http://127.0.0.1:8000. Credentials: data/initial-credentials.json. Ctrl+C stops both services.'
wait
