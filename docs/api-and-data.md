# API and scientific data contracts

Run the application and open `/docs` for the generated OpenAPI schema. The
committed snapshot is `docs/openapi.json`. Every data route requires a bearer
session token and project membership. Viewer reads and exports; engineer creates
drafts, imports, studies and acknowledges discrepancies; administrator publishes
versions/policies and creates projects/accounts. There are no utility equipment
command routes. Configuration POSTs affect this application's simulation only.

`POST /api/auth/login` returns an 8-hour opaque session token. Argon2 hashes protect
passwords; only token hashes are stored. Login is locally rate limited (20 attempts
per minute per client process). This is not a shared rate limiter or enterprise
identity integration. Logout revokes the stored session.

Core routes (all data prefixes include `/api/projects/{project_id}`):

| Path | Purpose |
|---|---|
| `revisions` / `revisions/{id}` | Store a new draft, list/read revisions |
| `revisions/{id}/publish` | Audited publication and new immutable effective timeline |
| `imports/preview`, `imports`, `imports/{id}/rejects` | Strict mapping, persisted raw UTF-8 text, rejection review |
| `studies` | Queue replay/network/scenario/research/calibration |
| `signal-snapshots` | As-of assembly and queue one aligned snapshot |
| `jobs`, `jobs/{id}/control` | Durable progress and pause/resume/cancel/retry/speed |
| `runs`, `runs/{id}/history` | Frozen manifests and paginated states |
| `runs/{id}/report`, `runs/{id}/export` | Aggregated validation; HTML figures and complete CSV |
| `alerts`, `alerts/{id}/acknowledge`, `alarm-policy` | Persistent discrepancy state and audited policies |
| `audit`, `diagnostics` | Project-scoped lineage and service measurements |

The application stores native timezone-aware PostgreSQL timestamps and JSONB.
SQLite is deliberately supported for offline use: UTC-aware bind/result adapters
restore explicit UTC offsets because SQLite has no native timezone type. Original
timestamp, source timezone, event/receipt/processing clocks, dataset checksum,
mapping hash, adapter/schema/plugin/physics/topology/parameter versions are retained.

Measurement schema is the supplied `line.measurement.v1`. Values are sending and
receiving line-to-line RMS kV, total three-phase MW/MVAr and RMS terminal A.
Receiving P/Q is positive leaving the selected line. Reverse flow preserves the
terminal names. Required inputs are Vs and receiving P/Q; Vr and sending quantities
are independent validation observations. Receiving-open requires only usable Vs
and zero receiving P/Q if observed. Zero voltage is retained for a deenergized
state, not replaced with a positive value.

As-of request example: supply a normal measurement `envelope`, `revision_id` and
`samples = {"vs_ll_kv": [{"event_time":"2026-01-01T00:00:00Z", "value":132.1,
"quality":"GOOD", "sigma":0.02}], ...}`. Samples must be in canonical units.
For each signal choose the newest sample with event time <= snapshot time,
regardless of quality. A recent BAD sample is retained; an older GOOD sample
does not replace it. Age >10s becomes missing; GOOD selected-signal skew >2s
becomes SUSPECT by default. Both limits are configurable and saved with raw samples,
per-signal timestamps and alignment metadata in the job/measurement history.
Unknown/future samples do not become boundary inputs.

Replay/offline clocks use the frame's event time. Live mode uses UTC wall time;
age >120s or >5s into the future produces DATA_UNAVAILABLE with no prediction.
Live history also exposes current age/freshness without rewriting persisted states.
Late corrections require a new measurement identity and remain separate snapshots;
`source_metadata` can identify the observation superseded. Out-of-order events do
not advance or clear the alarm's latest-event counters.

Published revisions are immutable. A subsequent open version starting later can
close its predecessor in a NEW immutable topology timeline. Old timelines, raw
revision payloads and run manifests stay unchanged. Published replay manifests
freeze the complete timeline/network versions; snapshots select exactly one
half-open interval by event time. Gaps give PARAMETERS_UNAVAILABLE. Same-start
overlaps and overlapping finite publications are rejected. Explicit draft studies
use the draft's own interval. Draft save inserts a new revision rather than
mutating the previous one.

Raw predictions, raw residuals, observations, quality, sigmas and outcomes are
distinct fields. Power-loss uncertainty is sqrt(sigma_send² + sigma_recv² -
2*rho*sigma_send*sigma_recv). Default rho=0; provide `power_error_correlation` in
mapping/source metadata when supported by meter evidence. It is measurement
uncertainty only, not total model uncertainty.

CSV is UTF-8. Mapping supports delimiter, Python strptime or ISO timestamps,
declared timezone, column names, scale/offset, CT/PT multipliers, terminal sign,
quality columns/maps, missing sentinels, sigmas and connection-state maps. The
wizard exposes common settings; advanced quality/state maps are supplied by its
mapping JSON file. Canonical units remain visible in charts and exports.

Imports are limited to 8MB/10,000 rows; pending jobs to 100; history pages to 1,000
states. SQL aggregates calculate channel counts/bias/MAE/RMSE. Exact voltage p95
is available up to 10,000 usable samples and explicitly unavailable above that
bound. HTML figures show the first 1,000 states and preserve missing-value gaps.
Exports stream database pages. Large-file streaming import, time-bucket chart
aggregation and large-history percentile calculation are not implemented.
