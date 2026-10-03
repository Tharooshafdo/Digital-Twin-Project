"""Opt-in archive retention. Preserve manifests; never prune unacknowledged outbox."""
import gzip,json,hashlib
from pathlib import Path
from datetime import timedelta
from sqlalchemy import select,func
from . import db,service

def archive_runs(engine,project_id,days,folder,apply=False):
    if days<0:raise ValueError('Retention days must be nonnegative')
    cutoff=db.now()-timedelta(days=days)
    with engine.connect() as conn:
        candidates=[dict(r) for r in conn.execute(select(db.runs).where(db.runs.c.project_id==project_id,db.runs.c.created_at<cutoff)).mappings()]
    result={'project_id':project_id,'days':days,'apply':apply,'archived':[],'eligible':[],'skipped':[]}
    for run in candidates:
        run_id=run['id']
        with engine.connect() as conn:
            unfinished=conn.scalar(select(func.count()).select_from(db.jobs).where(db.jobs.c.run_id==run_id,db.jobs.c.status.in_(['queued','running','paused'])))
            pending=conn.scalar(select(func.count()).select_from(db.outbox).where(db.outbox.c.id.like(run_id+'.%'),db.outbox.c.published_at.is_(None)))
            count=conn.scalar(select(func.count()).select_from(db.states).where(db.states.c.run_id==run_id))
        if unfinished or pending or run['kind']=='mqtt_stream':
            result['skipped'].append({'run_id':run_id,'reason':'Active job, active stream or unpublished outbox'});continue
        if not count:continue
        result['eligible'].append({'run_id':run_id,'states':count})
        if not apply:continue
        target=Path(folder);target.mkdir(parents=True,exist_ok=True)
        archive=target/(run_id+'.jsonl.gz')
        if archive.exists():raise ValueError('Archive already exists; retain it and inspect the previous operation')
        temporary=archive.with_suffix('.tmp')
        # Lock run during archive and prune; workers cannot add a state after the
        # terminal-job check. Streaming runs are excluded entirely.
        with engine.begin() as conn:
            conn.execute(select(db.runs).where(db.runs.c.id==run_id).with_for_update()).one()
            report=json.loads(json.dumps(service.report_data(conn,project_id,run_id),default=db.iso))
            with gzip.open(temporary,'wt',encoding='utf8') as handle:
                handle.write(json.dumps({'kind':'manifest','run':run,'report':report},default=str)+'\n')
                query=select(db.states.c.payload).where(db.states.c.run_id==run_id).order_by(db.states.c.event_time)
                for state in conn.execute(query.execution_options(stream_results=True)).scalars():
                    handle.write(json.dumps({'kind':'state','payload':state})+'\n')
            checksum=hashlib.sha256(temporary.read_bytes()).hexdigest()
            # Validate archive contents before deletion, including exact state count.
            with gzip.open(temporary,'rt',encoding='utf8') as handle:
                records=[json.loads(line) for line in handle]
            if sum(r['kind']=='state' for r in records)!=count:raise ValueError('Archive count mismatch')
            temporary.replace(archive)
            conn.execute(db.states.delete().where(db.states.c.run_id==run_id))
            conn.execute(db.outbox.delete().where(db.outbox.c.id.like(run_id+'.%'),db.outbox.c.published_at.is_not(None)))
            db.audit_event(conn,'retention-cli','run.archived',project_id,{'run_id':run_id,'archive':str(archive),'sha256':checksum,'state_count':count,'report':report})
        result['archived'].append({'run_id':run_id,'file':str(archive),'sha256':checksum,'states':count})
    return result
