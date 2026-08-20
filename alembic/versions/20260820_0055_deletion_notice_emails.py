"""A qui part le courriel de suppression.

Un journal d'audit vit dans la base : celui qui peut effacer une fiche peut,
en principe, atteindre la trace de son geste. Un courriel, lui, est deja
parti. Il dort dans une boite de reception, hors du logiciel.

Cette colonne dit a quelles adresses. Laissee vide, on retombe sur l'adresse
de l'etablissement, qui est celle du chef d'etablissement dans la quasi
totalite des colleges.

Revision ID: 0055_deletion_notice_emails
Revises: 0054_archive_permissions
Create Date: 2026-08-20
"""

import sqlalchemy as sa

from alembic import op

revision = "0055_deletion_notice_emails"
down_revision = "0054_archive_permissions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "school_settings",
        sa.Column("deletion_notice_emails", sa.String(500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("school_settings", "deletion_notice_emails")
