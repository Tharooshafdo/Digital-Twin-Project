# Grid Atlas: extensible power-system digital twin

Runnable local research application: React/TypeScript frontend, FastAPI backend,
separate numerical worker, Alembic migrations and persistent SQLite storage. The
first twin is a balanced transmission line with independent ABCD verification.
Basic AC components contribute to one connected pandapower solve, including a
real two-winding transformer. All supplied/demo operating data are synthetic.

**Read [capabilities](docs/capabilities.md) and [verification](docs/verification.md)
before relying on a feature.** Docker/PostgreSQL/Mosquitto runtime qualification
and utility field validation have not been performed here. Optional learning and
forecasting remain reference CLI experiments, not application workflows.

## Start in the supplied Windows workspace

The virtual environment, dependencies, built UI, database and synthetic demo
already exist in this workspace. In PowerShell at the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\start.ps1
Get-Content .\data\initial-credentials.json
```

Open **http://127.0.0.1:8000** and sign in using the generated credentials from that
private file. API documentation: **http://127.0.0.1:8000/docs**. Readiness:
**http://127.0.0.1:8000/api/ready**. The launcher starts both API and worker hidden,
records their PIDs and writes logs in `data/`. Stop them without deleting data:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\stop.ps1
```

The initialized database contains the connected demonstration and completed
replay runs. Use the run selector to inspect their actual January 2026 event range.
The initial credentials are generated once; setup never regenerates an existing
account's password. Keep `data/initial-credentials.json` and `.env` private.

## Fresh Windows installation

Install Python **3.12** and Node **24** (npm included). Run from this directory:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock -r requirements-dev.lock
.\.venv\Scripts\python.exe -m pip install setuptools wheel
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run build
.\.venv\Scripts\python.exe -m grid_twin.cli init
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\start.ps1
```

If Python 3.12 is absent, this workspace was bootstrapped using `python -m pip
install uv`, `python -m uv python install 3.12`, and `python -m uv venv --python
3.12 .venv`. Use `python -m ensurepip` inside a uv environment if it lacks pip.
Windows Application Control blocked uv's temporary isolated build interpreter;
the explicit `pip --no-build-isolation` installation above worked here.

For foreground services, use separate PowerShell terminals:

```powershell
.\.venv\Scripts\python.exe -m grid_twin.worker
```

```powershell
.\.venv\Scripts\python.exe -m uvicorn grid_twin.api:app --host 127.0.0.1 --port 8000
```

Keep the working directory at the repository root. The teaching research modules
read the frozen synthetic reference fixtures in `config/`.

## Equivalent Linux installation

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock -r requirements-dev.lock
.venv/bin/python -m pip install setuptools wheel
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
npm --prefix frontend ci
npm --prefix frontend run build
.venv/bin/python -m grid_twin.cli init
bash tools/start.sh
```

The Linux script runs both services and stops them on Ctrl+C. Linux runtime was
not executed on this Windows host. Core operation needs no cloud/paid service.
The built UI uses local assets/system fonts.

## Overview map and operating workflows

Admin sign-in opens **Overview** with component locations, automatically refreshed
synthetic grid voltage/frequency/demand, and **Simulate changes** / **Inspect
operating data** actions. Engineers can save asset coordinates. Simulation compares
the baseline and candidate before an administrator publishes the tested candidate
to a new platform model version. Actual field values remain unavailable until a
source is connected. Google Maps is configurable through a restricted browser key;
the coordinate map works immediately without one.

See [overview configuration and source contract](docs/overview.md) for exact Google
Maps startup settings, telemetry API, data-quality boundaries and test evidence.

## Executable demo and engineering workflow

```powershell
.\.venv\Scripts\python.exe -m grid_twin.cli demo --rows 288
```

This generates reproducible synthetic frames, queues a frozen run, processes it
through the persistent worker workflow and saves `docs/evidence/demo.json`. It
does not require a broker. It is safe to run with the worker: ownership is leased.
`init` writes `data/demo.csv` and `data/demo-mapping.json` for the browser wizard.

1. Inspect **Component catalog** for catalog/study/twin support, then open
   **Single-line editor**. Select a line/transformer, edit parameters/terminals,
   save a named draft, and reload it from the version selector. Invalid electrical
   connections are rejected by the backend.
2. **Data imports**: choose the generated CSV and mapping JSON. Preview the
   normalized rows and intentional invalid timestamp; save the import. Units,
   timezone, scale/direction/CT/PT, uncertainty and missing values are configurable.
3. **Runs & replay**: choose a saved revision/import, set replay speed and start.
   Wait for the separate worker's durable checkpoint to reach total. Pause/resume,
   cancel/retry and speed controls are persistent.
4. **Line dashboard**: choose a completed replay and line. Inspect measured/predicted
   voltage, raw residuals, loss/loading, status/quality, history and versions.
5. **Validation & scenarios**: inspect independent errors, run an isolated PQ-load
   scenario comparison, export CSV/HTML, or create an R/X calibration candidate
   from 60+ chronological frames. Candidates are not auto-published.
6. **Research studies**: execute supplied estimation, thermal/TDPF, three-phase,
   fault or known-tension catenary examples and inspect persisted results.
7. **Alerts**, **Diagnostics**, and **Configuration** show discrepancy hysteresis,
   backlog/latency, version/audit history and generated role-limited accounts.

Publication requires administrator role. Give a new open revision a later UTC
effective time: publication creates a new timeline closing its predecessor,
without editing previous timelines or runs. Same-start overlapping publication
is rejected. Cable sections carry separately sourced electrical ratings; no
overhead thermal model is used for cable thermal claims.

