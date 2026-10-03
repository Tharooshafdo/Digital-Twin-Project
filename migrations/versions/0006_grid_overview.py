"""Geographic locations and source-separated grid observations."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None

def upgrade():
    for name in ('asset_locations', 'grid_observations'):
        op.create_table(name,
            sa.Column('id', sa.String(180), primary_key=True),
            sa.Column('project_id', sa.String(80), sa.ForeignKey('projects.id')),
            sa.Column('version', sa.String(80), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('payload', sa.JSON().with_variant(postgresql.JSONB(), 'postgresql'), nullable=False))
        op.create_index('ix_'+name+'_project_created', name, ['project_id', 'created_at'])

def downgrade():
    for name in ('grid_observations', 'asset_locations'):
        op.drop_index('ix_'+name+'_project_created', table_name=name)
        op.drop_table(name)
