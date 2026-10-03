# Capability matrix — Release 0.1

This is a runnable local research release. Support does not imply utility field
accuracy. **Implemented/tested** means executed against real local SQLite/API/
worker or numerical calculations. **Implemented/NOT RUN** identifies a runtime
qualification gate absent on this host. **Deferred** is not a completed feature.

| Capability | Status | Evidence / precise boundary |
|---|---|---|
| Reference reuse and pinned scientific core | Implemented/tested | Original 30-test baseline; full application regression XML; byte comparison of 48 original files |
| React/TypeScript browser + FastAPI + separate worker | Implemented/tested | Production build, real Chromium checks, local startup logs |
| SQLite persistent platform and Alembic | Implemented/tested | Populated upgrade, UTC round trips, native schema versions 0001–0005 |
| PostgreSQL JSONB/native timestamps and Compose deployment | Implemented/NOT RUN | Migrations/config supplied; YAML parsed only; Docker absent |
| Asset registry and versioned component manifests | Implemented/tested | Domain/plugin/API tests; catalog/UI forms |
| Shared positive-sequence AC buses/terminals/network | Implemented/tested | Connected balance, terminal compatibility, duplicate ID/island/reference tests |
| Lines: balanced pi and independent ABCD | Implemented/tested | Synthetic 132.1 kV regression; forward/reverse/zero flow; conservation |
| Full circuits versus conductor bundle metadata | Implemented/tested | Reference parallel/temperature/loading tests; bundle count does not multiply circuit admittance |
| Overhead/cable electrical sections | Implemented/tested | Cascaded ABCD vs pandapower tests, connected section balances, UI section form |
| Measured conductor temperature resistance | Implemented/tested | Reference correction, once-only isolated correction; connected temperature snapshot adapter is deferred |
| Two-winding transformer and fixed taps | Study support, tested | Real plugin and tap/voltage tests; no transformer condition twin |
| External grid, PQ loads, PQ generation, fixed shunts | Study support, tested | Shared solver, extension/shunt test and connected conservation |
| Simulated bus coupler/switch topology | Implemented/tested | Open island and closed-coupler tests; no physical switching |
| Sources/control policy | Implemented/tested, limited | Exactly one external reference per supplied island; fixed PQ generators; PV/Q-limit/OPF and multiple references rejected/deferred |
| Future equipment families | Catalog only | Battery, renewable-specific equipment, relays, PMU, CT/PT, auxiliary assets etc. Unsupported in-service models cause preflight error |
| Immutable drafts/publications/effective timelines | Implemented/tested | Later publication creates new half-open timeline; old run manifests remain unchanged; gaps/overlaps checked |
| Aligned CSV wizard and raw manifests/rejects | Implemented/tested | Real browser/API imports; UTF-8 only; 8MB/10,000-row bound; advanced quality/state maps through JSON mapping |
| Separately arriving signals, as-of/age/skew gates | Implemented/tested API | Raw sample lists and per-signal time metadata persisted; newest BAD retained; no live signal subscription UI |
| Durable historical replay controls | Implemented/tested | Checkpoint, pause/resume/cancel/retry/speed tests; real 288-state browser run |
| Live UTC freshness and late corrections | Implemented/tested synthetic | >120s old / >5s future yields unavailable; ordered alarm state; no approved utility adapter |
| MQTT durable commit/manual ACK/dead letters | Implemented; broker NOT RUN | Synthetic delivery, conflict, bounded-inbox and outbox lease tests; actual Mosquitto redelivery/interruption not executed |
| Transactional worker ownership and outbox | Implemented/tested SQLite | Ownership races, expired leases, checkpoint recreation and outbox resend tests; PostgreSQL concurrency unexecuted |
| Line dashboard, independent residuals, history/units | Implemented/tested | Real historical charts and data; browser screenshots; unavailable values remain gaps |
| Validation errors/regimes/uncertainty | Implemented/tested | Bias/MAE/RMSE/counts SQL aggregation, bounded exact voltage p95, regime chart, correlated meter-loss uncertainty |
| Calibration/chronological holdout candidates | Implemented/tested | API → worker → persisted candidate; frozen threshold, no automatic publication; no actual-line identifiability claim |
| Scenarios and baseline comparison | Implemented/tested | Separate connected solves and immutable linked reports; browser comparison |
| Residual hysteresis/quality/acknowledgement | Implemented/tested | Consecutive counter, missing/late/duplicate gates, policy versions and audit |
| Human-readable HTML figures and complete CSV | Implemented/tested | Real browser downloads; inputs/assumptions/versions/failures/limits; HTML figures bounded at 1,000 states |
| State estimation research | Integrated/tested | Reference synthetic WLS fixture, roles/sigmas/convergence; no general observability analysis or actual PMU estimator |
| Thermal/TDPF research | Integrated/tested | Initial 35°C, final temperature and 600s retained; teaching heat model; no certified IEEE 738 rating |
| Known-tension catenary sag | Integrated/tested | Positive geometry/tension inputs; clearance explicitly unavailable |
| Three-phase steady-state/fault research | Integrated/tested fixtures | Sequence/source data from synthetic fixture; IEC 60909-style fault outputs; no EMT/waveforms/relay operation |
| Optional ML residual/15-minute forecast | Reference-only/tested | Preserved CLI experiments with chronological/purged splits and guards; application training/promotion/inference path deferred |
| Local Argon2 authentication/project roles | Implemented/tested | Viewer/engineer/admin, exports/publication/project restrictions and persistent sessions |
| Organizational identity/TLS shared deployment | Deferred integration | Reverse-proxy boundary documented; no OIDC/SAML/MFA/password-reset/shared limiter implementation |
| Diagnostics and measured 1/10/100 workloads | Implemented/measured | Hardware, timing, throughput, backlog and payload evidence; no sustained production/HA claim |
| SQLite backups/isolated restore | Implemented/tested | Backup API, restored counts/manifests; safe new paths only |
| Windows service recreation | Runtime check | `runtime-recovery.json` is the authority for executed outcome; leases may delay crash recovery up to 300s |
| PostgreSQL restore/broker/DB service interruption | NOT RUN | Exact named-environment commands in operations/README; Docker runtime absent |
| Opt-in state retention archives | Implemented/tested | Dry run, checksum/count verification, audit/report lineage; active/unpublished streams excluded |
| Large-history/time-bucket analytics and raw-data lifecycle | Deferred | Page limits/aggregates work; >10k p95, streaming large-file imports, chart time bucketing and archive reconstruction UI not implemented |
| Physical commands, utility gateways and field accuracy | Requires approved field work | No equipment-command endpoints; no utility credentials, records or independent field holdout supplied |

