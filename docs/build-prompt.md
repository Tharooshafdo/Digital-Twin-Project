# Codex prompt for an extensible power system digital twin

Use this prompt in Codex with the corrected handbook and reference project available in the workspace. The requested deliverable is working software. The handbook is a transmission-line implementation reference; it does not certify field accuracy or provide every future component model.

---

You are the lead software engineer and power-system modelling engineer for this project. Build a practical, maintainable power-system digital-twin application for an Electrical and Information Engineering university project in Sri Lanka.

The long-term objective is a platform that can represent and progressively add generation, transmission, substations, distribution, renewable generation, storage, loads, instrumentation and protection assets. The first completed release must deliver the reusable platform foundation and a working transmission-line twin. Implement the software, run it, test it and document it. Do not stop after producing an architecture document, scaffold, UI mockup or collection of TODOs.

## 1 Read the inputs and preserve the validated starting point

Locate these supplied files:

- `Transmission_Line_Twin_Implementation_Handbook_v2.docx`
- `Transmission_Line_Twin_Reference_Project_v2.zip`, or its extracted `transmission_line_twin_reference` directory.

Read the handbook, `README.md`, `VERIFICATION.md`, source files, configuration files and tests. Extract the archive safely if necessary. Respect any applicable repository instructions and preserve unrelated work. Inspect the existing project before deciding whether to extend it in place or reorganize it into a monorepo. Reuse its numerical core, data contracts, replay logic and meaningful tests where suitable. Keep a traceable comparison with the original reference implementation.

The reference reports 30 passing Python tests, but its complete Docker/MQTT/PostgreSQL/Grafana deployment was not executed during authoring. Treat that as prior evidence to reproduce, not proof that the new application works. Run the original suite before refactoring when the environment permits. Do not silently fix failing scientific checks by weakening tolerances.

Use the handbook as the baseline. Resolve an error against independent calculations and official documentation, then document the correction. If inputs are missing, proceed with explicitly labelled synthetic demo assets and record the assumptions. Never invent utility parameters, credentials, approval, measurements or field validation. Ask only for information that actually blocks the next dependent step; continue independent implementation work.

## 2 Deliverable and implementation scope

Build a browser application with a Python backend, persistent storage, an asset registry, an editable single-line network model, historical-data import, replay, numerical studies, visualizations, reports and diagnostics. It must run locally on a Windows development computer and through Docker Compose. Document an equivalent Linux setup.

Start with a modular monolith plus a separate background worker. Keep clear interfaces so ingestion, solving and analytics can be separated into services later. Do not introduce Kubernetes or a large distributed stack without a measured need.

Preferred stack:

- Python 3.12, FastAPI, Pydantic, pandapower and the scientific libraries used by the reference.
- SQLAlchemy with Alembic migrations; PostgreSQL for the service deployment. Retain SQLite for a small offline mode only if doing so remains straightforward and tested.
- React, TypeScript and Vite for the application; React Flow for the single-line editor and a maintained open-source chart library for scientific time series.
- Mosquitto and Paho MQTT for replay and simulated streaming, reusing and strengthening the reference's delivery behaviour.
- Docker Compose for the local service stack. Grafana may remain an optional operational dashboard; the main application must provide its own usable workflows.
- pytest for backend/numerical checks and Playwright or an equivalent browser test framework for critical user journeys.

Preserve the reference's pinned scientific dependencies initially. Verify compatibility before changing them. Choose compatible frontend and migration-tool versions, commit lock files, document licenses and provide repeatable installation. Use official documentation for APIs; do not guess supported solver features. Core functionality must not require paid services, proprietary software or cloud access.

## 3 Extensible components with honest capability reporting

Separate three levels of support:

1. **Catalog support:** the platform can store an asset and its metadata.
2. **Study support:** an implemented model can participate in specified calculations.
3. **Twin support:** the model has measurement mapping, time handling, persistent state, independent validation and applicable analytics.

Registering a JSON schema or displaying a diagram symbol does not implement a component's physics. Expose support levels in the UI and documentation. An unsupported in-service component must produce an explicit preflight error for a study that requires its model; never silently ignore it or substitute fabricated results.

Provide a versioned component-plugin interface with:

