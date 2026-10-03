# ADR 001: persistent modular monolith (2026-10-03)

Accepted before application edits. Preserve the supplied archive unchanged under
`reference/transmission_line_twin_reference`. Reuse its physics, contracts,
alignment, calibration, and research exercises. Reproduce its tests first.

The application is `grid_twin`: a FastAPI API, SQLAlchemy repository with Alembic
migrations, pure component contracts, a pandapower adapter, and a separate bounded
worker. React/TypeScript/Vite, React Flow and Recharts provide the browser UI.
SQLite is the offline development database; PostgreSQL is the Compose database.
Run manifests freeze topology, component parameters and dependency identities.
Published revisions are insert-only; drafts never mutate completed studies.

The component registry loads reviewed installed classes, never uploaded code.
Each component contributes to one shared network. Balanced AC islands require
exactly one external reference per island. PQ generators have fixed injections;
PV controls, multiple slacks and dynamic reactive limits are unsupported.
Organizational relationships and screen positions do not create electrical edges.

Worker jobs have durable checkpoint, ownership and lease fields. Each frame and
its state/outbox/alarm update commit in one transaction. Replay uses event time;
live processing uses current UTC. Duplicate content is idempotent; conflicting
content is quarantined. No physical command interfaces exist.

Password hashes use Argon2 and sessions use expiring opaque random tokens stored
only by hash. Roles and project membership are enforced in every data endpoint.
The local application serves the built frontend and API from one origin.

The supplied references are engineering guidance, not field validation. All demo
parameters, observations and thresholds remain visibly synthetic. Runtime gates
that cannot be exercised will be labelled NOT RUN, with reproducible commands.
