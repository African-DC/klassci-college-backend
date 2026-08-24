"""Sessions de caisse — journée de guichet d'un caissier.

Crée `cash_sessions` (une ligne par caissier et par jour) et seede les quatre
permissions qui cloisonnent la caisse :

- `payments:read:all` — lire le journal de toutes les caisses. Sans elle, un
  utilisateur qui a `payments:read` ne voit que ses propres encaissements.
- `payments:cancel:any` — corriger n'importe quel versement, même sur une
  journée clôturée.
- `cash-session:manage` — ouvrir et clôturer sa propre journée.
- `cash-session:read:all` — point journalier de toutes les caisses.

Le rattachement d'un versement à une session est dérivé de
(`received_by`, date de `created_at`) : pas de colonne ajoutée sur `payments`,
donc pas de backfill ni de seconde source de vérité.

Revision ID: 0043_cash_sessions
Revises: 0042_metier_roles
Create Date: 2026-08-20
"""

import sqlalchemy as sa

from alembic import op

revision = "0043_cash_sessions"
down_revision = "0042_metier_roles"
branch_labels = None
depends_on = None


_NEW_PERMISSIONS = [
    ("payments:read:all", "View every cashier's payments"),
    ("payments:cancel:any", "Cancel any payment, including a closed day"),
    ("cash-session:manage", "Open and close one's own cash day"),
    ("cash-session:read:all", "View every cash day (daily reconciliation)"),
]

# `cashier` reçoit `cash-session:manage` mais NI `payments:read:all` NI
# `cash-session:read:all` : c'est cette absence qui le cantonne à sa caisse.
_ROLE_PERMISSION_MATRIX: dict[str, list[str]] = {
    "admin": [s for s, _ in _NEW_PERMISSIONS],
    "director": [s for s, _ in _NEW_PERMISSIONS],
    "accountant": [
        "payments:read:all",
        "payments:cancel:any",
        "cash-session:read:all",
    ],
    "staff": [
        "payments:read:all",
        "cash-session:read:all",
        "cash-session:manage",
    ],
    "cashier": ["cash-session:manage"],
}


def _quote(value: str) -> str:
    return value.replace("'", "''")


def upgrade() -> None:
    op.create_table(
        "cash_sessions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("cashier_user_id", sa.BigInteger(), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("opened_at", sa.DateTime(), nullable=False),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("counted_amount", sa.Numeric(15, 2), nullable=True),
        sa.Column("expected_amount", sa.Numeric(15, 2), nullable=True),
        sa.Column("variance", sa.Numeric(15, 2), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["cashier_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        # Une seule journée par caissier : c'est cette contrainte qui permet de
        # dériver la session d'un versement sans la stocker.
        sa.UniqueConstraint(
            "cashier_user_id", "business_date", name="uq_cash_session_cashier_date"
        ),
    )
    op.create_index("idx_cash_sessions_business_date", "cash_sessions", ["business_date"])
    op.create_index("idx_cash_sessions_status", "cash_sessions", ["status"])

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

    op.drop_index("idx_cash_sessions_status", table_name="cash_sessions")
    op.drop_index("idx_cash_sessions_business_date", table_name="cash_sessions")
    op.drop_table("cash_sessions")
