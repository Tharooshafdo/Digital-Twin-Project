"""Geographic metadata, measured grid summaries and explicit synthetic telemetry.

No line-end flows are summed to estimate system demand. Observation channels
share one source snapshot; model predictions never become field measurements.
"""
import math
import os
from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select, or_
from . import db, service

class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

class AssetLocation(Contract):
    asset_id: str = Field(min_length=1, max_length=80)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    label: str = Field(default='', max_length=200)
    provenance: Literal['illustrative', 'surveyed', 'user_entered'] = 'user_entered'

class Reading(Contract):
    value: float | None = None
    quality: Literal['GOOD', 'SUSPECT', 'BAD', 'MISSING'] = 'GOOD'

class BusReading(Reading):
    asset_id: str = Field(min_length=1, max_length=80)
    @model_validator(mode='after')
    def voltage(self):
        if self.value is not None and self.value < 0:
            raise ValueError('Bus RMS voltage cannot be negative')
        return self

class GridObservation(Contract):
    snapshot_id: str = Field(min_length=1, max_length=120)
    revision_id: str
    event_time: datetime
    source_id: str = Field(min_length=1, max_length=120)
    data_origin: Literal['synthetic', 'field']
    frequency_hz: Reading = Field(default_factory=lambda: Reading(quality='MISSING'))
    total_demand_mw: Reading = Field(default_factory=lambda: Reading(quality='MISSING'))
    bus_voltages_kv: list[BusReading] = Field(default_factory=list, max_length=2000)

    @field_validator('event_time')
    @classmethod
    def aware(cls, value):
        return db.utc_time(value)

    @model_validator(mode='after')
    def bounds(self):
        if self.frequency_hz.value is not None and not 0 < self.frequency_hz.value <= 100:
            raise ValueError('Frequency must be in (0,100] Hz')
        if self.total_demand_mw.value is not None and self.total_demand_mw.value < 0:
            raise ValueError('Total demand must be nonnegative MW')
        if len({v.asset_id for v in self.bus_voltages_kv}) != len(self.bus_voltages_kv):
            raise ValueError('Duplicate bus voltage channel')
        return self

def active_revision(conn, project_id, clock=None):
    clock = clock or db.now()
    table = db.entities['topology_timelines']
    timeline = conn.execute(select(table.c.payload).where(table.c.project_id == project_id)
        .order_by(table.c.created_at.desc(), table.c.id.desc()).limit(1)).scalar()
    if not timeline:
        # Databases seeded before timeline publication was introduced retain
        # explicit immutable revision intervals. Accept only one as-of match.
        revisions=conn.execute(select(db.revisions).where(db.revisions.c.project_id==project_id,
            db.revisions.c.status=='published',db.revisions.c.valid_from<=clock,
            or_(db.revisions.c.valid_to.is_(None),db.revisions.c.valid_to>clock)).limit(2)).mappings().all()
        return revisions[0] if len(revisions)==1 else None
    applicable = [v for v in timeline['intervals'] if db.utc_time(v['valid_from']) <= clock
        and (not v['valid_to'] or clock < db.utc_time(v['valid_to']))]
    if len(applicable) != 1:
        return None
    return conn.execute(select(db.revisions).where(db.revisions.c.project_id == project_id,
        db.revisions.c.id == applicable[0]['revision_id'])).mappings().one()

def validate_observation(conn, project_id, observation):
    revision = conn.execute(select(db.revisions).where(db.revisions.c.project_id == project_id,
        db.revisions.c.id == observation.revision_id)).mappings().first()
    if not revision or revision['status'] != 'published':
        raise ValueError('Grid observations require a published revision in this project')
    applicable=active_revision(conn,project_id,observation.event_time)
    if not applicable or applicable['id']!=observation.revision_id:
        raise ValueError('Observation revision must match the published model at its event time')
    buses = {c['id'] for c in revision['payload']['components'] if c['type_id'] == 'ac.bus'}
    if any(v.asset_id not in buses for v in observation.bus_voltages_kv):
        raise ValueError('Voltage channel must reference a bus in the observation revision')
    return revision

def store_observation(conn, project_id, observation, actor=None, extra=None):
    revision = validate_observation(conn, project_id, observation)
    table = db.entities['grid_observations']
    payload = observation.model_dump(mode='json')
    key = 'grid.' + db.digest([project_id, observation.source_id, observation.snapshot_id])
    previous = conn.execute(select(table.c.payload).where(table.c.id == key)).scalar()
    if previous:
        if previous['observation_sha256'] != db.digest(payload):
            raise ValueError('Grid snapshot identity reused with changed content')
        return {'id': key, 'duplicate': True}
    conn.execute(table.insert().values(id=key, project_id=project_id, version='grid.observation.v1',
        created_at=db.now(), payload={**payload, 'received_at': db.iso(db.now()),
            'network_sha256': revision['payload_hash'], 'observation_sha256': db.digest(payload),
            **(extra or {})}))
    if actor:
        db.audit_event(conn, actor, 'grid.observation_received', project_id,
            {'id': key, 'source_id': observation.source_id, 'origin': observation.data_origin})
    return {'id': key, 'duplicate': False}

