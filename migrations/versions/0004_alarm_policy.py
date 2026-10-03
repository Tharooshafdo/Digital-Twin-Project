"""Immutable versioned discrepancy policies."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision="0004"
down_revision="0003"
branch_labels=None
depends_on=None
def upgrade():
    op.create_table('alarm_policy_versions',sa.Column('id',sa.String(180),primary_key=True),
        sa.Column('project_id',sa.String(80),sa.ForeignKey('projects.id')),sa.Column('version',sa.String(80),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('payload',sa.JSON().with_variant(postgresql.JSONB(),'postgresql'),nullable=False))
def downgrade():op.drop_table('alarm_policy_versions')
