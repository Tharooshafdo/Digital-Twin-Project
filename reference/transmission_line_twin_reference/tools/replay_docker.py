"""Host publisher for the loopback-only Compose demo."""
import argparse
import os
from pathlib import Path
from tl_twin.mqtt_io import replay

settings = dict(line.split("=", 1) for line in Path(".env").read_text().splitlines()
                if line and not line.startswith("#"))
os.environ["MQTT_USER"] = "dt_publisher"
os.environ["MQTT_PASSWORD"] = settings["MQTT_PUBLISH_PASSWORD"]
parser = argparse.ArgumentParser()
parser.add_argument("--input", default="data/demo.jsonl")
parser.add_argument("--speed", type=float, default=600)
parser.add_argument("--checkpoint", default="data/docker-replay.checkpoint.json")
args = parser.parse_args()
replay(args.input, "demo", args.speed, args.checkpoint)
print("Replay acknowledged by broker; confirm committed states through API")
