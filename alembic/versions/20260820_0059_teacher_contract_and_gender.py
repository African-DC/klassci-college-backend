"""Type de contrat et sexe des enseignants.

La synthese DRENA du rapport de fin de trimestre distingue permanents,
vacataires et fonctionnaires, et ventile par sexe. Sans ces deux colonnes,
deux tableaux du rapport officiel restent vierges.

Les colonnes sont nulles : on ne devine ni le sexe ni le contrat de
quelqu'un, et un defaut arbitraire ferait dire au rapport une chose que
personne n'a constatee.

Revision ID: 0059_teacher_contract_and_gender
Revises: 0058_deep_trimester_report_data
Create Date: 2026-08-20
"""

import sqlalchemy as sa

from alembic import op

revision = "0059_teacher_contract_and_gender"
down_revision = "0058_deep_trimester_report_data"
branch_labels = None
depends_on = None

_CONTRACT = sa.Enum("permanent", "vacataire", "fonctionnaire", name="teacher_contract")


def upgrade() -> None:
    op.add_column("teacher_profiles", sa.Column("genre", sa.String(1), nullable=True))
    op.add_column("teacher_profiles", sa.Column("contract_type", _CONTRACT, nullable=True))


def downgrade() -> None:
    op.drop_column("teacher_profiles", "contract_type")
    op.drop_column("teacher_profiles", "genre")
