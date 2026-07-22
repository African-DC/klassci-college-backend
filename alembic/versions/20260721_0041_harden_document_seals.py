"""Harden institutional document seals.

Revision ID: 0041_harden_document_seals
Revises: 0040_account_management
Create Date: 2026-07-21
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.mysql import LONGBLOB

from alembic import op

revision = "0041_harden_document_seals"
down_revision = "0040_account_management"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("document_issuances", sa.Column("seal_code", sa.String(40), nullable=True))
    op.add_column(
        "document_issuances",
        sa.Column("scheme_version", sa.String(16), server_default="KCEV1", nullable=False),
    )
    op.add_column(
        "document_issuances", sa.Column("signature_algorithm", sa.String(32), nullable=True)
    )
    op.add_column("document_issuances", sa.Column("key_id", sa.String(64), nullable=True))
    op.add_column("document_issuances", sa.Column("document_sha256", sa.String(64), nullable=True))
    op.add_column("document_issuances", sa.Column("source_sha256", sa.String(64), nullable=True))
    op.add_column("document_issuances", sa.Column("signature", sa.String(128), nullable=True))
    op.add_column(
        "document_issuances",
        sa.Column(
            "pdf_content",
            sa.LargeBinary(length=20 * 1024 * 1024).with_variant(LONGBLOB(), "mysql"),
            nullable=True,
        ),
    )
    op.add_column("document_issuances", sa.Column("pdf_size", sa.Integer(), nullable=True))
    op.add_column(
        "document_issuances",
        sa.Column("status", sa.String(20), server_default="active", nullable=False),
    )
    op.add_column(
        "document_issuances",
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column("document_issuances", sa.Column("expires_at", sa.DateTime(), nullable=True))
    op.add_column("document_issuances", sa.Column("finalized_at", sa.DateTime(), nullable=True))
    op.add_column("document_issuances", sa.Column("failed_at", sa.DateTime(), nullable=True))
    op.add_column("document_issuances", sa.Column("failure_reason", sa.String(500), nullable=True))
    op.add_column("document_issuances", sa.Column("revoked_at", sa.DateTime(), nullable=True))
    op.add_column("document_issuances", sa.Column("revoked_by_id", sa.BigInteger(), nullable=True))
    op.add_column(
        "document_issuances", sa.Column("revocation_reason", sa.String(500), nullable=True)
    )
    op.add_column("document_issuances", sa.Column("supersedes_id", sa.BigInteger(), nullable=True))
    op.add_column(
        "document_issuances", sa.Column("superseded_by_id", sa.BigInteger(), nullable=True)
    )

    # MySQL 8 window functions keep the historical backfill bounded and set-based.
    op.execute(
        """
        CREATE TEMPORARY TABLE document_issuance_lineage AS
        SELECT
            id,
            ROW_NUMBER() OVER lineage AS lineage_revision,
            LAG(id) OVER lineage AS previous_id,
            LEAD(id) OVER lineage AS next_id
        FROM document_issuances
        WINDOW lineage AS (
            PARTITION BY document_type, reference
            ORDER BY issued_at, id
        )
        """
    )
    op.execute(
        """
        UPDATE document_issuances AS issuance
        INNER JOIN document_issuance_lineage AS lineage ON lineage.id = issuance.id
        SET
            issuance.revision = lineage.lineage_revision,
            issuance.status = IF(lineage.next_id IS NULL, 'active', 'superseded'),
            issuance.supersedes_id = lineage.previous_id,
            issuance.superseded_by_id = lineage.next_id
        """
    )
    op.execute("DROP TEMPORARY TABLE document_issuance_lineage")

    op.create_index(
        "ix_document_issuances_seal_code", "document_issuances", ["seal_code"], unique=True
    )
    op.create_index("ix_document_issuances_status", "document_issuances", ["status"], unique=False)
    op.create_index(
        "ix_document_issuances_reference_version",
        "document_issuances",
        ["document_type", "reference", "revision"],
        unique=True,
    )
    op.create_foreign_key(
        "fk_document_issuances_supersedes",
        "document_issuances",
        "document_issuances",
        ["supersedes_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_document_issuances_superseded_by",
        "document_issuances",
        "document_issuances",
        ["superseded_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_document_issuances_revoked_by",
        "document_issuances",
        "users",
        ["revoked_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute(
        "INSERT IGNORE INTO permissions (slug, name) VALUES "
        "('documents:revoke', 'Revoke institutional document seals')"
    )
    op.execute(
        """
        INSERT IGNORE INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permissions p
        WHERE r.name IN ('admin', 'director')
        AND p.slug = 'documents:revoke'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE rp FROM role_permissions rp
        JOIN permissions p ON rp.permission_id = p.id
        WHERE p.slug = 'documents:revoke'
        """
    )
    op.execute("DELETE FROM permissions WHERE slug = 'documents:revoke'")
    op.drop_constraint("fk_document_issuances_revoked_by", "document_issuances", type_="foreignkey")
    op.drop_constraint(
        "fk_document_issuances_superseded_by", "document_issuances", type_="foreignkey"
    )
    op.drop_constraint("fk_document_issuances_supersedes", "document_issuances", type_="foreignkey")
    op.drop_index("ix_document_issuances_reference_version", table_name="document_issuances")
    op.drop_index("ix_document_issuances_status", table_name="document_issuances")
    op.drop_index("ix_document_issuances_seal_code", table_name="document_issuances")
    for column in (
        "superseded_by_id",
        "supersedes_id",
        "revocation_reason",
        "revoked_by_id",
        "revoked_at",
        "failure_reason",
        "failed_at",
        "finalized_at",
        "expires_at",
        "revision",
        "status",
        "signature",
        "pdf_size",
        "pdf_content",
        "document_sha256",
        "source_sha256",
        "key_id",
        "signature_algorithm",
        "scheme_version",
        "seal_code",
    ):
        op.drop_column("document_issuances", column)