## Milestone accounting

1. Reference numerical baseline reproduced; originals preserved.
2. Persistent foundation, migrations, plugins, project permissions and shared solver
   implemented and exercised on SQLite. PostgreSQL execution remains pending.
3. Frontend network create/save/reload and invalid-edge rejection exercised against
   the real API, including the transformer plugin.
4. Isolated line physics, measurement roles, uncertainty/time/quality/topology gates
   and sectioned electrical calculations implemented and tested.
5. Local CSV/replay/persistence/dashboard/alerts/report workflows exercised. MQTT
   code paths are tested synthetically; real broker qualification is pending.
6. Declared research studies, calibration and scenarios have complete persisted
   paths and tests. Optional ML application integration is deferred.
7. Local build/auth/migration/SQLite recovery/workload checks executed. Container,
   PostgreSQL, broker recovery and Linux runtime remain NOT RUN. This milestone
   is not fully qualified for a shared service deployment.

## Engineering extension roadmap

Require separate evidence gates for transformer condition/thermal analytics;
PV/wind/hydro/diesel equipment dynamics; battery converter/energy/SOC evolution;
unbalanced connected networks and observability; cable thermal models; surveyed
sag/clearance and validated tension relationships; HVDC/power-electronic solvers;
waveform/protection/EMT studies; and authorized read-only vendor gateways.
Each progresses from catalog to specified study support, then to validated twin
support. Training and parameter candidates require explicit audited review; raw
physics discrepancy alarms remain independent of optional corrections.
