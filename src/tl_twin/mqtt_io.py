"""QoS 1 input, transactional state outbox, at least once delivery."""
import json
import os
import queue
import threading
import time
from pathlib import Path
import paho.mqtt.client as mqtt
from sqlalchemy.exc import SQLAlchemyError
from .contracts import Measurement
from .twin import evaluate


def client(client_id, durable=False, manual_ack=False,
           on_connect=None, on_message=None):
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id,
                    clean_session=not durable, protocol=mqtt.MQTTv311,
                    manual_ack=manual_ack)
    if os.getenv("MQTT_USER"):
        c.username_pw_set(os.environ["MQTT_USER"], os.environ["MQTT_PASSWORD"])
    if os.getenv("MQTT_CA"):
        c.tls_set(ca_certs=os.environ["MQTT_CA"])
    c.reconnect_delay_set(min_delay=1, max_delay=30)
    c.on_connect = on_connect
    c.on_message = on_message
    c.connect(os.getenv("MQTT_HOST", "localhost"),
              int(os.getenv("MQTT_PORT", "1883")), keepalive=30)
    c.loop_start()
    return c


def send(c, topic, payload):
    info = c.publish(topic, payload, qos=1, retain=False)
    info.wait_for_publish(timeout=10)
    if not info.is_published():
        raise TimeoutError("MQTT broker acknowledgement timed out")


def replay(path, stream_id, speed=60, checkpoint=None):
    if speed <= 0:
        raise ValueError("Speed must be positive")
    frames = [Measurement.model_validate_json(line) for line in
              Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    frames.sort(key=lambda m: (m.event_time, m.asset_id, m.sequence_no))
    start = 0
    if checkpoint and Path(checkpoint).exists():
        saved = json.loads(Path(checkpoint).read_text())
        # Resume only the exact normalized dataset, never a changed input file.
        from hashlib import sha256
        if saved["file_hash"] != sha256(Path(path).read_bytes()).hexdigest():
            raise ValueError("Checkpoint belongs to another file")
        start = saved["next_index"]
    c = client("replay-" + stream_id)
    try:
        previous = frames[start].event_time if start < len(frames) else None
        for i in range(start, len(frames)):
            m = frames[i]
            delay = max(0, (m.event_time - previous).total_seconds() / speed)
            time.sleep(delay)
            send(c, f"dt/v1/input/{stream_id}/line/{m.asset_id}/measurement",
                 m.model_dump_json())
            previous = m.event_time
            if checkpoint:
                from hashlib import sha256
                temp = Path(str(checkpoint) + ".tmp")
                temp.write_text(json.dumps({"next_index": i + 1,
                    "file_hash": sha256(Path(path).read_bytes()).hexdigest()}))
                temp.replace(checkpoint)
    finally:
        c.disconnect()
        c.loop_stop()


def consume(store, configs, run_id, stream_id, mode="replay"):
    inbox = queue.Queue(maxsize=1000)
    overloaded = threading.Event()

    def connected(c, userdata, flags, reason_code, properties):
        if reason_code == 0:
            c.subscribe(f"dt/v1/input/{stream_id}/line/+/measurement", qos=1)

    def received(c, userdata, msg):
        try:
            inbox.put_nowait(msg)
        except queue.Full:
            # Restart the process; persistent session redelivers unacknowledged input.
            overloaded.set()

    c = client("twin-" + stream_id, durable=True, manual_ack=True,
               on_connect=connected, on_message=received)
    pending = None
    try:
        while True:
            if overloaded.is_set():
                raise RuntimeError("Input queue full; restart and reconcile stream")
            # Paho's background network loop reconnects after transport failures.
            try:
                pending = pending or inbox.get(timeout=0.2)
            except queue.Empty:
                pass
            if pending:
                raw = pending.payload.decode("utf-8", errors="replace")
                try:
                    m = Measurement.model_validate_json(raw)
                    if pending.topic != f"dt/v1/input/{stream_id}/line/{m.asset_id}/measurement":
                        raise ValueError("Topic and payload asset disagree")
                    # Commit checks identity even for an already processed frame.
                    s = evaluate(m, configs, run_id, mode)
                    s["mode"] = mode
                    store.commit_frame(m, s)
                except (ValueError, json.JSONDecodeError) as exc:
                    store.dead_letter(exc, raw)
                except SQLAlchemyError:
                    time.sleep(2)  # Keep frame pending and unacknowledged.
                    continue
                c.ack(pending.mid, pending.qos)
                pending = None
            for row in store.outbox(run_id):
                try:
                    send(c, f"dt/v1/run/{run_id}/line/{row['asset_id']}/state",
                         json.dumps(row["payload"], allow_nan=False))
                    store.mark_published(run_id, row["message_id"])
                except (TimeoutError, RuntimeError, SQLAlchemyError):
                    break
    finally:
        c.disconnect()
        c.loop_stop()
