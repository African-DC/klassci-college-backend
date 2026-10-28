"""Enseignant par classe et par matière, choisi parmi les enseignants du niveau.

Crée `class_subject_teachers` : pour une classe et une matière, l'enseignant
retenu. Une ligne absente signifie « pas de choix explicite » : la résolution
prend alors l'unique enseignant du niveau, s'il n'y en a qu'un.

Aucune donnée n'est recopiée : tant qu'aucune classe n'a fait de choix, la
résolution se fait à partir de `subject_teachers` (migration 0087).

Pas d'année académique sur cette table, volontairement : ni `classes` ni
`subjects` n'en portent une, l'affectation vaut donc pour toute la vie de la
classe, comme le niveau et la série.

La migration est rejouable : la table n'est créée que si elle est absente.

Revision ID: 0088_class_subject_teachers
Revises: 0087_subject_teachers
Create Date: 2026-10-28
"""

import sqlalchemy as sa

from alembic import op

revision = "0088_class_subject_teachers"
down_revision = "0087_subject_teachers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("class_subject_teachers"):
        return
    op.create_table(
        "class_subject_teachers",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("class_id", sa.BigInteger(), nullable=False),
        sa.Column("subject_id", sa.BigInteger(), nullable=False),
        sa.Column("teacher_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["class_id"], ["classes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["teacher_id"], ["teacher_profiles.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "class_id", "subject_id", name="uq_class_subject_teachers_class_subject"
        ),
    )
    op.create_index("ix_class_subject_teachers_class_id", "class_subject_teachers", ["class_id"])
    op.create_index(
        "ix_class_subject_teachers_subject_id", "class_subject_teachers", ["subject_id"]
    )
    op.create_index(
        "ix_class_subject_teachers_teacher_id", "class_subject_teachers", ["teacher_id"]
    )


def downgrade() -> None:
    op.drop_table("class_subject_teachers")
