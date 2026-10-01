"""Fiche de renseignements : les champs que l'inscription ne portait pas.

Le comptable remplit, classe par classe, une fiche de seize colonnes. Six
d'entre elles n'existaient nulle part dans KLASSCI : niveau et série de
l'année précédente, qualité (redoublant ou non), LV2, discipline artistique,
et la nationalité de l'élève. Elles arrivent ici, toutes facultatives.

Rien n'est rempli d'office. Une colonne à `NULL` veut dire « pas renseigné »,
et c'est la seule valeur honnête pour les inscriptions déjà en base : déduire
un redoublement d'un historique que l'école n'a pas déclaré complet serait
faux dès le premier dossier ressaisi.

L'index unique sur `scholarships.enrollment_id` borne la bourse à une par
inscription, ce que la fiche suppose (une seule case « régime »). La table
était vide en production au moment de l'écrire. Si une base portait déjà deux
bourses sur une même inscription, la création de l'index échouerait : c'est
voulu, il faut alors trancher à la main laquelle garder.

Le droit `scholarships:manage` est semé aux rôles `admin` et `director`,
comme `performance:read` l'a été par la migration 0034.

Revision ID: 0084_information_sheet
Revises: 0083_payment_idempotency_key
Create Date: 2026-10-01
"""

import sqlalchemy as sa

from alembic import op

revision = "0084_information_sheet"
down_revision = "0083_payment_idempotency_key"
branch_labels = None
depends_on = None

_SCHOLARSHIP_INDEX = "uq_scholarships_enrollment_id"

_NEW_PERMISSIONS = [
    ("scholarships:manage", "Grant or remove a scholarship"),
]

_ROLE_PERMISSION_MATRIX = {
    "admin": ["scholarships:manage"],
    "director": ["scholarships:manage"],
}

_ENROLLMENT_COLUMN_NAMES = (
    "previous_level",
    "previous_series",
    "is_repeater",
    "lv2",
    "artistic_discipline",
)


def _enrollment_columns() -> tuple[sa.Column, ...]:
    """Colonnes neuves, construites à chaque appel : une `Column` ne s'attache qu'une fois."""
    return (
        sa.Column(
            "previous_level",
            sa.Enum("CM2", "6E", "5E", "4E", "3E", "2NDE", "1RE", "TLE", name="previous_level"),
            nullable=True,
        ),
        sa.Column("previous_series", sa.String(20), nullable=True),
        sa.Column("is_repeater", sa.Boolean(), nullable=True),
        sa.Column("lv2", sa.Enum("allemand", "espagnol", name="lv2"), nullable=True),
        sa.Column(
            "artistic_discipline",
            sa.Enum("arts_plastiques", "musique", name="artistic_discipline"),
            nullable=True,
        ),
    )


def upgrade() -> None:
    for column in _enrollment_columns():
        op.add_column("enrollments", column)
    op.add_column("students", sa.Column("nationality", sa.String(60), nullable=True))
    op.create_index(_SCHOLARSHIP_INDEX, "scholarships", ["enrollment_id"], unique=True)
    _seed_permissions()


def downgrade() -> None:
    _unseed_permissions()
    op.drop_index(_SCHOLARSHIP_INDEX, table_name="scholarships")
    op.drop_column("students", "nationality")
    for name in reversed(_ENROLLMENT_COLUMN_NAMES):
        op.drop_column("enrollments", name)


def _seed_permissions() -> None:
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


def _unseed_permissions() -> None:
    slugs_sql = ", ".join(f"'{slug}'" for slug, _ in _NEW_PERMISSIONS)
    op.execute(
        f"""
        DELETE rp FROM role_permissions rp
        JOIN permissions p ON rp.permission_id = p.id
        WHERE p.slug IN ({slugs_sql})
        """
    )
    op.execute(f"DELETE FROM permissions WHERE slug IN ({slugs_sql})")
