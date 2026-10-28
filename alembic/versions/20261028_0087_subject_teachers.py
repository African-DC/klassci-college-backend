"""Plusieurs enseignants par matière, dans l'ordre choisi.

Crée `subject_teachers` et y recopie l'enseignant unique de chaque matière
existante (position 0). `subjects.teacher_id` est CONSERVÉ : il reste égal au
premier enseignant, pour les lecteurs qui ne sont pas encore passés à
l'affectation par classe (bulletins, synthèse de classe, export enseignant,
fiche enseignant). Il ne sera retiré qu'une fois ces lecteurs migrés.

La migration est rejouable : la table n'est créée que si elle est absente,
chaque index n'est créé que s'il manque, et la recopie n'ajoute jamais deux
fois le même couple matière / enseignant. L'index unique (subject_id,
teacher_id) couvre déjà les recherches par matière, d'où l'absence d'index
dédié sur subject_id.

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

TABLE = "subject_teachers"
TEACHER_INDEX = "ix_subject_teachers_teacher_id"

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


def _ensure_indexes(bind: sa.Connection) -> None:
    """Crée chaque index absent de `subject_teachers`, et laisse les autres en place."""
    existing = {ix["name"] for ix in sa.inspect(bind).get_indexes(TABLE)}
    if TEACHER_INDEX not in existing:
        bind.execute(sa.text(f"CREATE INDEX {TEACHER_INDEX} ON {TABLE} (teacher_id)"))


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(TABLE):
        op.create_table(
            TABLE,
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
    _ensure_indexes(bind)
    bind.execute(sa.text(COPY_SQL))


def downgrade() -> None:
    op.drop_table(TABLE)
