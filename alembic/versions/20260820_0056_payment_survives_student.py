"""Un versement survit a l'eleve.

La caissiere avait compte ces billets. Le tiroir etait juste ce soir-la, le
point journalier a ete signe, le bordereau est classe. Supprimer les
versements d'un eleve ferait mentir tous ces documents d'un coup, sans que
personne ne s'en apercoive avant le prochain controle.

D'ou `enrollment_id` nullable — un versement peut n'etre rattache a aucune
inscription — et les deux colonnes d'identite figee, recopiees sur le
versement avant que la fiche ne parte, pour que le bordereau reste lisible
une fois l'eleve disparu.

Rien n'est detruit ici : trois colonnes ajoutees, une contrainte assouplie.
Le `downgrade` resserre `enrollment_id` en NOT NULL et echouerait donc s'il
restait des versements orphelins — c'est voulu, on ne supprime pas
silencieusement une ligne de caisse pour faire passer un rollback.

Revision ID: 0056_payment_survives_student
Revises: 0055_deletion_notice_emails
Create Date: 2026-08-20
"""

import sqlalchemy as sa

from alembic import op

revision = "0056_payment_survives_student"
down_revision = "0055_deletion_notice_emails"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "payments",
        sa.Column("student_name_snapshot", sa.String(200), nullable=True),
    )
    op.add_column(
        "payments",
        sa.Column("student_matricule_snapshot", sa.String(50), nullable=True),
    )
    # MySQL exige le type complet pour un ALTER de nullabilite. La cle
    # etrangere reste en place : on n'autorise que l'absence de lien.
    op.alter_column(
        "payments",
        "enrollment_id",
        existing_type=sa.BigInteger(),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "payments",
        "enrollment_id",
        existing_type=sa.BigInteger(),
        nullable=False,
    )
    op.drop_column("payments", "student_matricule_snapshot")
    op.drop_column("payments", "student_name_snapshot")