- Stable type ID, plugin version, compatible platform versions and capability manifest.
- Parameter schemas with units, required fields, bounds and provenance.
- Typed electrical terminals: AC/DC domain, voltage level and phase interpretation. Keep physical connectivity separate from organizational parent/child relationships and diagram positions.
- Measurement-channel definitions, adapter mappings and quality/uncertainty metadata.
- Validation, contribution to a shared solver network, snapshot updates and extraction of solved component states.
- Optional thermal, mechanical, forecasting or condition-analysis hooks.
- UI form schema, diagram symbol, result fields and corresponding tests.

Keep domain models independent of FastAPI, MQTT, PostgreSQL and React. Use a solver-adapter layer; components contribute elements to a network rather than independently solving each adjacent branch. Enable reviewed plugins through a controlled installed-package registry. Do not execute arbitrary uploaded Python, expressions or serialized models.

The component catalog must be extensible for these families:

| Family | Examples | Release scope |
| --- | --- | --- |
| Network structure | Buses, busbars, substations, feeders, connectivity terminals | Working platform and basic AC topology |
| Transmission and distribution | Overhead lines, cable sections, parallel circuits, line reactors | Complete balanced line twin; overhead/cable electrical metadata; separate future cable thermal model |
| Voltage transformation | Two- and three-winding transformers, tap changers | Working two-winding steady-state model for connected demonstrations; advanced transformer twin later |
| Switching | Breakers, disconnectors, bus couplers | Working simulated topology changes; no physical switching commands |
| Sources and generation | External grid, synchronous generation, PV, wind, hydro, diesel | Working external-grid and basic PQ generation model; equipment-specific dynamics later |
| Demand | Constant PQ loads, motors, ZIP and phase loads | Working PQ load model; additional formulations advertised only when implemented |
| Reactive and power-electronic assets | Capacitor banks, shunts, reactors, SVC, STATCOM, HVDC and converters | Working simple shunt model; specialized models added through declared solver capabilities |
| Storage | Batteries, storage converters and state of charge | Catalog/schema support initially; time-dependent energy and converter models later |
| Measurement and protection | Meters, CT/PT, PMU, IED, relays, weather sensors | Measurement mapping and metadata now; protection/waveform models later |
| Mechanical and auxiliary assets | Towers, spans, conductors, insulators, earthing, arresters | Asset relationships and optional line-analysis inputs; individual condition models later |

This list is an extensibility target, not a claim to model every power-system device in Release 1. Provide a developer guide and a tested example showing how to add a component without editing a central chain of component-type conditionals. Use the real two-winding-transformer plugin as an integration proof alongside the line plugin.

## 4 Shared network and time coordinator

Maintain one shared bus/terminal registry and immutable topology revisions. Validate terminal compatibility, duplicate IDs, switch states, voltage transitions and references. Diagram edges must map to real terminals; screen coordinates must not determine electrical connectivity. Editing a draft topology must not alter a previous run.

Offer two explicitly different study modes:

- **Isolated line:** sending voltage and selected receiving-branch P/Q are boundary inputs.
- **Connected network:** source references, bus injections, generators, loads, taps and topology define one network solve. Receiving branch P/Q becomes a result or an estimator observation rather than a duplicate load at every line end.

Do not add a station demand repeatedly at adjacent branches. Do not impose each isolated line's sending voltage as a new internal slack source. Solve connected components with consistent shared bus voltages and one documented reference/slack policy per supplied island. Detect unsupplied islands and produce unavailable outcomes. Multiple sources, reactive limits and controls must have an explicit validated policy.

For each snapshot, choose inputs by event time and an as-of rule, preserve per-signal timestamps, apply age/skew/quality gates, freeze topology and parameters, then solve. All component results reference the same snapshot ID. Historical replay uses a shared event clock; live mode uses current UTC freshness and a bounded lateness policy. Preserve late corrections as new snapshot revisions instead of rewriting scientific history.

## 5 Persistent data and reproducibility

Design database entities for projects, asset types/plugins, assets, terminals, topology revisions, parameter versions, data sources, signal mappings, raw-import manifests, normalized measurements, runs, snapshots, component states, validation reports, jobs, model artifacts, audit events, alarms and transactional outbox records.

Include stable asset IDs and separate schema, adapter, parameter, topology, physics, plugin and ML model versions. Record event, receipt and processing times, clock mode, dataset/source identities, deterministic message IDs, data origin and run manifests. Use timezone-aware UTC storage; allow `Asia/Colombo` display and preserve the original timestamp and declared source timezone. Prefer native PostgreSQL timestamps and JSONB where appropriate, with deliberate indexes and constraints.

