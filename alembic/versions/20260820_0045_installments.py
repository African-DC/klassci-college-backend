"""Tranches de paiement et moyens de paiement acceptes.

Cree `fee_installments` (grille de l'etablissement, en pourcentages du total
obligatoire) et `enrollment_installments` (accord negocie avec une famille, en
montants fermes), plus la colonne des moyens de paiement acceptes.

Une tranche n'est PAS une categorie de frais : le trimestre est un moment de
paiement, pas une nature de frais. Les categories restent des natures, les
tranches decoupent le total dans le temps.

La fusion des categories « Scolarite Trimestre N » en une categorie
« Scolarite » n'est volontairement PAS faite ici : elle touche des donnees de
production et merite sa propre migration verifiee. Les tranches fonctionnent
sans elle, puisqu'elles portent sur le TOTAL des frais obligatoires quel que
soit le nombre de categories qui le composent.

Revision ID: 0045_installments
Revises: 0044_backfill_cash_sessions
Create Date: 2026-08-20
"""

import sqlalchemy as sa

from alembic import op

revision = "0045_installments"
down_revision = "0044_backfill_cash_sessions"
branch_labels = None
depends_on = None


_NEW_PERMISSIONS = [
    ("admin:fee-installments:read", "View the instalment grid"),
    ("admin:fee-installments:write", "Set the instalment grid"),
    ("enrollments:schedule:write", "Negotiate a family payment plan"),
]

# Lire les echeances sert a repondre a une famille au guichet : tout poste en
# contact avec les parents l'obtient. Les modifier est une decision financiere.
_ROLE_PERMISSION_MATRIX: dict[str, list[str]] = {
    "admin": [s for s, _ in _NEW_PERMISSIONS],
    "director": [s for s, _ in _NEW_PERMISSIONS],
    "accountant": [s for s, _ in _NEW_PERMISSIONS],
    "staff": ["admin:fee-installments:read"],
    "cashier": ["admin:fee-installments:read"],
    "educator": ["admin:fee-installments:read"],
}


def _quote(value: str) -> str:
    return value.replace("'", "''")


def upgrade() -> None:
    op.create_table(
        "fee_installments",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("academic_year_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("percentage", sa.Numeric(5, 2), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["academic_year_id"], ["academic_years.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "academic_year_id", "position", name="uq_fee_installment_year_position"
        ),
    )
    op.create_index("idx_fee_installments_year", "fee_installments", ["academic_year_id"])

    op.create_table(
        "enrollment_installments",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("enrollment_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["enrollment_id"], ["enrollments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "enrollment_id", "position", name="uq_enrollment_installment_enrollment_position"
        ),
    )
    op.create_index(
        "idx_enrollment_installments_enrollment", "enrollment_installments", ["enrollment_id"]
    )

    # NULL = tous les moyens acceptes, ce qui preserve le comportement des
    # etablissements deja en service.
    op.add_column(
        "school_settings",
        sa.Column("enabled_payment_methods", sa.String(length=200), nullable=True),
    )

    values_sql = ", ".join(f"('{_quote(s)}', '{_quote(n)}')" for s, n in _NEW_PERMISSIONS)
    op.execute(f"INSERT IGNORE INTO permissions (slug, name) VALUES {values_sql}")

    for role_name, slugs in _ROLE_PERMISSION_MATRIX.items():
        slugs_sql = ", ".join(f"'{_quote(slug)}'" for slug in sorted(set(slugs)))
        op.execute(
            f"""
            INSERT IGNORE INTO role_permissions (role_id, permission_id)
            SELECT r.id, p.id
            FROM roles r
            CROSS JOIN permissions p
            WHERE r.name = '{_quote(role_name)}'
            AND p.slug IN ({slugs_sql})
            """
        )


def downgrade() -> None:
    slugs_sql = ", ".join(f"'{_quote(s)}'" for s, _ in _NEW_PERMISSIONS)
    op.execute(
        f"""
        DELETE rp FROM role_permissions rp
        JOIN permissions p ON p.id = rp.permission_id
        WHERE p.slug IN ({slugs_sql})
        """
    )
    op.execute(f"DELETE FROM permissions WHERE slug IN ({slugs_sql})")

    op.drop_column("school_settings", "enabled_payment_methods")
    op.drop_index("idx_enrollment_installments_enrollment", table_name="enrollment_installments")
    op.drop_table("enrollment_installments")
    op.drop_index("idx_fee_installments_year", table_name="fee_installments")
    op.drop_table("fee_installments")
