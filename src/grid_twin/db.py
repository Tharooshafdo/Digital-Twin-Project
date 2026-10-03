"""Application persistence. Schema is created/upgraded only through Alembic."""
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import (create_engine, event, MetaData, Table, Column, String,
                        Integer, Float, DateTime, JSON, Text, ForeignKey, UniqueConstraint, Index)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import TypeDecorator

metadata = MetaData()
J = JSON().with_variant(JSONB(), "postgresql")
class UTCDateTime(TypeDecorator):
    impl = DateTime
    cache_ok = True
    def __init__(self):
        super().__init__(timezone=True)
    def process_bind_param(self,value,dialect):
        if value is not None:
            if value.tzinfo is None:
                raise ValueError("UTC storage requires aware timestamps")
            return value.astimezone(timezone.utc)
    def process_result_value(self,value,dialect):
        if value is not None:
            return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
T = UTCDateTime()
def now():
    return datetime.now(timezone.utc)
def utc_time(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("Explicit timezone required")
    return value.astimezone(timezone.utc)
def iso(value):
    return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)).isoformat()
def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()
def uid(prefix):
    import uuid
    return prefix + "_" + uuid.uuid4().hex

projects = Table("projects", metadata, Column("id", String(80), primary_key=True),
    Column("name", String(200), nullable=False), Column("created_at", T, nullable=False))
users = Table("users", metadata, Column("id", String(80), primary_key=True),
    Column("username", String(80), nullable=False, unique=True), Column("password_hash", Text, nullable=False),
    Column("role", String(20), nullable=False), Column("created_at", T, nullable=False))
memberships = Table("memberships", metadata, Column("user_id", ForeignKey("users.id"), primary_key=True),
    Column("project_id", ForeignKey("projects.id"), primary_key=True))
sessions = Table("sessions", metadata, Column("token_hash", String(64), primary_key=True),
    Column("user_id", ForeignKey("users.id"), nullable=False), Column("expires_at", T, nullable=False))
revisions = Table("topology_revisions", metadata, Column("id", String(80), primary_key=True),
    Column("project_id", ForeignKey("projects.id"), nullable=False), Column("name", String(200), nullable=False),
    Column("status", String(20), nullable=False), Column("payload", J, nullable=False),
    Column("payload_hash", String(64), nullable=False), Column("created_at", T, nullable=False),
    Column("valid_from", T, nullable=False), Column("valid_to", T), Column("parent_id", String(80)))
Index("ix_revision_project_interval", revisions.c.project_id, revisions.c.status, revisions.c.valid_from)
runs = Table("runs", metadata, Column("id", String(80), primary_key=True),
    Column("project_id", ForeignKey("projects.id"), nullable=False), Column("kind", String(30), nullable=False),
    Column("mode", String(20), nullable=False), Column("manifest", J, nullable=False),
    Column("created_at", T, nullable=False))
imports = Table("raw_imports", metadata, Column("id", String(80), primary_key=True),
    Column("project_id", ForeignKey("projects.id"), nullable=False), Column("filename", String(200), nullable=False),
    Column("checksum", String(64), nullable=False), Column("raw_text", Text, nullable=False),
    Column("mapping", J, nullable=False), Column("manifest", J, nullable=False),
    Column("rejects", J, nullable=False), Column("created_at", T, nullable=False))
measurements = Table("measurements", metadata, Column("id", String(240), primary_key=True),
    Column("project_id", ForeignKey("projects.id"), nullable=False), Column("message_id", String(128), nullable=False),
    Column("asset_id", String(80), nullable=False), Column("event_time", T, nullable=False),
    Column("received_at", T, nullable=False), Column("payload_hash", String(64), nullable=False),
    Column("payload", J, nullable=False), Column("natural_key", String(64), nullable=False),
    UniqueConstraint("project_id", "message_id", name="uq_measurement_identity"),
    UniqueConstraint("project_id", "natural_key", name="uq_measurement_source_identity"))
Index("ix_measurement_asset_time", measurements.c.project_id, measurements.c.asset_id, measurements.c.event_time)
states = Table("component_states", metadata, Column("id", String(180), primary_key=True),
    Column("run_id", ForeignKey("runs.id"), nullable=False), Column("message_id", String(128), nullable=False),
    Column("asset_id", String(80), nullable=False), Column("event_time", T, nullable=False),
    Column("processed_at", T, nullable=False), Column("status", String(40), nullable=False),
    Column("voltage_residual", Float), Column("payload", J, nullable=False),
    UniqueConstraint("run_id", "message_id", name="uq_state_identity"))
