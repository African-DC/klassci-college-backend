"""Modèles académiques : AcademicYear, Level, Series, Class, Subject, Room, SchoolSettings."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.enrollment import Enrollment
    from app.models.timetable import TimetableSlot
    from app.models.user import TeacherProfile


# ---------------------------------------------------------------------------
# AcademicYear
# ---------------------------------------------------------------------------


class AcademicYear(Base, TimestampMixin):
    """Année scolaire (ex : 2024-2025)."""

    __tablename__ = "academic_years"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)  # "2024-2025"
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Class is now universal (no academic_year_id). Listing « classes courantes »
    # passe par JOIN sur Enrollment.academic_year_id côté repo, pas via cette
    # relation qui n'existe plus depuis le refactor #97.

    trimesters: Mapped[list[Trimester]] = relationship(
        back_populates="academic_year",
        cascade="all, delete-orphan",
        order_by="Trimester.order_no",
    )
    holidays: Mapped[list[SchoolHoliday]] = relationship(
        back_populates="academic_year",
        cascade="all, delete-orphan",
        order_by="SchoolHoliday.start_date",
    )


class Trimester(Base, TimestampMixin):
    """Trimestre scolaire scopé à une année académique.

    Le calendrier scolaire ivoirien découpe l'année en 3 trimestres. Chaque
    bulletin, conseil de classe et moyenne périodique se rattache à un
    trimestre. Les dates varient légèrement d'une année à l'autre, d'où
    le scoping par `academic_year_id`.
    """

    __tablename__ = "trimesters"
    __table_args__ = (UniqueConstraint("academic_year_id", "order_no"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    academic_year_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("academic_years.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    label: Mapped[str] = mapped_column(String(50), nullable=False)
    order_no: Mapped[int] = mapped_column(Integer, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)

    academic_year: Mapped[AcademicYear] = relationship(back_populates="trimesters")


class SchoolHoliday(Base, TimestampMixin):
    """Période de congé ou jour férié scopée à une année académique.

    Contrairement aux trimestres (qui délimitent les périodes d'enseignement),
    un `SchoolHoliday` marque une plage de jours *non travaillés* à l'intérieur
    (ou en marge) de l'année : congés de Toussaint, fêtes religieuses mobiles,
    jour férié isolé (1er mai, fête de l'Indépendance…). Un jour unique se
    représente avec `start_date == end_date`. Les fêtes mobiles variant chaque
    année, ces plages sont saisies par l'établissement, pas figées dans le code.
    """

    __tablename__ = "school_holidays"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    academic_year_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("academic_years.id", ondelete="CASCADE"),
        nullable=False,
    )
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)

    academic_year: Mapped[AcademicYear] = relationship(back_populates="holidays")


# ---------------------------------------------------------------------------
# Level & Series
# ---------------------------------------------------------------------------


class Level(Base):
    """Niveau scolaire (ex : 6ème, 5ème, Terminale)."""

    __tablename__ = "levels"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    series: Mapped[list[Series]] = relationship(back_populates="level", passive_deletes=True)
    classes: Mapped[list[Class]] = relationship(back_populates="level", passive_deletes=True)


class Series(Base):
    """Série de lycée (ex : A1, C, D). Applicable uniquement au lycée."""

    __tablename__ = "series"
    __table_args__ = (UniqueConstraint("level_id", "name"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    level_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("levels.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(20), nullable=False)  # "A1", "C", "D"

    level: Mapped[Level] = relationship(back_populates="series")
    classes: Mapped[list[Class]] = relationship(back_populates="series", passive_deletes=True)


# ---------------------------------------------------------------------------
# Room
# ---------------------------------------------------------------------------


class Room(Base, TimestampMixin):
    """Salle de classe ou laboratoire."""

    __tablename__ = "rooms"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    room_type: Mapped[str] = mapped_column(String(30), nullable=False, server_default="classroom")

    classes: Mapped[list[Class]] = relationship(back_populates="room", passive_deletes=True)
    timetable_slots: Mapped[list[TimetableSlot]] = relationship(back_populates="room")


# ---------------------------------------------------------------------------
# Class
# ---------------------------------------------------------------------------


class Class(Base, TimestampMixin):
    """Classe scolaire universelle (ex : Terminale C, 6ème A).

    Refactor #97 : Class est désormais universelle (1 row par classe à vie).
    L'année académique est portée par Enrollment.academic_year_id, pas par Class.
    Les changements rares de max_students/room_id sont audit-loggés via la table
    audit_logs existante (entity_type=class, action=update).
    """

    __tablename__ = "classes"
    __table_args__ = (UniqueConstraint("name"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    level_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("levels.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    series_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("series.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    room_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("rooms.id", ondelete="SET NULL"), nullable=True, index=True
    )
    max_students: Mapped[int] = mapped_column(Integer, nullable=False, default=40)

    level: Mapped[Level] = relationship(back_populates="classes")
    series: Mapped[Series | None] = relationship(back_populates="classes")
    room: Mapped[Room | None] = relationship(back_populates="classes")
    enrollments: Mapped[list[Enrollment]] = relationship(back_populates="class_")
    timetable_slots: Mapped[list[TimetableSlot]] = relationship(back_populates="class_")


# ---------------------------------------------------------------------------
# Subject
# ---------------------------------------------------------------------------


class Subject(Base, TimestampMixin):
    """Matière enseignée."""

    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    level_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("levels.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    series_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("series.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    coefficient: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    hours_per_week: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    color: Mapped[str | None] = mapped_column(String(20), nullable=True)
    teacher_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("teacher_profiles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    level: Mapped[Level | None] = relationship(foreign_keys=[level_id])
    series: Mapped[Series | None] = relationship(foreign_keys=[series_id])
    teacher: Mapped[TeacherProfile | None] = relationship(foreign_keys=[teacher_id])
    timetable_slots: Mapped[list[TimetableSlot]] = relationship(back_populates="subject")


# ---------------------------------------------------------------------------
# SchoolSettings (singleton par tenant)
# ---------------------------------------------------------------------------


class SchoolSettings(Base, TimestampMixin):
    """Paramètres de l'établissement (singleton par tenant)."""

    __tablename__ = "school_settings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    school_name: Mapped[str] = mapped_column(String(200), nullable=False)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 50 caracteres et non 20 : l'en-tete officiel imprime deux numeros separes
    # par un double slash (« 27-31-63-01-60// 07-58-59-97-73 »), ce qui deborde
    # largement d'un seul numero ivoirien.
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ministry_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Direction Regionale de l'Education Nationale et de l'Alphabetisation de
    # rattachement (« BOUAKE 2 »). Elle figure sur tout acte administratif et
    # ne se deduit d'aucune autre colonne.
    drena_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    # Armoiries de la Republique. Facultatif : a defaut, les documents
    # impriment un embleme sobre. Seul l'etablissement detient le fichier
    # officiel, on ne peut donc pas l'embarquer dans le code.
    coat_of_arms_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Official documents (PR #105)
    signature_image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    head_master_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    head_master_title: Mapped[str | None] = mapped_column(String(100), nullable=True)
    enrollment_number_pattern: Mapped[str | None] = mapped_column(String(200), nullable=True)
    enrollment_number_counter: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Personnalisation PDF par tenant (migration 0029)
    primary_color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    accent_color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    website: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Moyens de paiement acceptes, en cles separees par des virgules
    # (cash, mobile_money, bank_transfer, cheque). NULL = tous acceptes, ce qui
    # preserve le comportement des etablissements deja en service.
    enabled_payment_methods: Mapped[str | None] = mapped_column(String(200), nullable=True)
    motto: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Seconde ligne de devise, imprimee en italique sous l'en-tete des actes
    # administratifs (« Soyons des citoyens responsables pour une ecole de
    # qualite »). Distincte de `motto`, qui reste la devise principale.
    secondary_motto: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Timetable generation settings
    slot_duration_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=60, server_default="60"
    )
    day_start_hour: Mapped[int] = mapped_column(
        Integer, nullable=False, default=7, server_default="7"
    )
    day_end_hour: Mapped[int] = mapped_column(
        Integer, nullable=False, default=17, server_default="17"
    )
    # Notification settings (canaux + types)
    notify_by_email: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    notify_by_sms: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    notify_grades: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    notify_absences: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    notify_payments: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    notify_enrollment: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    notify_reenrollment: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    # MailPulse — notifications email + WhatsApp aux parents (migration 0039)
    mailpulse_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    mailpulse_base_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Secret au repos — jamais renvoyé dans une réponse, jamais loggé, exclu du dict PDF.
    mailpulse_api_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mailpulse_sender_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mailpulse_sender_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mailpulse_default_language: Mapped[str] = mapped_column(
        String(5), nullable=False, default="fr", server_default="fr"
    )
    mailpulse_timeout: Mapped[int] = mapped_column(
        Integer, nullable=False, default=20, server_default="20"
    )
    # Gate des workflows réels (paiement/absence/note/rappel) vers les vrais parents.
    mailpulse_real_workflows_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    # Moteur de test — destinataires dédiés (jamais de vrais parents).
    mailpulse_test_email_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    mailpulse_test_whatsapp_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    # Listes [{"value": "...", "enabled": true}] — destinataires de test avec interrupteur.
    mailpulse_test_email_recipients: Mapped[list | None] = mapped_column(JSON, nullable=True)
    mailpulse_test_phone_recipients: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Secret de signature du webhook entrant (feature INFO) — jamais renvoyé.
    mailpulse_inbound_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Destinataires du courriel de suppression, séparés par des virgules.
    # Un courriel sort du logiciel : si quelqu'un efface une trace, il n'efface
    # pas une boîte de réception. Vide, on retombe sur l'adresse de l'école.
    deletion_notice_emails: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # L'école déclare elle-même que ses inscriptions des années passées sont
    # exploitables. Tant que c'est faux, le serveur ne déduit JAMAIS si un
    # élève est nouveau : dans une base qui ne contient que l'année en cours,
    # l'absence d'inscription antérieure ne distingue pas un arrivant d'un
    # ancien pas encore ressaisi, et la déduction facturerait le droit
    # d'entrée à toute l'école.
    #
    # Le défaut est donc `false`, y compris pour un établissement qui vient de
    # saisir ses premières lignes d'historique : c'est ce qui empêche le
    # garde-fou de basculer tout seul au milieu d'une reprise. Seul un geste
    # dans les réglages le lève.
    enrollment_history_is_reliable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
