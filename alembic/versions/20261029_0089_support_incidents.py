"""Persist support incidents and their audit timeline in each tenant DB.

Crée `support_incidents` et `support_incident_events`, ainsi que les trois
droits de l'assistance. Le droit `support:read` est accordé à qui lit déjà le
journal d'audit, comme le prévoit la matrice de rôles.

La migration est rejouable : chaque table n'est créée que si elle est absente,
chaque index n'est créé que s'il manque, et les droits sont insérés sans doublon.

Revision ID: 0089_support_incidents
Revises: 0088_class_subject_teachers
"""

import sqlalchemy as sa

from alembic import op

revision = "0089_support_incidents"
down_revision = "0088_class_subject_teachers"
branch_labels = None
depends_on = None

INCIDENTS = "support_incidents"
EVENTS = "support_incident_events"
INDEXES = {
    INCIDENTS: {
        "ix_support_incidents_reference": ["reference"],
        "ix_support_incidents_status_created": ["status", "created_at"],
    },
    EVENTS: {
        "ix_support_incident_events_incident_id": ["incident_id"],
    },
}


def _ensure_indexes(bind: sa.Connection) -> None:
    """Crée chaque index absent, et laisse les autres en place."""
    inspector = sa.inspect(bind)
    for table, wanted in INDEXES.items():
        existing = {ix["name"] for ix in inspector.get_indexes(table)}
        for name, columns in wanted.items():
            if name not in existing:
                op.create_index(name, table, columns)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(INCIDENTS):
        op.create_table(
            INCIDENTS,
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
    if not inspector.has_table(EVENTS):
        op.create_table(
            EVENTS,
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("incident_id", sa.String(32), nullable=False),
            sa.Column("actor_id", sa.BigInteger(), nullable=True),
            sa.Column("actor_kind", sa.String(16), nullable=False),
            sa.Column("status", sa.String(24), nullable=True),
            sa.Column("message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["incident_id"], [f"{INCIDENTS}.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        )
    _ensure_indexes(bind)
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
    op.execute(
        """INSERT IGNORE INTO role_permissions (role_id, permission_id)
        SELECT rp.role_id, p_new.id FROM role_permissions rp
        JOIN permissions p_old ON p_old.id = rp.permission_id
        CROSS JOIN permissions p_new
        WHERE p_old.slug = 'audit:read' AND p_new.slug = 'support:read'"""
    )


def downgrade() -> None:
    op.drop_table(EVENTS)
    op.drop_table(INCIDENTS)
    op.execute(
        """DELETE rp FROM role_permissions rp JOIN permissions p ON rp.permission_id=p.id
        WHERE p.slug IN ('support:read', 'super-admin:incidents:read', 'super-admin:incidents:manage')"""
    )
    op.execute(
        "DELETE FROM permissions WHERE slug IN "
        "('support:read', 'super-admin:incidents:read', 'super-admin:incidents:manage')"
    )
