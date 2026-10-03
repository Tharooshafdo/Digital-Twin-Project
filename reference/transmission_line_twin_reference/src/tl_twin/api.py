import os
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Query
from sqlalchemy import text
from .storage import Store


def create_app(database_url=None):
    app = FastAPI(title="Transmission line twin read only API", version="2.0.0")
    store = Store(database_url or os.getenv("DATABASE_URL", "sqlite:///twin.db"))

    @app.get("/health")
    def health():
        try:
            with store.engine.connect() as conn:
                conn.execute(text("SELECT 1 FROM twin_states LIMIT 1"))
            return {"status": "ready"}
        except Exception:
            raise HTTPException(503, "Database or schema not ready")

    @app.get("/v1/runs/{run_id}/lines/{asset_id}/latest")
    def latest(run_id: str, asset_id: str):
        rows = store.history(run_id, asset_id, 1)
        if not rows:
            raise HTTPException(404, "No state for this run and asset")
        result = dict(rows[0]["payload"])
        # Historical replay is evaluated against its event clock, never wall time.
        if result.get("mode") == "live":
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(
                result["event_time"])).total_seconds()
            result["current_age_s"] = age
            result["current_freshness"] = ("STALE" if age > 120 else
                                            "FUTURE" if age < -5 else "FRESH")
        return result

    @app.get("/v1/runs/{run_id}/lines/{asset_id}/history")
    def history(run_id: str, asset_id: str, limit: int = Query(200, ge=1, le=2000)):
        return [row["payload"] for row in store.history(run_id, asset_id, limit)]

    return app


app = create_app()
