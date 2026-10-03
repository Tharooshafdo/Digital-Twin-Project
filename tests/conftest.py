import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from grid_twin import db
from grid_twin.demo import initialize, demo_csv
from grid_twin.api import create_app
from grid_twin.ingestion import parse_csv
from grid_twin import service

@pytest.fixture
def platform(tmp_path):
    url = "sqlite:///" + str(tmp_path/"platform.db").replace("\\", "/")
    engine = db.engine_for(url)
    db.migrate(url)
    initialized = initialize(engine, tmp_path/"initial-credentials.json")
    credentials = json.loads((tmp_path/"initial-credentials.json").read_text())
    client = TestClient(create_app(url))
    login = client.post("/api/auth/login", json={"username": credentials["username"], "password": credentials["password"]})
    assert login.status_code == 200
    client.headers["Authorization"] = "Bearer " + login.json()["token"]
    yield {"engine": engine, "url": url, "client": client, "rid": initialized["revision_id"], "credentials": credentials, "tmp": tmp_path}
    engine.dispose()

@pytest.fixture
def dataset():
    raw, mapping = demo_csv(5)
    return raw, mapping, parse_csv(raw, mapping)

def make_job(platform, frames, kind="replay", payload=None, mode="replay"):
    with platform["engine"].begin() as conn:
        manifest = service.run_manifest(conn, "demo", platform["rid"], mode)
        result = service.enqueue(conn, "demo", kind, payload or {"frames": frames}, manifest, "test", mode, 100000)
    return result, manifest
