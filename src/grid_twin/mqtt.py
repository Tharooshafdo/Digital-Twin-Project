"""Scoped QoS1 bridge. Commit before manual ACK; bounded/restartable queue."""
import json
import os
import queue
import threading
import time
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from tl_twin.mqtt_io import client, send
from . import db, service
from .worker import calculate_frame, claim_outbox, complete_outbox

class DurableInbox:
    def __init__(self, capacity=1000):
        self.queue = queue.Queue(maxsize=capacity)
        self.overloaded = threading.Event()
    def receive(self, message):
        try:
            self.queue.put_nowait(message)
        except queue.Full:
            self.overloaded.set() # no ACK: persistent session must redeliver
            return False
        return True

def commit_delivery(engine, project_id, run_id, topic, raw):
    try:
        with engine.connect() as conn:
            run = conn.execute(select(db.runs).where(db.runs.c.id == run_id, db.runs.c.project_id == project_id)).mappings().one()
        frame = json.loads(raw)
        if topic != f"dt/v1/project/{project_id}/input/line/{frame['asset_id']}/measurement":
            raise ValueError("Topic and payload identity disagree")
        m, state = calculate_frame(frame, run["manifest"], run_id, run["mode"])
        with engine.begin() as conn:
            service.commit_state(conn, project_id, m, state, run["manifest"])
        return "committed"
    except (ValueError, KeyError) as exc:
        with engine.begin() as conn:
            conn.execute(db.dead_letters.insert().values(id=db.uid("dead"), project_id=project_id,
                created_at=db.now(), reason=str(exc), raw=raw))
        return "dead_letter"

def main():
    engine = db.engine_for()
    project_id = os.getenv("MQTT_PROJECT", "demo")
    run_id = os.environ["MQTT_RUN_ID"]
    owner = "bridge-"+project_id
    inbox = DurableInbox(int(os.getenv("MQTT_QUEUE_CAPACITY", "1000")))
    def connected(c, _, flags, reason, props):
        if reason == 0:
            c.subscribe(f"dt/v1/project/{project_id}/input/line/+/measurement", qos=1)
    def received(c, _, msg):
        inbox.receive(msg)
    c = client(owner, durable=True, manual_ack=True, on_connect=connected, on_message=received)
    pending = None
    try:
        while True:
            if inbox.overloaded.is_set():
                raise RuntimeError("MQTT queue overload; exit without ACK, restart durable session, reconcile expected IDs")
            try:
                pending = pending or inbox.queue.get(timeout=0.1)
            except queue.Empty:
                pass
            if pending:
                try:
                    commit_delivery(engine, project_id, run_id, pending.topic, pending.payload.decode("utf-8", errors="replace"))
                    c.ack(pending.mid, pending.qos)
                    pending = None
                except SQLAlchemyError:
                    time.sleep(1) # preserve pending unacknowledged delivery
                    continue
            record = claim_outbox(engine, owner)
            if record:
                try:
                    send(c, record["topic"], db.canonical(record["payload"]))
                    complete_outbox(engine, owner, record["id"])
                except (TimeoutError, RuntimeError, SQLAlchemyError):
                    pass # lease expires; resend is allowed and consumers deduplicate
    finally:
        c.disconnect()
        c.loop_stop()
