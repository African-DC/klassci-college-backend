"""Modèles utilisateurs : User, profils (Staff, Teacher), Student, Parent."""

from __future__ import annotations

import enum
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.archivable import ArchivableMixin
from app.models.base import TimestampMixin, ValueEnum

if TYPE_CHECKING:
    from app.models.enrollment import Enrollment
    from app.models.grade import Grade
    from app.models.notification import Notification
    from app.models.permission import UserRole


class UserRoleEnum(str, enum.Enum):
    """Rôle fonctionnel de l'utilisateur dans la plateforme."""

    ADMIN = "admin"
    TEACHER = "teacher"
    STAFF = "staff"
    STUDENT = "student"
    PARENT = "parent"
    SUPER_ADMIN = "super_admin"


class Genre(str, enum.Enum):
    M = "M"
    F = "F"


# ---------------------------------------------------------------------------
# User (compte de connexion)
# ---------------------------------------------------------------------------


class User(Base, TimestampMixin):
    """Compte de connexion — toute personne pouvant se connecter à la plateforme."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(
        ValueEnum(UserRoleEnum, name="user_role"),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Vrai quand le compte a un mot de passe temporaire (création par un admin
    # ou réinitialisation) : l'utilisateur doit le changer à la 1re connexion.
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Relations
    staff_profile: Mapped[StaffProfile | None] = relationship(back_populates="user", uselist=False)
    teacher_profile: Mapped[TeacherProfile | None] = relationship(
        back_populates="user", uselist=False
    )
    student_profile: Mapped[Student | None] = relationship(back_populates="user", uselist=False)
    parent_profile: Mapped[Parent | None] = relationship(back_populates="user", uselist=False)
    roles: Mapped[list[UserRole]] = relationship(back_populates="user")
    notifications: Mapped[list[Notification]] = relationship(back_populates="user")


# ---------------------------------------------------------------------------
# Profils métier
# ---------------------------------------------------------------------------


class StaffProfile(Base, TimestampMixin, ArchivableMixin):
    """Profil personnel administratif."""

    __tablename__ = "staff_profiles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
        index=True,
    )
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    position: Mapped[str | None] = mapped_column(String(100), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    photo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    user: Mapped[User] = relationship(back_populates="staff_profile")


class TeacherProfile(Base, TimestampMixin, ArchivableMixin):
    """Profil enseignant."""

    __tablename__ = "teacher_profiles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
        index=True,
    )
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    speciality: Mapped[str | None] = mapped_column(String(150), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    photo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    user: Mapped[User] = relationship(back_populates="teacher_profile")


# ---------------------------------------------------------------------------
# Student
# ---------------------------------------------------------------------------


class Student(Base, TimestampMixin, ArchivableMixin):
    """Profil élève — peut ou non avoir un compte User."""

    __tablename__ = "students"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    genre: Mapped[str | None] = mapped_column(ValueEnum(Genre, name="genre"), nullable=True)
    enrollment_number: Mapped[str | None] = mapped_column(
        String(50), nullable=True, unique=True, index=True
    )
    photo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    commune: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Etablissement d'origine et numero de la decision de transfert : les deux
    # seules informations que la demande de dossier scolaire ne peut pas
    # deviner. Sans elles, le secretariat retape l'adresse du college
    # precedent a chaque demande, avec les fautes que cela suppose.
    previous_school: Mapped[str | None] = mapped_column(String(200), nullable=True)
    transfer_decision_number: Mapped[str | None] = mapped_column(String(60), nullable=True)

    user: Mapped[User | None] = relationship(back_populates="student_profile")
    parents: Mapped[list[ParentStudent]] = relationship(back_populates="student")
    enrollments: Mapped[list[Enrollment]] = relationship(back_populates="student")
    grades: Mapped[list[Grade]] = relationship(back_populates="student")


# ---------------------------------------------------------------------------
# Parent
# ---------------------------------------------------------------------------


class ParentRelationship(str, enum.Enum):
    FATHER = "father"
    MOTHER = "mother"
    GUARDIAN = "guardian"
    OTHER = "other"


class Parent(Base, TimestampMixin, ArchivableMixin):
    """Profil parent / tuteur légal."""

    __tablename__ = "parents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    commune: Mapped[str | None] = mapped_column(String(100), nullable=True)

    user: Mapped[User | None] = relationship(back_populates="parent_profile")
    children: Mapped[list[ParentStudent]] = relationship(back_populates="parent")


class ParentStudent(Base):
    """Table de liaison Parent ↔ Student (many-to-many)."""

    __tablename__ = "parent_students"
    __table_args__ = (UniqueConstraint("parent_id", "student_id"),)

    parent_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("parents.id", ondelete="CASCADE"), primary_key=True
    )
    student_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("students.id", ondelete="CASCADE"), primary_key=True
    )
    relationship_type: Mapped[str] = mapped_column(
        ValueEnum(ParentRelationship, name="parent_relationship"),
        nullable=False,
        default=ParentRelationship.GUARDIAN,
    )

    parent: Mapped[Parent] = relationship(back_populates="children")
    student: Mapped[Student] = relationship(back_populates="parents")
