"""Table notification_preferences (canaux email / SMS par utilisateur).

L'in-app (cloche) est toujours actif ; l'utilisateur choisit de recevoir en
plus les notifications par email et/ou SMS depuis son profil.

Revision ID: 0035_notification_prefs
Revises: 0034_performance_perm
Create Date: 2026-07-03
"""

import sqlalchemy as sa

from alembic import op

revision = "0035_notification_prefs"
down_revision = "0034_performance_perm"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_preferences",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("email", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("sms", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index(
        "idx_notification_preferences_user_id", "notification_preferences", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("idx_notification_preferences_user_id", table_name="notification_preferences")
    op.drop_table("notification_preferences")
