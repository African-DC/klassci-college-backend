"""Enseignants d'une matière : plusieurs par niveau, dans un ordre choisi."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.user import TeacherProfile


class SubjectTeacher(Base, TimestampMixin):
    """Rattachement d'un enseignant à une matière. `position` fixe l'ordre d'affichage."""

    __tablename__ = "subject_teachers"
    __table_args__ = (
        UniqueConstraint("subject_id", "teacher_id", name="uq_subject_teachers_subject_teacher"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    subject_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False
    )
    teacher_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("teacher_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    teacher: Mapped[TeacherProfile] = relationship(foreign_keys=[teacher_id])
