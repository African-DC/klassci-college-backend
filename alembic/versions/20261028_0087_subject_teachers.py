"""Plusieurs enseignants par matière, dans l'ordre choisi.

Crée `subject_teachers` et y recopie l'enseignant unique de chaque matière
existante (position 0). `subjects.teacher_id` est CONSERVÉ : il reste égal au
premier enseignant, pour les lecteurs qui ne sont pas encore passés à
l'affectation par classe (bulletins, synthèse de classe, export enseignant,
fiche enseignant). Il ne sera retiré qu'une fois ces lecteurs migrés.

La migration est rejouable : la table n'est créée que si elle est absente,
et la recopie n'ajoute jamais deux fois le même couple matière / enseignant.

Revision ID: 0087_subject_teachers
Revises: 0086_level_lv2
Create Date: 2026-10-28
"""

import sqlalchemy as sa

from alembic import op

revision = "0087_subject_teachers"
down_revision = "0086_level_lv2"
branch_labels = None
depends_on = None

COPY_SQL = """
INSERT INTO subject_teachers (subject_id, teacher_id, position, created_at, updated_at)
SELECT s.id, s.teacher_id, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
FROM subjects s
WHERE s.teacher_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM subject_teachers st
      WHERE st.subject_id = s.id AND st.teacher_id = s.teacher_id
  )
"""


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("subject_teachers"):
        op.create_table(
            "subject_teachers",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("subject_id", sa.BigInteger(), nullable=False),
            sa.Column("teacher_id", sa.BigInteger(), nullable=False),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["teacher_id"], ["teacher_profiles.id"], ondelete="CASCADE"),
            sa.UniqueConstraint(
                "subject_id", "teacher_id", name="uq_subject_teachers_subject_teacher"
            ),
        )
        op.create_index("ix_subject_teachers_subject_id", "subject_teachers", ["subject_id"])
        op.create_index("ix_subject_teachers_teacher_id", "subject_teachers", ["teacher_id"])
    bind.execute(sa.text(COPY_SQL))


def downgrade() -> None:
    op.drop_table("subject_teachers")