Index("ix_state_run_time", states.c.run_id, states.c.asset_id, states.c.event_time)
jobs = Table("jobs", metadata, Column("id", String(80), primary_key=True),
    Column("project_id", ForeignKey("projects.id"), nullable=False), Column("run_id", ForeignKey("runs.id"), nullable=False),
    Column("kind", String(30), nullable=False), Column("status", String(20), nullable=False),
    Column("payload", J, nullable=False), Column("checkpoint", Integer, nullable=False, default=0),
    Column("total", Integer, nullable=False), Column("owner", String(80)), Column("lease_until", Float),
    Column("attempts", Integer, nullable=False, default=0), Column("error", Text),
    Column("speed", Float, nullable=False, default=600), Column("next_due", Float, nullable=False, default=0),
    Column("created_at", T, nullable=False), Column("updated_at", T, nullable=False))
Index("ix_job_claim", jobs.c.status, jobs.c.lease_until, jobs.c.next_due)
outbox = Table("outbox", metadata, Column("id", String(180), primary_key=True),
    Column("project_id", ForeignKey("projects.id"), nullable=False), Column("topic", String(240), nullable=False),
    Column("payload", J, nullable=False), Column("owner", String(80)), Column("lease_until", Float),
    Column("published_at", T), Column("attempts", Integer, nullable=False, default=0))
alarms = Table("alarms", metadata, Column("id", String(180), primary_key=True),
    Column("project_id", ForeignKey("projects.id"), nullable=False), Column("run_id", ForeignKey("runs.id"), nullable=False),
    Column("asset_id", String(80), nullable=False), Column("active", Integer, nullable=False),
    Column("count", Integer, nullable=False), Column("last_event_time", T),
    Column("acknowledged_by", String(80)), Column("payload", J, nullable=False))
dead_letters = Table("dead_letters", metadata, Column("id", String(80), primary_key=True),
    Column("project_id", String(80)), Column("created_at", T, nullable=False),
    Column("reason", Text, nullable=False), Column("raw", Text, nullable=False))
audit = Table("audit_events", metadata, Column("id", String(80), primary_key=True),
    Column("project_id", String(80)), Column("actor", String(80), nullable=False),
    Column("action", String(80), nullable=False), Column("created_at", T, nullable=False), Column("payload", J, nullable=False))
# Dedicated version/artifact entities use immutable JSON contracts. Empty tables
# do not imply implemented model-artifact promotion or retention workflows.
entities = {}
for name in ("asset_types", "assets", "terminals", "parameter_versions", "data_sources", "signal_mappings",
             "snapshots", "validation_reports", "model_artifacts", "topology_timelines", "alarm_policy_versions"):
    entities[name] = Table(name, metadata, Column("id", String(180), primary_key=True),
        Column("project_id", ForeignKey("projects.id")), Column("version", String(80), nullable=False),
        Column("created_at", T, nullable=False), Column("payload", J, nullable=False))

def engine_for(url=None):
    url = url or os.getenv("DATABASE_URL", "sqlite:///data/platform.db")
    if url.startswith("sqlite:///"):
        file = url.removeprefix("sqlite:///")
        if file != ":memory:":
            Path(file).parent.mkdir(parents=True, exist_ok=True)
    options = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        options["connect_args"] = {"check_same_thread": False, "timeout": 30}
    engine = create_engine(url, **options)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def sqlite_settings(conn, _):
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA journal_mode=WAL")
    return engine

def audit_event(conn, actor, action, project_id=None, payload=None):
    conn.execute(audit.insert().values(id=uid("audit"), project_id=project_id,
        actor=actor, action=action, created_at=now(), payload=payload or {}))

def migrate(url=None):
    from alembic.config import Config
    from alembic import command
    cfg = Config(str(Path(os.getenv("GRID_TWIN_ROOT", str(Path.cwd()))).resolve() / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", (url or os.getenv("DATABASE_URL", "sqlite:///data/platform.db")).replace("%", "%%"))
    command.upgrade(cfg, "head")