def seed_demo_locations(conn):
    """Illustrative coordinates only; never seed positions into field projects."""
    table = db.entities['asset_locations']
    if not conn.scalar(select(db.projects.c.id).where(db.projects.c.id == 'demo')):
        return
    if conn.scalar(select(table.c.id).where(table.c.project_id == 'demo').limit(1)):
        return
    revision = active_revision(conn, 'demo')
    if not revision:
        return
    bus_positions = {'BUS_A': (6.9271, 79.8612), 'BUS_B': (7.015, 80.045),
        'BUS_C': (7.12, 80.23), 'BUS_D': (7.10, 80.26)}
    for c in revision['payload']['components']:
        positions = [bus_positions[t['bus_id']] for t in c['terminals'] if t['bus_id'] in bus_positions]
        location = bus_positions.get(c['id'])
        if not location and positions:
            location = (sum(p[0] for p in positions)/len(positions), sum(p[1] for p in positions)/len(positions))
            # Separate co-located symbols without claiming engineering precision.
            if len(positions) == 1:
                location = (location[0] + .008, location[1] - .006)
        if location:
            conn.execute(table.insert().values(id=db.uid('location'), project_id='demo', version='1',
                created_at=db.now(), payload=AssetLocation(asset_id=c['id'], latitude=location[0],
                    longitude=location[1], label=c['name'], provenance='illustrative').model_dump()))

def project_overview(conn, project_id, mode='demo', source_id=None, clock=None):
    clock = clock or db.now()
    revision = active_revision(conn, project_id, clock)
    network = revision['payload'] if revision else {'components': [], 'frequency_hz': None, 'provenance': 'unavailable'}
    locations = {}
    table = db.entities['asset_locations']
    for row in conn.execute(select(table).where(table.c.project_id == project_id)
            .order_by(table.c.created_at.desc(), table.c.id.desc())).mappings():
        locations.setdefault(row['payload']['asset_id'], {**row['payload'], 'updated_at': db.iso(row['created_at'])})
    observations = db.entities['grid_observations']
    origin = 'field' if mode == 'live' else 'synthetic'
    query = select(observations).where(observations.c.project_id == project_id,
        observations.c.payload['data_origin'].as_string() == origin)
    if source_id:
        query = query.where(observations.c.payload['source_id'].as_string() == source_id)
    row = conn.execute(query.order_by(observations.c.payload['event_time'].as_string().desc(),
        observations.c.created_at.desc(), observations.c.id.desc()).limit(1)).mappings().first()
    snapshot = row['payload'] if row else None
    age = (clock-db.utc_time(snapshot['event_time'])).total_seconds() if snapshot else None
    status = 'NO_SOURCE' if not snapshot else 'FUTURE' if age < -5 else 'STALE' if age > 120 else 'FRESH'
    if snapshot and (not revision or snapshot['revision_id'] != revision['id']):
        status = 'REVISION_MISMATCH'
    def usable(reading):
        return reading.get('value') if status == 'FRESH' and reading.get('quality') == 'GOOD' else None
    frequency = snapshot.get('frequency_hz', {}) if snapshot else {}
    demand = snapshot.get('total_demand_mw', {}) if snapshot else {}
    voltages = {v['asset_id']: v for v in snapshot['bus_voltages_kv']} if snapshot else {}
    components = [{**c, 'location': locations.get(c['id']),
        'voltage_kv': usable(voltages.get(c['id'], {})),
        'voltage_quality': voltages.get(c['id'], {}).get('quality', 'MISSING')} for c in network['components']]
    return {'project_id': project_id, 'mode': mode, 'refreshed_at': db.iso(clock), 'refresh_interval_s': 5,
        'revision_id': revision['id'] if revision else None, 'network': network,
        'components': components, 'unlocated_assets': sum(c['location'] is None for c in components),
        'telemetry': {'status': status, 'event_time': snapshot['event_time'] if snapshot else None,
            'age_s': age, 'source_id': snapshot['source_id'] if snapshot else None, 'data_origin': origin,
            'frequency_hz': usable(frequency), 'frequency_quality': frequency.get('quality', 'MISSING'),
            'nominal_frequency_hz': network['frequency_hz'], 'total_demand_mw': usable(demand),
            'demand_quality': demand.get('quality', 'MISSING'), 'snapshot': snapshot},
        'map_config': {'api_key': os.getenv('GOOGLE_MAPS_BROWSER_KEY', ''),
            'map_id': os.getenv('GOOGLE_MAPS_MAP_ID', 'DEMO_MAP_ID')},
        'field_validation': False}

