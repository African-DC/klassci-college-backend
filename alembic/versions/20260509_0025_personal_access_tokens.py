"""Personal Access Tokens for CLI / AI agent authentication.

Long-lived but mandatory-expiring credentials, scoped to a subset of
permissions and a single user. Replaces JWT for non-interactive callers.

Token format on the wire: `klc_pat_<32 hex>` (40 chars total).
Stored: sha256 hex hash of the full token (deterministic lookup) +
display prefix (first 12 chars) for safe UI rendering.

Revision ID: 0025
Revises: 0024
Create Date: 2026-05-09
"""

import sqlalchemy as sa

from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "personal_access_tokens",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("token_prefix", sa.String(16), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
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
    )
    op.create_index("uq_pat_token_hash", "personal_access_tokens", ["token_hash"], unique=True)
    op.create_index("idx_pat_user_id", "personal_access_tokens", ["user_id"])
    op.create_index("idx_pat_expires_at", "personal_access_tokens", ["expires_at"])


def downgrade() -> None:
    # ``op.drop_table`` cascades the foreign-key + indexes; explicit
    # ``op.drop_index`` calls would fail with MySQL 1553 because the
    # user_id index backs the FK and cannot be dropped while it exists.
    op.drop_table("personal_access_tokens")
