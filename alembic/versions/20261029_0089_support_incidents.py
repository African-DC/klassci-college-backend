"""Persist support incidents and their audit timeline in each tenant DB.

Revision ID: 0089_support_incidents
Revises: 0088_class_subject_teachers
"""
from alembic import op
import sqlalchemy as sa

revision = "0089_support_incidents"
down_revision = "0088_class_subject_teachers"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "support_incidents",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("reference", sa.String(16), nullable=True),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("source", sa.String(24), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("priority", sa.String(16), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_support_incidents_reference", "support_incidents", ["reference"])
    op.create_index("ix_support_incidents_status_created", "support_incidents", ["status", "created_at"])
    op.create_table(
        "support_incident_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("incident_id", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.BigInteger(), nullable=True),
        sa.Column("actor_kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(24), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["incident_id"], ["support_incidents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_support_incident_events_incident_id", "support_incident_events", ["incident_id"])
    op.execute(
        """INSERT IGNORE INTO permissions (slug, name) VALUES
        ('support:read', 'See school support incidents'),
        ('super-admin:incidents:read', 'Read platform support incidents'),
        ('super-admin:incidents:manage', 'Manage platform support incidents')"""
    )
    op.execute(
        """INSERT IGNORE INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
        WHERE r.name = 'super_admin' AND p.slug IN
        ('super-admin:incidents:read', 'super-admin:incidents:manage')"""
    )
    op.execute("""
        INSERT IGNORE INTO role_permissions (role_id, permission_id)
        SELECT rp.role_id, p_new.id FROM role_permissions rp
        JOIN permissions p_old ON p_old.id = rp.permission_id
        CROSS JOIN permissions p_new
        WHERE p_old.slug = 'audit:read' AND p_new.slug = 'support:read'
    """)

def downgrade() -> None:
    op.drop_table("support_incident_events")
    op.drop_table("support_incidents")
    op.execute("""
        DELETE rp FROM role_permissions rp JOIN permissions p ON rp.permission_id=p.id
        WHERE p.slug='support:read'
    """)
    op.execute(
        """DELETE rp FROM role_permissions rp JOIN permissions p ON rp.permission_id=p.id
        WHERE p.slug IN ('super-admin:incidents:read', 'super-admin:incidents:manage')"""
    )
    op.execute(
        "DELETE FROM permissions WHERE slug IN "
        "('support:read', 'super-admin:incidents:read', 'super-admin:incidents:manage')"
    )
