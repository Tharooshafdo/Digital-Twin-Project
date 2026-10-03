import argparse
import json
import os
import sqlite3
import time
from pathlib import Path
from sqlalchemy import select, func
from . import db, service
from .demo import initialize, demo_csv
from .ingestion import parse_csv

def main():
    parser = argparse.ArgumentParser(description="Power-system twin local operations")
    parser.add_argument("--db", default=os.getenv("DATABASE_URL", "sqlite:///data/platform.db"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    demo = sub.add_parser("demo")
    demo.add_argument("--rows", type=int, default=288)
    sub.add_parser("worker")
    sub.add_parser("mqtt")
    backup = sub.add_parser("backup"); backup.add_argument("--out", required=True)
    restore = sub.add_parser("restore"); restore.add_argument("--input", required=True)
    retention=sub.add_parser("retention");retention.add_argument("--project",default="demo");retention.add_argument("--days",type=int,default=90);retention.add_argument("--out",default="data/archive");retention.add_argument("--apply",action="store_true")
    args = parser.parse_args()
    os.environ["DATABASE_URL"] = args.db
    engine = db.engine_for(args.db)
    if args.command == "retention":
        from .retention import archive_runs
        print(json.dumps(archive_runs(engine,args.project,args.days,args.out,args.apply),indent=2))
    elif args.command == "init":
        db.migrate(args.db)
        credentials_path=Path(args.db.removeprefix("sqlite:///")).parent/"initial-credentials.json" if args.db.startswith("sqlite:///") else Path("data/initial-credentials.json")
        print(json.dumps(initialize(engine,credentials_path), indent=2))
    elif args.command == "worker":
        from .worker import main as worker
        worker()
    elif args.command == "mqtt":
        from .mqtt import main as mqtt
        mqtt()
    elif args.command == "demo":
        from .worker import run_one
        raw, mapping = demo_csv(args.rows)
        result = parse_csv(raw, mapping)
        with engine.begin() as conn:
            rid = conn.scalar(select(db.revisions.c.id).where(db.revisions.c.project_id == "demo", db.revisions.c.status == "published"))
            manifest = service.run_manifest(conn, "demo", rid, "replay")
            manifest["dataset_manifest"] = result["manifest"]
            study = service.enqueue(conn, "demo", "replay", {"frames": result["frames"]}, manifest, "cli", speed=100000)
        while True:
            run_one(engine, "demo-cli")
            with engine.connect() as conn:
                job = conn.execute(select(db.jobs).where(db.jobs.c.id == study["job_id"])).mappings().one()
            if job["status"] in ("completed", "failed"):
                break
            time.sleep(0.005)
        with engine.connect() as conn:
            report = service.report_data(conn, "demo", study["run_id"])
        evidence = {"study": study, "job_status": job["status"], "import": result["manifest"], "report": report}
        Path("docs/evidence").mkdir(parents=True, exist_ok=True)
        Path("docs/evidence/demo.json").write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
        print(json.dumps({"run_id": study["run_id"], "status": job["status"], "states": report["states"], "metrics": report["voltage_kv"], "rejects": len(result["rejects"])}))
    elif args.command in ("backup", "restore"):
        if not args.db.startswith("sqlite:///"):
            raise ValueError("Use pg_dump/pg_restore for PostgreSQL; see README")
        current = Path(args.db.removeprefix("sqlite:///"))
        if args.command == "backup":
            output = Path(args.out)
            if output.exists() or output.resolve() == current.resolve():
                raise ValueError("Backup target must be a new distinct file")
            output.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(current) as source, sqlite3.connect(output) as target:
                source.backup(target)
            print(json.dumps({"backup": str(output), "bytes": output.stat().st_size}))
        else:
            if current.exists():
                raise ValueError("Restore requires a NEW isolated database path; existing data is never overwritten")
            current.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(args.input) as source, sqlite3.connect(current) as target:
                source.backup(target)
            print(json.dumps({"restored": str(current)}))

if __name__ == "__main__":
    main()
