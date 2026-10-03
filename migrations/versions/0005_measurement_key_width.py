"""Allow maximum project-scoped measurement identity width."""
from alembic import op
import sqlalchemy as sa
revision="0005"
down_revision="0004"
branch_labels=None
depends_on=None
def upgrade():
    with op.batch_alter_table('measurements') as batch:
        batch.alter_column('id',existing_type=sa.String(150),type_=sa.String(240),existing_nullable=False)
def downgrade():
    with op.batch_alter_table('measurements') as batch:
        batch.alter_column('id',existing_type=sa.String(240),type_=sa.String(150),existing_nullable=False)
