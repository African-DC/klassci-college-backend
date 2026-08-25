"""Demandes de congé : table leave_requests + permissions leave:request / leave:approve.

Revision ID: 0037_leave_requests
Revises: 0036_student_documents
Create Date: 2026-07-03
"""

import sqlalchemy as sa

from alembic import op

revision = "0037_leave_requests"
down_revision = "0036_student_documents"
branch_labels = None
depends_on = None


_NEW_PERMISSIONS = [
    ("leave:request", "Request leave"),
    ("leave:approve", "Approve or reject leave requests"),
]

_ROLE_PERMISSION_MATRIX = {
    "admin": ["leave:request", "leave:approve"],
    "director": ["leave:request", "leave:approve"],
    "teacher": ["leave:request"],
    "staff": ["leave:request"],
}


def upgrade() -> None:
    op.create_table(
        "leave_requests",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "leave_type",
            sa.Enum(
                "annual", "sick", "maternity", "exceptional", "training", "other", name="leave_type"
            ),
            nullable=False,
        ),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("pending", "approved", "rejected", "cancelled", name="leave_status"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("reviewed_by", sa.BigInteger(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_leave_requests_user_id", "leave_requests", ["user_id"])
    op.create_index("idx_leave_requests_status", "leave_requests", ["status"])

    values_sql = ", ".join(f"('{slug}', '{name}')" for slug, name in _NEW_PERMISSIONS)
    op.execute(f"INSERT IGNORE INTO permissions (slug, name) VALUES {values_sql}")
    for role_name, slugs in _ROLE_PERMISSION_MATRIX.items():
        slugs_sql = ", ".join(f"'{slug}'" for slug in slugs)
        op.execute(
            f"""
            INSERT IGNORE INTO role_permissions (role_id, permission_id)
            SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
            WHERE r.name = '{role_name}' AND p.slug IN ({slugs_sql})
            """
        )


def downgrade() -> None:
    slugs_sql = ", ".join(f"'{slug}'" for slug, _ in _NEW_PERMISSIONS)
    op.execute(
        f"""
        DELETE rp FROM role_permissions rp
        JOIN permissions p ON rp.permission_id = p.id
        WHERE p.slug IN ({slugs_sql})
        """
    )
    op.execute(f"DELETE FROM permissions WHERE slug IN ({slugs_sql})")
    op.drop_table("leave_requests")
