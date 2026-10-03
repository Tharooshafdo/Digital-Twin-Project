"""Reconcile expected identities with committed measurements and numerical states."""
import argparse,json,os
from pathlib import Path
from sqlalchemy import select
from grid_twin import db
parser=argparse.ArgumentParser();parser.add_argument('--input',required=True);parser.add_argument('--run-id',required=True);parser.add_argument('--project',default='demo');parser.add_argument('--db',default=os.getenv('DATABASE_URL','sqlite:///data/platform.db'));args=parser.parse_args()
expected={json.loads(s)['message_id'] for s in Path(args.input).read_text().splitlines() if s.strip()}
with db.engine_for(args.db).connect() as conn:
    measurements=set(conn.execute(select(db.measurements.c.message_id).where(db.measurements.c.project_id==args.project)).scalars())
    states=set(conn.execute(select(db.states.c.message_id).where(db.states.c.run_id==args.run_id)).scalars())
result={'expected':len(expected),'committed_measurements':len(expected&measurements),'committed_states':len(expected&states),'missing_measurements':sorted(expected-measurements),'missing_states':sorted(expected-states),'unexpected_states':sorted(states-expected)}
print(json.dumps(result,indent=2))
raise SystemExit(1 if result['missing_measurements'] or result['missing_states'] or result['unexpected_states'] else 0)
