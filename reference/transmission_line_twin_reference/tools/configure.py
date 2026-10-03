"""Generate local demo secrets without overwriting an existing environment."""
from pathlib import Path
import secrets

path = Path(".env")
if path.exists():
    raise SystemExit(".env already exists; keep it for persisted database volumes")
names = ("DB_ADMIN_PASSWORD", "DB_APP_PASSWORD", "DB_READER_PASSWORD",
         "MQTT_PUBLISH_PASSWORD", "MQTT_WORKER_PASSWORD", "MQTT_VIEW_PASSWORD",
         "GRAFANA_ADMIN_PASSWORD")
path.write_text("".join(f"{key}={secrets.token_hex(24)}\n" for key in names))
try:
    path.chmod(0o600)
except OSError:
    pass
print("Local environment generated. Keep .env private and backed up securely.")
