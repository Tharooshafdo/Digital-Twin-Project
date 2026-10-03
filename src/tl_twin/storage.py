"""Portable persistence; event strings are canonical UTC for stable ordering."""
import hashlib
import json
from datetime import datetime, timezone
from sqlalchemy import (JSON, Column, Float, Integer, Index, MetaData, String, Table,
                        Text, UniqueConstraint, create_engine, select)
from sqlalchemy.exc import IntegrityError

metadata = MetaData()
runs = Table("runs", metadata,
    Column("run_id", String(128), primary_key=True),
    Column("mode", String(16), nullable=False),
    Column("created_at", String(40), nullable=False),
    Column("manifest", JSON, nullable=False))
parameters = Table("parameters", metadata,
    Column("asset_id", String(128), primary_key=True),
    Column("parameter_version", String(128), primary_key=True),
    Column("payload_hash", String(64), nullable=False),
    Column("payload", JSON, nullable=False))
measurements = Table("measurements", metadata,
    Column("message_id", String(128), primary_key=True),
    Column("dataset_id", String(128), nullable=False),
    Column("source_id", String(128), nullable=False),
    Column("asset_id", String(128), nullable=False, index=True),
    Column("event_time", String(40), nullable=False, index=True),
    Column("sequence_no", Integer, nullable=False),
    Column("received_at", String(40), nullable=False),
    Column("payload_hash", String(64), nullable=False),
    Column("payload", JSON, nullable=False),
    UniqueConstraint("dataset_id", "source_id", "asset_id", "event_time",
                     "sequence_no", name="uq_source_frame"))
states = Table("twin_states", metadata,
    Column("run_id", String(128), primary_key=True),
    Column("message_id", String(128), primary_key=True),
    Column("asset_id", String(128), nullable=False, index=True),
    Column("event_time", String(40), nullable=False, index=True),
    Column("received_at", String(40), nullable=False),
    Column("processed_at", String(40), nullable=False),
    Column("clock_time", String(40), nullable=False),
    Column("dataset_id", String(128), nullable=False),
    Column("parameter_version", String(128)),
    Column("topology_version", String(128)),
    Column("model_version", String(128)),
    Column("model_status", String(32), nullable=False),
    Column("assessment", String(32), nullable=False),
    Column("data_origin", String(16), nullable=False),
    Column("vr_measured_kv", Float), Column("vr_predicted_kv", Float),
    Column("vr_residual_kv", Float), Column("loss_predicted_mw", Float),
    Column("loading_percent", Float), Column("payload", JSON, nullable=False),
    Column("published_at", String(40)))
dead_letters = Table("dead_letters", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("created_at", String(40), nullable=False),
    Column("reason", Text, nullable=False), Column("raw", Text, nullable=False))
Index("ix_states_run_asset_event", states.c.run_id, states.c.asset_id, states.c.event_time)
Index("ix_states_outbox", states.c.run_id, states.c.published_at)


