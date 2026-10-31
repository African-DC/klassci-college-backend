"""School schedule events — revision 0090, per-tenant recurring periods.

Revision ID: 0090_schedule_events
Revises: 0089_support_incidents
"""
from alembic import op
import sqlalchemy as sa

revision = "0090_schedule_events"
down_revision = "0089_support_incidents"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if sa.inspect(bind).has_table("schedule_events"):
        return
    op.create_table(
        "schedule_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("academic_year_id", sa.BigInteger(), nullable=False),
        sa.Column("class_id", sa.BigInteger(), nullable=True),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("category", sa.String(24), nullable=False),
        sa.Column("blocks_courses", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("day", sa.String(12), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("end_time > start_time", name="ck_schedule_events_valid_time_range"),
        sa.ForeignKeyConstraint(["academic_year_id"], ["academic_years.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["class_id"], ["classes.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_schedule_events_academic_year_id", "schedule_events", ["academic_year_id"])
    op.create_index("ix_schedule_events_class_id", "schedule_events", ["class_id"])
    op.create_index("ix_schedule_events_day_start", "schedule_events", ["day", "start_time"])


def downgrade():
    op.drop_table("schedule_events")
