# Component developer guide

The transport-independent contracts are in `src/grid_twin/domain.py`. A reviewed
plugin declares a stable type ID, plugin version, platform compatibility range,
Pydantic parameter schema (bounds, engineering units and provenance), named
electrical terminals, capabilities, contribution and result extraction. Optional
pure snapshot/analytics hooks are on `BasePlugin`. The registry rejects unknown
and incompatible plugins. The network preflight rejects an unsupported
in-service component instead of ignoring its physics.

`TransformerPlugin` is the real integration example: two distinct HV/LV terminals,
impedance and no-load parameters, bounded taps and a pandapower transformer
contribution. The shared adapter creates buses first; all components contribute
to the same network before one solve per snapshot. Connected components share a
snapshot ID. Organizational parents and diagram positions create no connections.

`example_plugin.py` supplies `TeachingCapacitorPlugin`. It reuses a fixed-shunt
adapter method without modifying solver dispatch. Its parameters are positive
active absorption and signed reactive MVAr (capacitive values negative). The
installed package advertises the `teaching_capacitor` entry point in group
`grid_twin.components`; it is disabled by default. In reviewed application startup
code, call `enable_reviewed_plugins(["teaching_capacitor"])` in both API and worker.
Missing entry points, duplicate types and incompatible versions fail startup.
Do not load entry points from an upload or arbitrary user string. Install and
review the package, change the explicit allowlist, then deploy matching API/worker
versions. Tests `test_plugin_extension_without_solver_edit` and
`test_installed_approved_example_plugin` exercise this path.

A new family can use an existing adapter contribution method or introduce a
tested adapter method. It must provide independent numerical validation before
advertising study support. Measurement/channel roles, event-time selection,
quality/uncertainty, persistent states, analytics and holdout evidence are needed
before advertising twin support. A schema/symbol alone provides catalog support.

Keep `catalog.*` organizational/measurement assets out of electrical studies
(`in_service=false`) until they have an implemented solver contribution. An asset
may retain organizational metadata and parent relationships without being an
energized electrical element. AC positive-sequence terminals must match their
shared bus voltage/domain/phase interpretation. DC and arbitrary phase networks
are not implemented by this adapter.

Extension checklist: parameter schema and units, terminal contract, capability
manifest, pure validation/update hooks, adapter contribution, state extraction,
independent calculations, topology/island tests, manifest version compatibility,
UI schema usability and examples. No arbitrary Python, expressions, serialized
models or pickle/joblib uploads are accepted by the application.
