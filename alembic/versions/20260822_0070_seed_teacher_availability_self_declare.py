"""Seed la permission `timetable:availability:self_declare`.

L'enseignant peut desormais declarer lui-meme ses plages d'indisponibilite
depuis son portail. Cote administration, la saisie pour un tiers reste sous
`timetable:write`, deja accordee a admin, director et studies_director : chez
ROSTAN c'est le directeur des etudes qui note ce que l'enseignant lui a dit de
vive voix, ailleurs c'est le secretariat. D'ou une permission, pas un role.

Revision ID: 0070_availability_self
Revises: 0069_payment_methods
Create Date: 2026-08-22
"""

from alembic import op

revision = "0070_availability_self"
down_revision = "0069_payment_methods"
branch_labels = None
depends_on = None


_NEW_PERMISSIONS = [
    ("timetable:availability:self_declare", "Declare own availability"),
]

_ROLE_PERMISSION_MATRIX = {
    "teacher": ["timetable:availability:self_declare"],
    "admin": ["timetable:availability:self_declare"],
    "director": ["timetable:availability:self_declare"],
}


def upgrade() -> None:
    values_sql = ", ".join(f"('{slug}', '{name}')" for slug, name in _NEW_PERMISSIONS)
    op.execute(f"INSERT IGNORE INTO permissions (slug, name) VALUES {values_sql}")

    for role_name, slugs in _ROLE_PERMISSION_MATRIX.items():
        slugs_sql = ", ".join(f"'{slug}'" for slug in slugs)
        op.execute(
            f"""
            INSERT IGNORE INTO role_permissions (role_id, permission_id)
            SELECT r.id, p.id
            FROM roles r
            CROSS JOIN permissions p
            WHERE r.name = '{role_name}'
            AND p.slug IN ({slugs_sql})
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