def timestamp(value=None):
    value = value or datetime.now(timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def canonical(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      allow_nan=False)


def digest(payload):
    return hashlib.sha256(canonical(payload).encode()).hexdigest()


class Store:
    def __init__(self, url):
        options = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            options["connect_args"] = {"check_same_thread": False}
        self.engine = create_engine(url, **options)

    def init(self):
        # create_all initializes a NEW schema. It is not a migration engine.
        metadata.create_all(self.engine)

    def ensure_run(self, run_id, mode, manifest):
        if mode not in ("offline", "replay", "live"):
            raise ValueError("Invalid run mode")
        with self.engine.begin() as conn:
            old = conn.execute(select(runs).where(
                runs.c.run_id == run_id)).mappings().first()
            if old:
                if old["mode"] != mode or old["manifest"] != manifest:
                    raise ValueError("Run ID already belongs to another manifest")
                return
            conn.execute(runs.insert().values(run_id=run_id, mode=mode,
                         created_at=timestamp(), manifest=manifest))

    def register_parameters(self, configs):
        with self.engine.begin() as conn:
            for cfg in configs:
                # Validity intervals belong to each run's timeline manifest.
                # Closing an interval must not change immutable electrical values.
                payload = cfg.model_dump(mode="json", exclude={"valid_from", "valid_to"})
                old = conn.execute(select(parameters).where(
                    parameters.c.asset_id == cfg.asset_id,
                    parameters.c.parameter_version == cfg.parameter_version
                )).mappings().first()
                if old and old["payload_hash"] != digest(payload):
                    raise ValueError("Parameter version is immutable; use a new ID")
                if not old:
                    conn.execute(parameters.insert().values(
                        asset_id=cfg.asset_id,
                        parameter_version=cfg.parameter_version,
                        payload_hash=digest(payload), payload=payload))

    def processed(self, run_id, message_id):
        with self.engine.connect() as conn:
            return conn.execute(select(states.c.message_id).where(
                states.c.run_id == run_id,
                states.c.message_id == message_id)).first() is not None

    def commit_frame(self, measurement, state):
        payload = measurement.model_dump(mode="json")
        frame_hash = digest(payload)
        try:
            with self.engine.begin() as conn:
                old = conn.execute(select(measurements).where(
                    measurements.c.message_id == measurement.message_id
                )).mappings().first()
                if old and old["payload_hash"] != frame_hash:
                    raise ValueError("Message ID reused with different content")
                if not old:
                    conn.execute(measurements.insert().values(
                        message_id=measurement.message_id,
                        dataset_id=measurement.dataset_id,
                        source_id=measurement.source_id,
                        asset_id=measurement.asset_id,
                        event_time=timestamp(measurement.event_time),
                        sequence_no=measurement.sequence_no,
                        received_at=state["received_at"],
                        payload_hash=frame_hash, payload=payload))
                existing = conn.execute(select(states.c.message_id).where(
                    states.c.run_id == state["run_id"],
                    states.c.message_id == measurement.message_id)).first()
                if existing:
                    return False
                prediction = state.get("prediction") or {}
                residual = state.get("residual_physics") or {}
                conn.execute(states.insert().values(
                    run_id=state["run_id"], message_id=measurement.message_id,
                    asset_id=measurement.asset_id,
                    event_time=timestamp(measurement.event_time),
                    received_at=state["received_at"],
                    processed_at=state["processed_at"], clock_time=state["clock_time"],
                    dataset_id=measurement.dataset_id,
                    parameter_version=state.get("parameter_version"),
                    topology_version=state.get("topology_version"),
                    model_version=prediction.get("model_version"),
                    model_status=state["model_status"],
                    assessment=state["assessment"], data_origin=measurement.data_origin,
                    vr_measured_kv=measurement.vr_ll_kv,
                    vr_predicted_kv=prediction.get("vr_ll_kv"),
                    vr_residual_kv=residual.get("vr_ll_kv"),
                    loss_predicted_mw=prediction.get("loss_mw"),
                    loading_percent=prediction.get("loading_percent"), payload=state))
                return True
        except IntegrityError as exc:
            # Single owner per stream is the reference deployment contract.
            # A race or alternate ID for a natural duplicate needs inspection.
            raise ValueError("Conflicting frame identity or concurrent ownership") from exc

    def dead_letter(self, reason, raw):
        with self.engine.begin() as conn:
            conn.execute(dead_letters.insert().values(
                created_at=timestamp(), reason=str(reason), raw=raw))

    def history(self, run_id, asset_id=None, limit=1000):
        query = select(states).where(states.c.run_id == run_id)
        if asset_id:
            query = query.where(states.c.asset_id == asset_id)
        query = query.order_by(states.c.event_time.desc(),
                               states.c.message_id.desc()).limit(limit)
        with self.engine.connect() as conn:
            return [dict(r) for r in conn.execute(query).mappings()]

    def outbox(self, run_id, limit=100):
        with self.engine.connect() as conn:
            return [dict(r) for r in conn.execute(select(states).where(
                states.c.run_id == run_id, states.c.published_at.is_(None)
            ).order_by(states.c.event_time).limit(limit)).mappings()]

    def mark_published(self, run_id, message_id):
        with self.engine.begin() as conn:
            conn.execute(states.update().where(states.c.run_id == run_id,
                states.c.message_id == message_id).values(published_at=timestamp()))
