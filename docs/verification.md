# Executed verification — 3 October 2026

Hardware: Windows 11, Intel Core i5-1135G7 @2.40GHz, 4 physical/8 logical cores.
Python 3.12.15 was installed in an isolated environment; the reference pins were
preserved. Node 24.21.0 built the UI. No Docker executable/daemon is installed.
All utility data, parameters and field holdouts remain absent.

| Check | Executed outcome | Evidence |
|---|---|---|
| Original suite before refactor | 30 passed, 6 dependency warnings | `evidence/reference-tests.xml` |
| Full final Python suite | 76 passed, 11 dependency warnings, 151.55s | `evidence/all-tests.xml` |
| Reference preservation | 48 archive files byte-identical; 16 modules reused; only optional solver hook in twin.py changed | `evidence/reference-comparison.json` |
| Runtime dependency consistency | pip check: no broken requirements | installed lock environment |
| Production frontend | TypeScript and Vite build passed | `evidence/frontend-build.txt` |
| npm audit | 0 reported vulnerabilities after Vite patch | `evidence/npm-audit.json` |
| Real Chromium browser | 11 checks passed; no mocked responses or JS runtime errors | `evidence/browser-checks.json` |
| Actual historical browser replay | 288 persisted solved states, 1 explicit invalid CSV row | browser results/report and SQLite run |
| Scenario comparison | Persisted baseline and changed-load network solve, positive loss delta | browser-checks.json and exported report |
| SQLite migration/recovery/auth/plugins | Populated upgrade, new identity backfill, roles/projects, races, leases, restore and retention tests passed | all-tests.xml |
| API contract and Python compilation | OpenAPI recorded; compileall passed | `openapi.json`, sources/migrations/tools |
| Small workload measurements | 1/10/100 independent assets committed and solved; three connected solves balanced | `evidence/benchmark.json` |
| Windows process restart | Gate outcome in runtime-recovery.json | `evidence/runtime-recovery.json` |
| Compose specification | 7-service YAML parsed; NOT a runtime deployment | `evidence/compose-static.json` |

The original baseline run took 466.54s. The later full run includes those original
tests plus 46 application checks, including the optional reference learning and
forecast tests. Differences in duration are workstation load/runtime effects;
no performance claim is based on pytest duration. Visible upstream warnings are
Starlette/AnyIO deprecation and pandapower/Pandas future/deprecation warnings.
They were not suppressed by weakening numerical checks.

The 288-row synthetic receiving-voltage comparison has expected bias/noise around
−0.1203kV. Near-zero current/reactive residuals share the reference equivalent
circuit generator and do not establish independent field accuracy. The regression
case targets and sign conventions are in reference-traceability.md.

Final small burst benchmark (not sustained operation):

| Independent assets | Duration s | States/s | Processing p50/p95/p99 ms | Admission-to-commit p99 ms |
|---:|---:|---:|---|---:|
| 1 | 0.231 | 4.326 | 229.8 / 229.8 / 229.8 | 231.2 |
| 10 | 1.679 | 5.955 | 159.0 / 206.2 / 218.9 | 1666.1 |
| 100 | 19.940 | 5.015 | 195.4 / 248.8 / 275.1 | 19758.1 |

One snapshot per asset was submitted as a burst to a single worker with local
SQLite, without broker/network latency. State JSON averaged about 3.46kB at
100 assets; the database measured 1.89MB at the end of that workload. These values
exclude long-run backups, raw files, WAL growth and deployment overhead. Three
11-component connected solves had p50/p95/p99 of about 181.1/187.5/188.1ms and
active-power mismatch −1.6431e−8MW. Small-sample tail quantiles are descriptive;
they do not establish sustained cadence, production capacity or high availability.

NOT RUN gates and reproduction commands:

* Docker image build/service startup and populated PostgreSQL execution:
  `python tools/configure.py`, `docker compose config --quiet`,
  `docker compose build`, `docker compose --profile streaming up -d`.
* Mosquitto redelivery, overload/session recovery, actual manual-ACK ordering,
  database/broker interruption, service recreation with volumes retained:
  follow the named `grid-twin-qualification` procedure in operations.md and
  `tools/reconcile.py`. Synthetic delivery/lease/overload tests do not replace it.
* PostgreSQL backup/isolated restore: execute README's pg_dump/pg_restore commands,
  then verify exact measurement/state identities and frozen manifests.
* Linux startup: fresh Python 3.12/Node setup followed by `bash tools/start.sh`.
* Utility accuracy, operational thermal/dynamic ratings, surveyed clearance,
  equipment/protection models and vendor gateways: require approved data and
  independent engineering validation that were not provided.

No deployment/field/throughput result beyond the actual executed measurements is
claimed. See capabilities.md for implemented, unexecuted and deferred components.
