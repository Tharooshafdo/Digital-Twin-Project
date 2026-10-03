"""Index project audit history; populated data retained."""
from alembic import op
revision = "0002"
down_revision = "db9c94423c4d"
branch_labels = None
depends_on = None
def upgrade():
    op.create_index("ix_audit_project_time", "audit_events", ["project_id", "created_at"])
def downgrade():
    op.drop_index("ix_audit_project_time", table_name="audit_events")
