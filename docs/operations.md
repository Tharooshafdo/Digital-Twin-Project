# Operations, reliability and upgrades

The default deployment is local, single API and one numerical worker. CPU solves
run synchronously in the separate worker process (one at a time), never in the
HTTP handler. More worker processes can claim independent jobs with transactional
leases; PostgreSQL uses SKIP LOCKED and SQLite uses conditional ownership updates.
Each solver builds a new mutable pandapower network. No solver-network cache is
introduced. A solve taking over the 300-second lease needs further engineering;
long-study heartbeats and hard CPU timeouts are not implemented.

Replay jobs checkpoint each frame in the same transaction as measurement, state,
alarm, snapshot and outbox. Crash before commit leaves the checkpoint unchanged.
Crash after commit resumes at the next index. A claimed job can be recovered after
its lease expires. Pause/cancel revoke ownership; a worker checks ownership/status
again before commit. Failed jobs require an explicit retry. There is no automatic
scientific-failure retry loop. MQTT database failures keep the frame pending and
unacknowledged; its fixed durable client identity is one owner per project stream.
Do not run two bridges with the same client ID. Frame and natural source identities
are scoped by project; changed content or alternate message IDs are quarantined.

State outbox claims have 30-second leases. Publishing followed by a process crash
can resend the same state. Downstream consumers must deduplicate the stable ID.
Manual broker ACK happens after durable input/state commit or durable dead letter.
The 1,000-message in-memory inbox reports overload by exiting without ACK; the
supervisor restarts the durable session. Broker persistent storage and configured
queue limits are part of the delivery boundary. QoS1 does not establish losslessness.

Health endpoints are `/api/health` (process) and `/api/ready` (schema/database).
Worker/error logs are in `data/`. Diagnostics expose stored counts, duplicate and
rejection counts, failed snapshots, pending jobs/outbox, oldest backlog age,
current wall age of observations, recent p50/p95/p99 solve latency, query time and
filesystem free space. Historical data age is shown separately from current UTC
age. Benchmarks measure admission-to-commit latency and payload/database sizes.
Continuous throughput instrumentation and centralized log/metrics collection are
not implemented. No high-availability claim is made.

## Recovery checks

SQLite backup/restore, conditional ownership races, lease recovery, outbox resend,
late ordering, duplicate/conflict handling and checkpoint recreation are tested in
the application suite. Windows service stop/start is exercised by the startup
scripts and `tools/runtime_check.py`. Docker/PostgreSQL/broker runtime tests below
are NOT RUN because this machine has no Docker executable/daemon.

Use a named disposable project/environment, never a live utility stack:

```powershell
docker compose -p grid-twin-qualification --profile streaming up -d --build
docker compose -p grid-twin-qualification exec api cat /app/data/initial-credentials.json
docker compose -p grid-twin-qualification stop worker bridge
docker compose -p grid-twin-qualification start worker bridge
docker compose -p grid-twin-qualification restart broker
docker compose -p grid-twin-qualification restart db
docker compose -p grid-twin-qualification up -d --force-recreate api worker bridge
```

For each interruption, publish a known input manifest before/during/after the
interruption, wait for recovery, reconcile exact expected IDs, inspect dead letters
and verify state count/manifest/duplicates. Restore into `twin_restore_check` using
README commands and run the same count/reconciliation checks. Keep named volumes;
do not use `down -v`. The above commands alone are NOT evidence that recovery works.

For broker reconciliation in Compose, copy the exact published JSONL into appdata:

```powershell
docker compose cp ./data/mqtt-demo.jsonl api:/app/data/mqtt-demo.jsonl
docker compose exec -T api python tools/reconcile.py --input /app/data/mqtt-demo.jsonl --run-id stream_demo
```

The tool reports missing measurements and missing committed states independently
of broker acknowledgements. `stream_demo` is historical simulated streaming.
Live utility ingestion needs approved source mappings, parameter/topology records,
clock policy and read-only gateways. None is supplied or connected here.

## Retention and sizing

Default retention is unlimited. `grid-twin retention --days N` is a dry run; explicit
`--apply` archives inactive completed runs to checksummed gzip JSONL and prunes
their hot states/published outbox while preserving raw data, run manifests and
audit/report lineage. Active streams/jobs/unpublished outbox are skipped. Archive
reconstruction and raw-import lifecycle management are not implemented. Review
archive files and verify backups before using pruning on important data.

Use measured `docs/evidence/benchmark.json` payload sizes, not architecture guesses.
Approximate daily payload storage for A assets at S-second cadence is
`A * 86400/S * measured_bytes_per_state`, plus normalized/raw measurements, indexes,
WAL, manifests and backups. Each imported raw file and bounded job frame list is
retained, so this release deliberately trades storage for inspectable lineage.
The 100-asset benchmark is a small burst, not sustained ingestion or a utility SLA.

## Upgrade procedure

1. Preserve `.env`, data volumes and encrypted/private credentials. Take a backup
   and rehearse restore into a separate database using the current version first.
2. Install from lock files in a fresh environment. Check plugin/platform ranges,
   `pip check`, frontend build and dependency license/audit records.
3. Run all numerical regressions (including independent ABCD, section cascades,
   signs and temperature) and representative approved chronological holdouts.
   Do not change holdout acceptance criteria after observing candidate errors.
4. Run populated migrations in the isolated restored database. Preserve immutable
   old manifests, parameter versions and timeline versions. Apply Alembic through
   `grid-twin init`; `create_all` is used only by the preserved legacy reference,
   never as an application upgrade mechanism.
5. Stop services, migrate the intended database and restart matching API/worker
   builds. Inspect readiness, reconciliation, errors and versions. If unsuccessful,
   stop services and restore the compatible pre-upgrade backup with the prior
   application/dependencies in an isolated environment. Do not assume a down
   migration can reverse scientific or destructive changes.
6. PostgreSQL major versions require an explicit tested dump/restore or supported
   pg_upgrade plan. Never attach an incompatible major image to the existing volume.

The Linux and container upgrade/rollback commands are documented, not executed.
The SQLite populated upgrade and backup/restore rehearsal are executed.

## Shared deployment boundary

The startup binds only localhost. Before organizational sharing, put the app behind
a TLS reverse proxy, use secure same-origin token transport and organization identity
integration, and implement a shared login rate limiter/session policy. An example
deployment could terminate TLS in an organization-managed nginx/Caddy proxy and
forward to the private API network. Certificate provisioning, OIDC/SAML integration,
distributed throttling, password reset/MFA and multi-tenant enterprise qualification
are not implemented. Local roles and project access are enforced on the server.
Utility telemetry stays read-only; model/scenario switches never issue commands.
