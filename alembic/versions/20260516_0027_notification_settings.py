"""Notification settings on school_settings (channels + types).

Ajoute 7 colonnes booleennes au singleton school_settings :
- 2 canaux : email, sms
- 5 types : grades, absences, payments, enrollment, reenrollment

Tous defaults a False pour preserver le comportement actuel (rien
n'envoye tant que l'admin n'a pas opte-in explicitement).

Revision ID: 0027
Revises: 0026
Create Date: 2026-05-16
"""

import sqlalchemy as sa

from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


_COLUMNS = [
    "notify_by_email",
    "notify_by_sms",
    "notify_grades",
    "notify_absences",
    "notify_payments",
    "notify_enrollment",
    "notify_reenrollment",
]


def upgrade() -> None:
    for col in _COLUMNS:
        op.add_column(
            "school_settings",
            sa.Column(col, sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    for col in reversed(_COLUMNS):
        op.drop_column("school_settings", col)
