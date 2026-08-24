"""Où mène une notification : l'écran sur lequel on fait ce qu'elle annonce.

`entity_type` et `entity_id` disaient de quoi il s'agissait, jamais où aller.
Le lien est posé par le serveur, qui est seul à savoir quelle action il attend
puisque c'est lui qui a décidé de prévenir.

Revision ID: 0072_notification_action_url
Revises: 0071_cancel_reason
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0072_notification_action_url"
down_revision: str | None = "0071_cancel_reason"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("action_url", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("notifications", "action_url")