Parameter/topology changes create new versions with half-open validity intervals. Reject gaps or overlaps where a snapshot requires exactly one applicable version. Published versions and run manifests are immutable. Support draft editing and explicit version publication, with audit history; an existing run must remain reproducible after later edits.

Separate measured values, input/estimation roles, raw predictions, corrected predictions, residuals, uncertainties and status. Preserve BAD, SUSPECT, MISSING, stale and future data. Missing readings are not zero; valid zero voltage during a deenergized state is retained. Duplicate delivery must not create duplicate states; a reused identity with changed content must be rejected and recorded.

Introduce Alembic migrations from the first application schema. Test upgrade against populated data. `create_all` is not an upgrade strategy. Provide paginated history and server-side aggregation instead of loading unlimited records into the browser.

## 6 Transmission-line twin required for Release 1

Implement these features end to end through the UI, API, worker and storage:

### Asset and electrical model

- Create/edit/version a line with terminals, nominal voltage, length, positive-sequence R/X/C/G, frequency, full-circuit count, conductor bundle metadata, current rating/source, derating, reference temperature and topology state.
- Support sectioned assets and distinguish overhead/cable electrical sections. Do not reuse overhead thermal ratings for cables.
- Complete balanced nominal-pi pandapower model with sending source, receiving branch-load equivalent, in-service handling and convergence checks.
- Independent ABCD verification: `A = D = 1 + YZ/2`, `B = Z`, `C = Y(1 + YZ/4)`.
- Inputs: sending line-to-line RMS kV and receiving total three-phase MW/MVAr leaving the line. Outputs: receiving voltage/angle, both terminal currents, sending P/Q, active loss, net reactive absorption and loading.
- Keep receiving voltage and other independent validation targets out of the boundary-input calculation. Transform pandapower branch-end signs explicitly. Reverse flow must not swap terminal identities. Charging can make net reactive absorption negative.
- Distinguish full parallel circuits from subconductors. State rating conventions and parameter units explicitly.
- Handle receiving-open charging, deenergization, inactive assets, unknown/conflicting topology, bad boundary inputs, future/stale data and solver/domain failures. Never label unavailable results healthy or publish the last successful value as a fresh prediction.
- Provide optional measured-conductor-temperature resistance correction with documented alpha and reference temperature; do not substitute ambient temperature or apply the correction twice.

### Data ingestion and replay

- CSV import wizard: preview, delimiter/date-format configuration, timezone, terminal directions, unit/CT/PT scaling, quality mapping, missing sentinels, uncertainty and connection-state mapping.
- Retain original files/checksums, mapping versions, normalized frames, rejection reasons and counts. Do not hide invalid rows.
- Import aligned snapshots and support assembling separately arriving signals using documented as-of selection. Do not replace a recent BAD sample with an older GOOD sample to conceal the bad observation.
- Synthetic demo generation, replay speed control, pause/resume/cancel, durable checkpoints and distinct demo/historical/live indicators.
- MQTT simulated streaming with scoped identities/topics, QoS 1 duplicate handling, manual acknowledgement after durable commit, dead-letter recording, retries and a transactional state outbox.
- Bound queues and implement a tested overload/restart strategy. Preserve unacknowledged delivery and report backlog/age; do not claim lossless delivery merely because QoS 1 is used.
- Reconcile expected message identities against committed measurements/states. Broker acknowledgement is not evidence that the numerical result was committed.

### Validation, studies and presentation

- Line detail dashboard with measured versus predicted time series, raw residuals, loading, loss, terminal quantities, quality, model status, data age and parameter/topology versions.
- Bias, MAE, RMSE, high-percentile error, usable/excluded counts and regime plots, with explicit independent observation roles.
- Measured loss only when both terminal powers are usable; propagate the stated meter uncertainty and account for correlated errors where supplied.
- A chronological calibration/holdout workflow with parameter-fit candidate reports. Never auto-publish fitted parameters or tune acceptance criteria after seeing the holdout.
- What-if studies run against isolated scenario versions and produce linked comparison reports. Scenario changes never operate physical equipment.
- A connected demo containing at least two lines, shared buses, a two-winding transformer, loads and an external source, with power-balance and topology checks.
- Configurable residual alarms with persistent hysteresis/consecutive-event state, acknowledgement/audit and separate data-quality conditions. Missing/stale data cannot silently clear an active discrepancy. Replay duplicates and late events must not falsely advance event counters. Treat alarms as discrepancies unless independent evidence supports a physical diagnosis.
- Downloadable measurement/result CSV and a human-readable validation report containing inputs, assumptions, versions, figures, failures and limitations.