## Tests and benchmarks

```powershell
.\.venv\Scripts\python.exe -m pytest --junitxml=docs/evidence/all-tests.xml
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe tools/browser_check.py
.\.venv\Scripts\python.exe tools/overview_browser_check.py
.\.venv\Scripts\python.exe tools/benchmark.py --assets 1 10 100 --snapshots 1
.\.venv\Scripts\python.exe tools/benchmark.py --assets 1 10 100 --snapshots 10 --out docs/evidence/manual-benchmark.json
```

Browser tests require the real application/worker on port 8000 and generated
credentials/demo files. They create labeled test drafts/imports/runs without
removing existing work. Benchmark databases are isolated temporary files. The
larger benchmark is a manual command, not a measured production capacity claim.

## Docker Compose (implemented; runtime NOT RUN here)

Install Docker Desktop with Linux containers. Stop the local services first.

```powershell
.\.venv\Scripts\python.exe tools/configure.py
docker compose config --quiet
docker compose build
docker compose up -d
docker compose logs init
docker compose exec api cat /app/data/initial-credentials.json
```

The same URL serves the application. Named volumes retain PostgreSQL, app files
and broker data. The app uses the non-superuser `dt_app` database role; its own
migrations own application tables. Do not regenerate secrets for existing
volumes. Start/stop/recreate without volume deletion:

```powershell
docker compose stop
docker compose up -d
docker compose up -d --force-recreate api worker
docker compose down
```

Optional simulated MQTT path:

```powershell
docker compose --profile streaming up -d
```

`stream_demo` is a frozen synthetic replay-clock run initialized for the bridge.
The bridge subscribes to `dt/v1/project/demo/input/line/+/measurement`, manually
acknowledges QoS1 after measurement/state/alarm/outbox commit, and drains leased
state outbox records to scoped run topics. The producer must use the generated
`dt_publisher` credentials (`MQTT_USER`, `MQTT_PASSWORD`, and optional `MQTT_CA`).
Generate reference JSONL using the reference CLI, then:

```powershell
.\.venv\Scripts\python.exe -m tl_twin.cli generate-demo --out data/mqtt-demo.jsonl
.\.venv\Scripts\python.exe tools/mqtt_replay.py --input data/mqtt-demo.jsonl --speed 600
.\.venv\Scripts\python.exe tools/reconcile.py --input data/mqtt-demo.jsonl --run-id stream_demo --db $env:DATABASE_URL
```

For Compose reconciliation, run the tool against PostgreSQL from a helper
container as described in `docs/operations.md`; the DB is not exposed on the host.
Broker acknowledgements are never presented as numerical commit evidence.
Real broker overload/interruption/restart qualification remains NOT RUN.

## Back up, restore and reset

SQLite backup works while the app is running through the SQLite backup API:

```powershell
.\.venv\Scripts\python.exe -m grid_twin.cli backup --out data/backups/platform.db
.\.venv\Scripts\python.exe -m grid_twin.cli --db sqlite:///data/restore-check/platform.db restore --input data/backups/platform.db
```

Backup targets and restore database paths must be new; existing files are not
overwritten. Switch `DATABASE_URL` to the isolated restored DB and run `init`
to apply pending migrations. Restore was rehearsed on SQLite here. PostgreSQL:

```powershell
docker compose exec -T db pg_dump -U twin -d twin -Fc -f /tmp/twin-backup.dump
docker compose cp db:/tmp/twin-backup.dump ./data/backups/twin-backup.dump
docker compose exec -T db createdb -U twin twin_restore_check
docker compose cp ./data/backups/twin-backup.dump db:/tmp/twin-restore.dump
docker compose exec -T db pg_restore -U twin -d twin_restore_check --no-owner /tmp/twin-restore.dump
```

These PostgreSQL commands are NOT RUN. Restore into the named isolated database,
then verify counts/manifests/reconciliation before considering recovery complete.

To start a fresh offline demonstration **without deleting the current one**, stop
services, set `$env:DATABASE_URL='sqlite:///data/new-demo/platform.db'`, and run
`init`. SQLite credentials/demo files are generated beside that database
(`data/new-demo/initial-credentials.json` in this example). Named test
environments should use separate data directories. No reset
procedure deletes a volume or recursively removes workspace files.

Opt-in retention archives completed runs only after their outbox is published:

```powershell
.\.venv\Scripts\python.exe -m grid_twin.cli retention --project demo --days 90 --out data/archive
# Review the dry-run list, then explicitly apply:
.\.venv\Scripts\python.exe -m grid_twin.cli retention --project demo --days 90 --out data/archive --apply
```

Archives contain frozen manifests, reports and complete states, with checksums
and retained audit pointers. Raw measurements/imports/topology/parameters remain
in the database. Streaming/active jobs and unpublished outbox are never pruned.
Archive reconstruction UI and full raw-import retention are future work.

## Repository guides

See [architecture](docs/architecture.md), [component extension](docs/component-extension.md),
[API/data contracts](docs/api-and-data.md), [operations/upgrades](docs/operations.md),
[requirements matrix](docs/requirements-to-tests.md), [capabilities](docs/capabilities.md),
[verification](docs/verification.md), [reference traceability](docs/reference-traceability.md)
and [licenses](docs/licenses.md). Open the supplied handbook text in
`reference/handbook.txt`; the original archive tree is retained unchanged.
