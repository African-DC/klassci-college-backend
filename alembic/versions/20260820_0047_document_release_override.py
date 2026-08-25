"""Seed la permission `documents:release:override` (deroger a la retenue pour impaye).

Depuis le lot 4, certificat, attestation et bulletin sont retenus quand la
famille est en retard sur son echeancier. La direction doit pouvoir passer
outre — cas social, bourse promise, versement en especes pas encore saisi.

Accordee a `admin` et `director` seulement : la personne qui constate la
dette (caissier, comptable, secretariat) ne doit pas etre celle qui l'efface.
Chaque derogation exige un motif et laisse une trace dans le journal d'audit.

Revision ID: 0047_document_release_override
Revises: 0046_merge_trimester_categories
Create Date: 2026-08-20
"""

from alembic import op

revision = "0047_document_release_override"
down_revision = "0046_merge_trimester_categories"
branch_labels = None
depends_on = None


_NEW_PERMISSIONS = [
    ("documents:release:override", "Release a document despite arrears"),
]

_ROLE_PERMISSION_MATRIX = {
    "admin": ["documents:release:override"],
    "director": ["documents:release:override"],
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