### Advanced research tools

Expose the supplied tested advanced examples in a separate Research Studies area, with explicit input requirements and synthetic/reference provenance. Reuse numerical implementations rather than creating invented graphs.

- State-estimation example with measurement roles, sigmas and convergence/observability reporting.
- Thermal heat-balance/TDPF example with retained initial/final temperature and elapsed time. Label the supplied teaching heat model accurately; do not claim certified IEEE 738 ratings.
- Catenary sag from supplied span geometry and horizontal tension. Report clearance unavailable without the required surveyed geometry and validated tension relationship.
- Three-phase and IEC 60909-style short-circuit examples with the required sequence/source data. Do not present them as EMT simulation or validated relay operation.
- Optional residual-learning and 15-minute forecasting experiments with chronological splits, purged future labels, training-only preprocessing, physics/persistence baselines, version/domain guards and empirical interval coverage. Preserve raw physics residual alarms. Training creates candidates; promotion is an explicit audited configuration decision. Do not accept arbitrary pickle/joblib uploads.

Integrate a research tool only when its complete API-to-worker-to-persisted-result path is implemented and tested. Describe deferred work explicitly; a disabled tab is not a completed feature. Operational dynamic ratings, full sag/clearance, cable thermal physics, vendor utility gateways, protection models and equipment dynamics are later engineering extensions with their own validation gates.

## 7 Product workflows and access

Provide useful pages for project overview, component catalog, asset inventory, single-line editor, data sources/imports, runs/replay, line detail, validation/scenarios, research studies, alerts, service diagnostics and configuration/version history.

Use clear engineering units, legends and visible timestamps. Provide loading/empty/error states, accessible controls, readable charts and consistent professional styling. Default demo views to the actual historical demo time range so they are not blank. Distinguish no data, deenergized, disconnected, unsupported and failed states; do not invent numeric values to make a chart look complete.

Implement local application authentication and viewer/engineer/administrator authorization using a maintained approach. Viewer reads, engineer manages permitted studies/configuration drafts and administrator manages accounts/publication. Generate initial credentials and avoid hard-coded passwords. Enforce authorization on the server, including project-scoped access and exports. Audit configuration changes and study/model approvals.

The application can edit its own model and simulation configuration. Its utility telemetry path remains read-only. Include no physical switching, setpoint or relay-command endpoint. Document TLS/reverse-proxy and organizational authentication integration for any later shared deployment.

## 8 Scalability, reliability and upgrades

Run CPU-intensive solves in bounded background processes, not inside an asynchronous HTTP request handler. Persist job states, progress, cancellation intent, retries and errors. Avoid sharing a mutable solver network between concurrent snapshots.

Use transactional job ownership and outbox claim/lease handling if multiple workers are enabled. Partition independent assets by a stable stream/asset key; for a connected network retain one consistent solve per snapshot. Test ownership races and restarts. Introduce caches only with topology/parameter/temperature invalidation tests and numerical equivalence checks.

Provide structured logs and health/readiness endpoints. Measure solve and end-to-end latency, throughput, backlog, rejection/duplicate counts, failed snapshots, data age, database time and disk usage. Add configurable retention/export and document sizing from measured payloads and workload. Do not assert production scale or high availability from the architecture alone.

Benchmark short configurable workloads with 1, 10 and 100 independent assets and small connected networks, recording actual hardware, cadence, run duration, p50/p95/p99 latency and limits. Keep CI checks small; document a larger manual benchmark command. Handle overload explicitly.

Use reproducible builds and a documented upgrade procedure: dependency/plugin compatibility checks, numerical regression and representative holdout comparison, populated-database migration, backup/restore rehearsal and rollback. Retain old manifests/configurations/models. Do not connect a new database major-version image directly to an incompatible existing volume.

## 9 Development milestones and acceptance evidence

Before major edits, write a concise architecture decision record and a requirements-to-test matrix. Then implement in this order, updating actual completion status:

