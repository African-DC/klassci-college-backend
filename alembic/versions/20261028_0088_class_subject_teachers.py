"""Enseignant par classe et par matière, choisi parmi les enseignants du niveau.

Crée `class_subject_teachers` : pour une classe et une matière, l'enseignant
retenu. Une ligne absente signifie « pas de choix explicite » : la résolution
prend alors l'unique enseignant du niveau, s'il n'y en a qu'un.

Aucune donnée n'est recopiée : tant qu'aucune classe n'a fait de choix, la
résolution se fait à partir de `subject_teachers` (migration 0087).

Pas d'année académique sur cette table, volontairement : ni `classes` ni
`subjects` n'en portent une, l'affectation vaut donc pour toute la vie de la
classe, comme le niveau et la série.

La migration est rejouable : la table n'est créée que si elle est absente,
et chaque index n'est créé que s'il manque. L'index unique (class_id,
subject_id) couvre déjà les recherches par classe, d'où l'absence d'index
dédié sur class_id.

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

TABLE = "class_subject_teachers"
INDEXES = {
    "ix_class_subject_teachers_subject_id": "subject_id",
    "ix_class_subject_teachers_teacher_id": "teacher_id",
}


def _ensure_indexes(bind: sa.Connection) -> None:
    """Crée chaque index absent de `class_subject_teachers`, et laisse les autres en place."""
    existing = {ix["name"] for ix in sa.inspect(bind).get_indexes(TABLE)}
    for name, column in INDEXES.items():
        if name not in existing:
            bind.execute(sa.text(f"CREATE INDEX {name} ON {TABLE} ({column})"))


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(TABLE):
        op.create_table(
            TABLE,
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
    _ensure_indexes(bind)


def downgrade() -> None:
    op.drop_table(TABLE)
