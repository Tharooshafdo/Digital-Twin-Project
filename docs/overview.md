# Geographic overview, simulation and operating inspection

The admin landing page is **Overview**. It now has a selectable component map,
total demand in MW, bus voltages in kV, frequency in Hz, observation age/quality,
and two main actions: **Simulate changes** and **Inspect operating data**.
The browser polls the authenticated overview endpoint every five seconds.

## Map configuration

The default coordinate map is local SVG and needs no account, network or key.
It displays latitude/longitude, component locations and their terminal connections.
Coordinates are asset metadata; screen positions and locations do not define
electrical connectivity. The existing synthetic demonstration receives explicitly
illustrative Sri Lanka coordinates, not actual equipment locations.

Engineers/admins can select **Edit locations**, select an asset, enter latitude,
longitude, label and provenance, and save. Changes persist with audit records;
previous electrical revisions remain unchanged. An asset without coordinates is
counted as unlocated and remains accessible in the component selector.
Connections are schematic straight segments, not surveyed line routes.

To enable Google Maps, obtain a browser key with **Maps JavaScript API** enabled
and restrict it to that API and your website's HTTP referrers. This is a client
API key, visible in the browser; do not use a privileged server credential.
Create a map ID for your deployment. `DEMO_MAP_ID` is a teaching/testing fallback.
See Google's [Advanced Markers setup](https://developers.google.com/maps/documentation/javascript/advanced-markers/migration)
and [API security guidance](https://developers.google.com/maps/api-security-best-practices).

In PowerShell at the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\stop.ps1
$env:GOOGLE_MAPS_BROWSER_KEY = 'YOUR_RESTRICTED_BROWSER_KEY'
$env:GOOGLE_MAPS_MAP_ID = 'YOUR_MAP_ID'
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\start.ps1
```

No frontend rebuild is needed for these settings. Keep the variables in the shell
used to start the API. For Compose, add them to the existing `.env` and recreate
`api` without deleting volumes. The Google view uses advanced markers and terminal
connection polylines. Missing keys keep Google disabled; loading/network/authorization
failure falls back to the coordinate map with a visible message.
**Actual Google Maps service execution is NOT RUN: no key was supplied.**

## Operating information and actual-source integration

**Synthetic demo** is an explicitly labeled source. The separate worker solves
the current published connected demonstration approximately every five seconds,
with deterministic varying PQ demand. It records the solved bus voltages and
system demand. Its frequency is an illustrative signal around nominal frequency;
steady-state power flow does not estimate actual system frequency.
Set `GRID_TWIN_DEMO_TELEMETRY=0` in the worker environment to disable this producer.
Only project `demo` receives automatic synthetic observations. Its automatic
source retains the latest 720 frames (about one hour); other source records are
retained. This is deliberately separate from frozen historical line replay.

**Live field source** reads field observations only and never substitutes demo or
model values. No actual utility source has been provided/connected. Until one is
connected, values display **Unavailable / NO_SOURCE**. Incoming data are read-only;
the platform offers no equipment-command endpoint.

An authorized source can push aligned grid-level observations:

```http
POST /api/projects/{project_id}/grid-observations
Authorization: Bearer <engineer-or-admin-session-token>
Content-Type: application/json

{
  "snapshot_id": "gateway-unique-snapshot-001",
  "revision_id": "<published_revision_effective_at_event_time>",
  "event_time": "<current_timestamp_with_explicit_timezone>",
  "source_id": "approved.readonly.gateway",
  "data_origin": "field",
  "frequency_hz": {"value": 49.98, "quality": "GOOD"},
  "total_demand_mw": {"value": 68.25, "quality": "GOOD"},
  "bus_voltages_kv": [
    {"asset_id": "BUS_A", "value": 132.1, "quality": "GOOD"},
    {"asset_id": "BUS_D", "value": 32.2, "quality": "GOOD"}
  ]
}
```

These numbers are example payload values, not field evidence. All channels belong
to the same aligned source snapshot. The source must supply a system demand
measurement/aggregate counted once per demand meter; the platform does not add
receiving line powers together. Source alignment/CT/PT/unit transformations should
be performed and validated by the read-only adapter before this endpoint.
Dedicated utility/vendor/PMU adapters remain unimplemented.

The current overview API is `GET /api/projects/{id}/overview?mode=live` (or `demo`).
API clients can select a source with `&source_id=...`; the current browser selects
the latest snapshot within the chosen origin and shows its source ID. It never
mixes channels from different source snapshots. More than 120 seconds old or five
seconds into the future makes current values unavailable. BAD/SUSPECT/MISSING
channels remain unavailable; a newer BAD sample does not fall back to older GOOD.
GOOD zero voltage is retained. A revision mismatch is shown as unavailable.
Identical source/snapshot delivery is idempotent; changed content under the same
identity is rejected. Original readings/quality/event and receipt times remain
in the stored snapshot. Project roles protect reads and writes.

**Inspect operating data** presents the selected source, bus voltage/quality table,
map and asset inspector. It also provides **Recorded history**, where the user
selects a persistent replay run and opens its detailed line charts. Historical
observations are not presented as current live readings.

## Simulation before publication

**Simulate changes** starts with the current published model. Change the PQ demand
multiplier, sending-source voltage, equipment in-service state or transformer tap.
**Run simulation** queues baseline and candidate connected solves through the
real worker. The comparison presents demand, losses and bus voltage differences;
unserved islands/domain/solver errors are failed studies, never successful previews.
The overview's varying demo demand does not silently alter this frozen baseline.

Changing any candidate setting after a solve disables applying that result.
**Apply to platform model** is administrator-only and publishes the exact stored,
successfully solved candidate as a new effective revision with audit lineage.
The server rechecks the candidate digest and current published baseline. If the
baseline has changed, rerun against the current model. Applying twice returns the
same revision; it does not create duplicate publications. Old runs/manifests and
timeline versions remain unchanged. Publication changes the software model and
does not switch or command physical equipment.

## Executed evidence

`tests/test_overview.py` covers source separation, freshness/quality, zero voltage,
identities, coordinates, role/project access, populated upgrade, legacy published
baseline discovery, successful/failed simulation and stale-baseline publication.
`tools/overview_browser_check.py` uses the actual API/worker/SQLite and applies its
candidate only in a newly named qualification project. It checks automatic demo
cadence, map selection, saved location reload, changed-tap/demand simulation,
candidate invalidation, audited publication and recorded/field inspection.
Evidence: `docs/evidence/overview-tests.xml`, `overview-browser-checks.json`,
`overview.png`, `simulation.png`, `inspection.png`. A valid-key Google Maps view and
real utility telemetry have not been exercised.
`tools/map_fallback_check.py` runs an actual isolated API against a SQLite copy
and deliberately blocks the Maps script before network delivery. It verifies the
visible failure message, usable fallback markers and absence of JS runtime errors;
`docs/evidence/map-fallback.json` records that result. This is a failure-path check,
not proof of Google service authorization or rendering.