def tick_demo(engine, clock=None):
    """A real shared-network solve produces clearly synthetic demo frames every 5s."""
    from .solver import solve_network
    clock = clock or db.now()
    slot = int(clock.timestamp()) // 5
    event_time = datetime.fromtimestamp(slot*5, timezone.utc)
    with engine.connect() as conn:
        revision = active_revision(conn, 'demo', clock)
        if not revision:
            return
        key = 'grid.' + db.digest(['demo', 'demo.connected_grid.v1', str(slot)])
        if conn.scalar(select(db.entities['grid_observations'].c.id).where(db.entities['grid_observations'].c.id == key)):
            return
        network = __import__('copy').deepcopy(revision['payload'])
    factor = 1 + .04*math.sin(slot/12)
    for c in network['components']:
        if c['type_id'] == 'ac.load_pq':
            c['parameters']['p_mw'] *= factor
            c['parameters']['q_mvar'] *= factor
    result = solve_network(network, 'demo-grid-'+str(slot))
    observation = GridObservation(snapshot_id=str(slot), revision_id=revision['id'], event_time=event_time,
        source_id='demo.connected_grid.v1', data_origin='synthetic',
        frequency_hz=Reading(value=network['frequency_hz']+.025*math.sin(slot/7)),
        total_demand_mw=Reading(value=result['demand_mw']),
        bus_voltages_kv=[BusReading(asset_id=c['id'], value=result['components'][c['id']].get('voltage_kv'),
            quality='GOOD' if result['components'][c['id']]['status']=='SOLVED' else 'MISSING')
            for c in network['components'] if c['type_id']=='ac.bus'])
    with engine.begin() as conn:
        if conn.scalar(select(db.entities['grid_observations'].c.id).where(db.entities['grid_observations'].c.id == key)):
            return
        # Two workers may enter the same cadence slot. Insert in a savepoint.
        from sqlalchemy.exc import IntegrityError
        try:
            with conn.begin_nested():
                store_observation(conn, 'demo', observation, extra={'simulation': result,
                    'assumptions': 'Synthetic PQ demand variation; frequency is an illustrative signal, not a power-flow result'})
        except IntegrityError:
            pass
        table=db.entities['grid_observations']
        old=select(table.c.id).where(table.c.project_id=='demo',
            table.c.payload['source_id'].as_string()=='demo.connected_grid.v1').order_by(table.c.created_at.desc()).offset(720)
        conn.execute(table.delete().where(table.c.id.in_(old)))

def apply_simulation(conn, project_id, run_id, actor, name):
    """Publish only the persisted, successfully simulated candidate against its base."""
    conn.execute(select(db.projects.c.id).where(db.projects.c.id==project_id).with_for_update()).one()
    applied=conn.execute(select(db.audit.c.payload).where(db.audit.c.project_id==project_id,
        db.audit.c.action=='simulation.applied', db.audit.c.payload['run_id'].as_string()==run_id)).scalar()
    if applied:
        return {**applied, 'already_applied': True}
    run=conn.execute(select(db.runs).where(db.runs.c.id==run_id, db.runs.c.project_id==project_id)).mappings().first()
    job=conn.execute(select(db.jobs).where(db.jobs.c.run_id==run_id, db.jobs.c.project_id==project_id)).mappings().first()
    report=conn.execute(select(db.entities['validation_reports'].c.payload).where(
        db.entities['validation_reports'].c.id==run_id, db.entities['validation_reports'].c.project_id==project_id)).scalar()
    if not run or run['kind']!='scenario' or not job or job['status']!='completed' or not report:
        raise ValueError('Complete a successful scenario simulation before applying changes')
    if report.get('scenario',{}).get('model_status')!='SOLVED' or report.get('scenario_sha256')!=db.digest(job['payload']['network']):
        raise ValueError('Simulation candidate is unavailable or inconsistent')
    active=active_revision(conn, project_id)
    if not active or active['id']!=run['manifest']['revision_id']:
        raise ValueError('The published baseline changed; rerun the simulation against the current model')
    rid=service.create_revision(conn,project_id,job['payload']['network'],name,actor,db.iso(db.now()),parent_id=active['id'])
    service.publish_revision(conn,project_id,rid,actor)
    result={'revision_id':rid,'run_id':run_id,'physical_commands':False}
    db.audit_event(conn,actor,'simulation.applied',project_id,result)
    return result
