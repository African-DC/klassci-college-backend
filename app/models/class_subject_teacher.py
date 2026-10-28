"""Enseignant retenu pour une matière dans une classe donnée."""

from __future__ import annotations

from sqlalchemy import BigInteger, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin


class ClassSubjectTeacher(Base, TimestampMixin):
    """Choix explicite de l'enseignant d'une matière pour une classe.

    Absente = pas de choix : la résolution se fait dans `class_subject_teacher_service`.
    """

    __tablename__ = "class_subject_teachers"
    __table_args__ = (
        UniqueConstraint("class_id", "subject_id", name="uq_class_subject_teachers_class_subject"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    class_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("classes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subject_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    teacher_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("teacher_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
