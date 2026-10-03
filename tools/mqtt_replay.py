"""Scoped synthetic/historical producer; durable file-hash checkpoint."""
import argparse,json,time,hashlib,os
from pathlib import Path
from tl_twin.mqtt_io import client,send
from tl_twin.contracts import Measurement
parser=argparse.ArgumentParser();parser.add_argument('--input',required=True);parser.add_argument('--project',default='demo');parser.add_argument('--speed',type=float,default=600);parser.add_argument('--checkpoint',default='data/mqtt-replay.checkpoint.json');args=parser.parse_args()
if args.speed<=0:raise ValueError('Positive speed required')
raw=Path(args.input).read_bytes();file_hash=hashlib.sha256(raw).hexdigest()
frames=sorted([Measurement.model_validate_json(s) for s in raw.decode().splitlines() if s.strip()],key=lambda m:(m.event_time,m.asset_id,m.sequence_no))
checkpoint=Path(args.checkpoint);start=0
if checkpoint.exists():
    saved=json.loads(checkpoint.read_text())
    if saved['file_sha256']!=file_hash or saved['project']!=args.project:raise ValueError('Checkpoint belongs to another input/project')
    start=saved['next_index']
c=client('producer-'+args.project)
try:
    previous=frames[start].event_time if start<len(frames) else None
    for index in range(start,len(frames)):
        m=frames[index];delay=max(0,(m.event_time-previous).total_seconds()/args.speed)
        # Wait in small intervals so Ctrl+C stops a long historical delay.
        end=time.monotonic()+delay
        while time.monotonic()<end:time.sleep(min(.5,end-time.monotonic()))
        send(c,f'dt/v1/project/{args.project}/input/line/{m.asset_id}/measurement',m.model_dump_json())
        checkpoint.parent.mkdir(parents=True,exist_ok=True);temp=checkpoint.with_suffix('.tmp')
        temp.write_text(json.dumps({'file_sha256':file_hash,'project':args.project,'next_index':index+1}));temp.replace(checkpoint)
        previous=m.event_time
finally:c.disconnect();c.loop_stop()
print(json.dumps({'broker_acknowledged':len(frames)-start,'numerical_commit_verified':False,'next_step':'Run tools/reconcile.py against the bridge run'}))
