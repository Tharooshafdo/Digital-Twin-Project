"""Natural measurement identities and immutable effective topology timelines."""
import hashlib,json
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision="0003"
down_revision="0002"
branch_labels=None
depends_on=None
def natural(payload):
    identity=[payload[k] for k in ("dataset_id","source_id","asset_id","event_time","sequence_no")]
    return hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
def upgrade():
    op.add_column('measurements',sa.Column('natural_key',sa.String(64),nullable=True))
    conn=op.get_bind()
    table=sa.table('measurements',sa.column('id',sa.String),sa.column('payload',sa.JSON),sa.column('natural_key',sa.String))
    for row in conn.execute(sa.select(table.c.id,table.c.payload)).mappings():
        payload=row['payload']
        if isinstance(payload,str):payload=json.loads(payload)
        conn.execute(table.update().where(table.c.id==row['id']).values(natural_key=natural(payload)))
    with op.batch_alter_table('measurements') as batch:
        batch.alter_column('natural_key',existing_type=sa.String(64),nullable=False)
        batch.create_unique_constraint('uq_measurement_source_identity',['project_id','natural_key'])
    op.create_table('topology_timelines',sa.Column('id',sa.String(180),primary_key=True),
        sa.Column('project_id',sa.String(80),sa.ForeignKey('projects.id')),sa.Column('version',sa.String(80),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('payload',sa.JSON().with_variant(postgresql.JSONB(),'postgresql'),nullable=False))
def downgrade():
    op.drop_table('topology_timelines')
    with op.batch_alter_table('measurements') as batch:
        batch.drop_constraint('uq_measurement_source_identity',type_='unique')
        batch.drop_column('natural_key')