1. Reproduce the reference numerical behaviour and preserve baseline tests.
2. Build the persistent platform foundation, migrations, component registry, API contracts and shared network coordinator.
3. Build the frontend and demonstrate create/save/reload of a valid network, including the real transformer plugin.
4. Complete the isolated transmission-line numerical and measurement-validation workflow.
5. Complete import, replay, streaming, persistence, dashboard, alarm and report workflows.
6. Integrate the declared advanced research tools and scenario studies, maintaining their validation boundaries.
7. Exercise deployment, authentication, recovery, migration and measured workload behaviour; fix defects and finish documentation.

Use these synthetic numerical regression inputs: nominal voltage 132 kV, frequency 50 Hz, length 65 km, R 0.08 ohm/km, X 0.35 ohm/km, C 9 nF/km, G 0, one full circuit, illustrative rating 0.60 kA, sending voltage 132.1 kV, receiving P 66.8 MW and Q 13.5 MVAr. Expected values are approximately:

- Receiving voltage 126.697514 kV.
- Receiving current 310.556265 A and sending current 307.531842 A.
- Sending P 68.292348 MW and Q 16.950410 MVAr.
- Active loss 1.492348 MW and net reactive absorption 3.450410 MVAr.
- Illustrative loading 51.759378 percent.

Require independent ABCD agreement using justified numerical tolerances. These are synthetic software regression targets, not actual-line error tolerances.

Required automated/integration evidence includes forward/reverse/zero-load flow, terminal conservation, parallel circuits, temperature correction, switch/open-end/island cases, quality/time alignment, parameter intervals, immutable history, duplicates/conflicting identities, restart/late ordering, outbox recovery, raw residual independence, auth/project permissions, plugin compatibility, migrations and report lineage.

Browser checks must demonstrate: create line/network, save/reload, reject an invalid connection, import data and review rejects, replay into real persistent storage, view correct units/residuals/status, inspect history, run a scenario and export a report. Verify the backend behaviour behind each UI action; a mocked response is not end-to-end completion.

Exercise broker/worker/database interruption, service recreation without volume deletion, exact-message reconciliation, and restore into an isolated environment when available. Test PostgreSQL and SQLite separately if both are advertised. Keep destructive recovery commands confined to a named test environment.

If Docker, a browser, utility data or another dependency cannot be exercised in the execution environment, mark that check NOT RUN with the reason and exact command for the user. Continue all executable checks. Never report a deployment, integration, field accuracy or throughput result that was not actually measured.

## 10 Final deliverables

Deliver a complete repository with source, frontend, migrations, lock files, Compose configuration, sample mapping/data generation, tests and a clean startup path. Include:

- README with Windows PowerShell and Linux setup; local URLs, generated-credential instructions, seed/demo and reset procedures.
- An executable end-to-end demo and documented commands to start, stop, back up and restore.
- Architecture and component-extension guides, example plugin, API/schema documentation and capability matrix.
- A feature matrix showing implemented/tested, implemented/not-yet-executed, deferred and requires-field-data status, with concrete evidence paths.
- Test/benchmark results and a truthful limitations report.
- A roadmap for transformer condition analytics, renewables/storage dynamics, richer unbalanced networks, cable thermal models, HVDC/power-electronic solvers, waveform/protection studies and authorized vendor adapters.

Keep the product flows understandable for an engineering student; put implementation details in developer documentation. Keep demo and actual utility data visibly separate. Make the initial release a usable transmission-line digital twin on an extensible power-system platform. Do not advertise a completed twin for future equipment until that component's physics, measurements and validation are implemented.

Proceed with the work. Give concise progress updates. Complete each milestone's working behaviour and verification before declaring it done. End with exact startup instructions, demonstrated capabilities and remaining limitations.

---

## Official documentation to check during implementation

- [pandapower component models](https://pandapower.readthedocs.io/en/latest/elements.html)
- [pandapower AC power flow](https://pandapower.readthedocs.io/en/latest/powerflow/ac.html)
- [FastAPI documentation](https://fastapi.tiangolo.com/)
- [React Flow documentation](https://reactflow.dev/learn)
- [Alembic migration tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html)
- [Paho MQTT client documentation](https://eclipse.dev/paho/files/paho.mqtt.python/html/)
- [Docker Compose documentation](https://docs.docker.com/compose/)

Documentation check date for the component, editor and migration references: 2 October 2026. Verify the exact installed versions when implementing.
