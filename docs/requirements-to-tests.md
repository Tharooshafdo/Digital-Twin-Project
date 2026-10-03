# Requirements and verification plan

Final execution status and precise boundaries are recorded in
`capabilities.md` and `verification.md` after execution.

| Milestone | Required behaviour | Evidence target |
|---|---|---|
| 1 | Preserve/reproduce original numerical behaviour | PASS: reference-tests.xml; reference-comparison.json |
| 2 | Migrations, immutable versions, plugin registry, shared solve, auth | PASS SQLite: all-tests.xml; PostgreSQL NOT RUN |
| 3 | Create/save/reload network and transformer, invalid edge rejection | PASS: browser-checks.json with real API |
| 4 | Line physics, ABCD, independent residual, quality/time gates | PASS: preserved and application numerical tests |
| 5 | CSV rejects, durable replay, MQTT, charts, alarms, exports | PASS local workflows; broker runtime NOT RUN |
| 6 | Research and isolated scenarios, persisted reports | PASS integrated research/scenario/calibration tests; optional ML application path deferred |
| 7 | Recovery, permissions, benchmarks, deployment, backups | PASS SQLite tests/benchmarks; runtime-recovery.json records Windows gate; Compose/PostgreSQL/Linux runtime NOT RUN |

Specific regression cases: forward/reverse/zero flow; terminal conservation;
parallel versus bundles; measured temperature; open ends and islands; current UTC
freshness versus event clock; BAD newest as-of samples; parameter gaps/overlaps;
immutable run history; identical/conflicting message IDs; restart checkpoint;
late ordering; outbox lease expiry; alarms without ML; roles/project scoping;
incompatible plugins; upgrade on populated DB; exported manifest lineage.

Browser journeys must use the real backend and worker: create/edit/reload,
invalid connection, import/reject review, replay, residual charts, history,
scenario and human-readable report export. No mocked backend responses.
