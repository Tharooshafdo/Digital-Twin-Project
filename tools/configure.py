"""Generate private Compose secrets exactly once; preserve existing volumes."""
from pathlib import Path
import secrets
path=Path('.env')
if path.exists():
    print('.env already exists; retaining existing credentials')
else:
    path.write_text('\n'.join(f'{name}={secrets.token_hex(24)}' for name in ['DB_PASSWORD','DB_APP_PASSWORD','MQTT_WORKER_PASSWORD','MQTT_PUBLISH_PASSWORD'])+'\n',encoding='utf8')
    print('Generated .env. Keep it private and retain it with your volume backups.')
