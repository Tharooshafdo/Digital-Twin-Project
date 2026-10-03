"""Measured small workloads; not a claim of production scale."""
import argparse
import copy
import json
import platform
import os
import time
import tempfile
import subprocess
from pathlib import Path
import numpy as np
from sqlalchemy import select,func
from grid_twin import db,service
from grid_twin.demo import demo_network,demo_csv
from grid_twin.ingestion import parse_csv
from grid_twin.worker import run_one

def percentiles(values):
    return dict(zip(['p50','p95','p99'],map(float,np.percentile(values,[50,95,99]))))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--snapshots',type=int,default=1);parser.add_argument('--assets',type=int,nargs='+',default=[1,10,100]);parser.add_argument('--out',default='docs/evidence/benchmark.json');args=parser.parse_args()
    result={'hardware':{'platform':platform.platform(),'cpu':platform.processor(),'logical_cpus':os.cpu_count(),'python':platform.python_version()},'workloads':[],'limitations':['Sequential single worker on local SQLite; no broker/network latency','One burst at each size by default; tail quantiles are descriptive, not statistically established service levels','No claim of sustainable 100-asset real-time cadence']}
    if os.name=='nt':
        query=subprocess.run(['powershell','-NoProfile','-Command','Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors | ConvertTo-Json'],capture_output=True,text=True)
        try:result['hardware']['processor_details']=json.loads(query.stdout)
        except Exception:pass
    raw,mapping=demo_csv(max(1,args.snapshots));base=parse_csv(raw,mapping)['frames']
    for count in args.assets:
        with tempfile.TemporaryDirectory() as folder:
            url='sqlite:///'+str(Path(folder)/'bench.db').replace('\\','/');engine=db.engine_for(url);db.migrate(url)
            network=demo_network();original=next(c for c in network['components'] if c['id']=='TL_001')
            extra=[]
            for i in range(1,count):
                c=copy.deepcopy(original);c['id']=f'TL_BENCH_{i:03}';extra.append(c)
            network['components']+=extra
            frames=[]
            for event in base:
                for i in range(count):
                    m=copy.deepcopy(event);m['asset_id']='TL_001' if i==0 else f'TL_BENCH_{i:03}';m['message_id']=f'bench-{count}-{i}-{m["sequence_no"]}';frames.append(m)
            with engine.begin() as conn:
                conn.execute(db.projects.insert().values(id='bench',name='Isolated benchmark',created_at=db.now()))
                rid=service.create_revision(conn,'bench',network,'benchmark','bench','2020-01-01T00:00:00Z')
                manifest=service.run_manifest(conn,'bench',rid,'replay')
                job=service.enqueue(conn,'bench','replay',{'frames':frames},manifest,'bench',speed=100000)
            started=time.perf_counter();latency=[];e2e=[]
            for _ in frames:
                # Benchmark burst admission: no inter-event pacing. Normal replay honors event deltas.
                with engine.begin() as conn:conn.execute(db.jobs.update().where(db.jobs.c.id==job['job_id']).values(next_due=0))
                tick=time.perf_counter();assert run_one(engine,'bench-worker');latency.append((time.perf_counter()-tick)*1000);e2e.append((time.perf_counter()-started)*1000)
            duration=time.perf_counter()-started
            with engine.connect() as conn:
                committed=conn.scalar(select(func.count()).select_from(db.states));solved=conn.scalar(select(func.count()).select_from(db.states).where(db.states.c.status=='SOLVED'))
                payload_bytes=np.mean([len(db.canonical(p).encode()) for p in conn.execute(select(db.states.c.payload)).scalars()])
            result['workloads'].append({'independent_assets':count,'snapshots_per_asset':args.snapshots,'cadence':'burst; event spacing 300s without pacing','duration_s':duration,'committed':committed,'solved':solved,'throughput_states_per_s':committed/duration,'processing_latency_ms':percentiles(latency),'admission_to_commit_ms':percentiles(e2e),'mean_state_payload_bytes':float(payload_bytes),'database_bytes':(Path(folder)/'bench.db').stat().st_size})
            engine.dispose()
    from grid_twin.solver import solve_network
    values=[]
    for _ in range(3):
        start=time.perf_counter();solved=solve_network(demo_network(),'benchmark-connected');values.append((time.perf_counter()-start)*1000)
    result['connected_network']={'assets':len(demo_network()['components']),'runs':3,'latency_ms':percentiles(values),'balance_error_mw':solved['active_power_balance_error_mw']}
    Path(args.out).parent.mkdir(parents=True,exist_ok=True);Path(args.out).write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))
if __name__=='__main__':main()
