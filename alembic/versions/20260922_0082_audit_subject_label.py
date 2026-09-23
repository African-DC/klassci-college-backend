"""Journal d'audit : nommer le sujet de l'action et ses fiches liees.

Le journal savait dire qui avait agi, mais pas sur qui. Une ligne
« Modification · Inscription #42 » oblige a aller chercher ailleurs de quel
eleve il s'agit, et n'est plus dechiffrable du tout le jour ou la fiche est
supprimee.

Deux colonnes, remplies a l'ecriture comme `actor_email` l'est deja pour
l'auteur :

- `subject_label` : « Aminata Traore · 6e B », fige au moment de l'acte.
- `related_entities` : `[{type, id, label}]`, les autres fiches touchees.
  L'identifiant ouvre la fiche tant qu'elle existe, le libelle reste lisible
  quand elle a disparu.

Les lignes deja ecrites restent sans libelle : on ne peut pas reconstituer
l'etat de fiches qui ont pu bouger depuis, et un libelle d'aujourd'hui colle
sur un acte d'hier serait un faux. L'ecran affiche l'identifiant pour
celles-la, et le dit.

Revision ID: 0082_audit_subject_label
Revises: 0081_arrears_policy
Create Date: 2026-09-22
"""

import sqlalchemy as sa

from alembic import op

revision = "0082_audit_subject_label"
down_revision = "0081_arrears_policy"
branch_labels = None
depends_on = None


def _has_column(name: str) -> bool:
    return bool(
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = DATABASE() AND table_name = 'audit_logs' "
                "AND column_name = :name"
            ),
            {"name": name},
        )
        .scalar()
    )


def upgrade() -> None:
    if not _has_column("subject_label"):
        op.add_column("audit_logs", sa.Column("subject_label", sa.String(255), nullable=True))
    if not _has_column("related_entities"):
        op.add_column("audit_logs", sa.Column("related_entities", sa.JSON(), nullable=True))


def downgrade() -> None:
    for column_name in ("related_entities", "subject_label"):
        if _has_column(column_name):
            op.drop_column("audit_logs", column_name)
