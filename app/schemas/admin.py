"""Schémas Pydantic pour le CRUD admin des entités de base."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.models.user import TeacherContract
from app.schemas.fee import FeeEntitlement

# ---------------------------------------------------------------------------
# Student
# ---------------------------------------------------------------------------


class StudentCreate(BaseModel):
    first_name: str
    last_name: str
    email: str
    password: str
    birth_date: date | None = None
    birth_place: str | None = None
    genre: str | None = None
    enrollment_number: str | None = None
    city: str | None = None
    commune: str | None = None

    @field_validator("genre")
    @classmethod
    def valid_genre(cls, v: str | None) -> str | None:
        if v is not None and v not in {"M", "F"}:
            raise ValueError("genre must be 'M' or 'F'")
        return v


class StudentUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    birth_date: date | None = None
    birth_place: str | None = None
    genre: str | None = None
    enrollment_number: str | None = None
    user_id: int | None = None
    city: str | None = None
    commune: str | None = None

    @field_validator("genre")
    @classmethod
    def valid_genre(cls, v: str | None) -> str | None:
        if v is not None and v not in {"M", "F"}:
            raise ValueError("genre must be 'M' or 'F'")
        return v


class CurrentEnrollmentInfo(BaseModel):
    """Inscription d'un élève pour l'année académique courante (status `valide`).

    Au plus une instance par élève (UniqueConstraint(student_id, academic_year_id)
    + filtre status=valide). `null` côté StudentResponse si l'élève n'est pas
    inscrit cette année.
    """

    model_config = ConfigDict(from_attributes=True)

    enrollment_id: int
    class_id: int
    class_name: str
    status: str


class StudentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    first_name: str
    last_name: str
    birth_date: date | None
    birth_place: str | None = None
    genre: str | None
    enrollment_number: str | None
    photo_url: str | None = None
    city: str | None = None
    commune: str | None = None
    user_id: int | None
    created_at: datetime
    updated_at: datetime
    # Enrichi par list_students avec l'inscription année courante (None si non inscrit).
    current_enrollment: CurrentEnrollmentInfo | None = None


class StudentClassFilterCount(BaseModel):
    """Compteur d'élèves dans une classe pour la barre de chips."""

    class_id: int
    class_name: str
    count: int


class StudentFiltersResponse(BaseModel):
    """Counts pour la barre de filtre-chips de /admin/students.

    `total` : tous les élèves du tenant (indépendant de l'année).
    `by_class` : listes des classes avec au moins 1 inscription valide cette année.
    `no_current_enrollment_count` : élèves sans inscription valide cette année.
    `current_academic_year_id` : null si aucune année n'est marquée courante.
    """

    total: int
    by_class: list[StudentClassFilterCount]
    no_current_enrollment_count: int
    current_academic_year_id: int | None = None


# ---------------------------------------------------------------------------
# Admin summary (KPI aggregates) — computed server-side, scale-independent
# ---------------------------------------------------------------------------


class ClassesSummary(BaseModel):
    total: int
    enrolled: int
    capacity: int
    full: int


class TeachersSummary(BaseModel):
    total: int
    with_speciality: int
    with_phone: int
    without_speciality: int


class StaffSummary(BaseModel):
    total: int
    distinct_positions: int
    with_phone: int
    without_position: int


class ParentsSummary(BaseModel):
    total: int
    with_account: int
    with_email: int
    without_account: int


class RoomsSummary(BaseModel):
    total: int
    capacity: int
    classrooms: int
    classes_without_room: int


class SubjectsSummary(BaseModel):
    unique_names: int
    instances: int
    without_teacher: int
    total_hours: int


class EnrollmentsSummary(BaseModel):
    total: int
    valid: int
    pending: int
    closed: int


class AdminSummaryResponse(BaseModel):
    """Agrégats KPI pour le dashboard et les pages de gestion admin."""

    classes: ClassesSummary
    teachers: TeachersSummary
    staff: StaffSummary
    parents: ParentsSummary
    rooms: RoomsSummary
    subjects: SubjectsSummary
    enrollments: EnrollmentsSummary


class StudentTrimesterGrades(BaseModel):
    trimester: int
    general: float | None = None
    best: float | None = None
    worst: float | None = None


class StudentTrimesterAbsences(BaseModel):
    trimester: int
    justifiees: int = 0
    non_justifiees: int = 0


class StudentFullResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    # Basic student info
    id: int
    first_name: str
    last_name: str
    birth_date: date | None
    birth_place: str | None = None
    genre: str | None
    enrollment_number: str | None
    photo_url: str | None = None
    city: str | None = None
    commune: str | None = None
    user_id: int | None
    created_at: datetime
    updated_at: datetime

    # User account info (from User model)
    user_email: str | None = None
    user_is_active: bool | None = None
    user_last_login: datetime | None = None
    user_created_at: datetime | None = None

    # Current enrollment summary
    current_class_name: str | None = None
    current_academic_year: str | None = None
    current_enrollment_status: str | None = None
    current_enrollment_id: int | None = None

    # Aggregated KPIs
    attendance_total: int = 0
    attendance_present: int = 0
    attendance_absent: int = 0
    attendance_late: int = 0
    attendance_rate: float = 0.0

    # Financial summary — `None` quand l'appelant n'a pas `payments:read`.
    # On renvoie `None` et pas `0` : un zero se lit « la famille ne doit
    # rien », ce qui serait un mensonge.
    fees_expected: float | None = 0.0
    fees_paid: float | None = 0.0
    fees_remaining: float | None = 0.0
    fees_rate: float | None = 0.0
    # Etat de paiement sans montant, pour `payments:status:read`.
    fee_status: str | None = None
    last_payment_date: date | None = None

    # Trimester breakdowns (current academic year)
    # Toujours 3 entrées (T1/T2/T3) padded avec null/0 si pas de données.
    trimester_grades: list[StudentTrimesterGrades] = []
    trimester_absences: list[StudentTrimesterAbsences] = []


class StudentListResponse(BaseModel):
    items: list[StudentResponse]
    total: int
    page: int
    size: int


# ---------------------------------------------------------------------------
# TeacherProfile
# ---------------------------------------------------------------------------


class TeacherCreate(BaseModel):
    first_name: str
    last_name: str
    email: str
    password: str
    speciality: str | None = None
    phone: str | None = None
    # Reclames par le rapport de fin de trimestre de la DEEP (repartition du
    # personnel enseignant par contrat et par sexe). Facultatifs : on ne devine
    # ni le sexe ni le contrat de quelqu'un.
    genre: str | None = None
    contract_type: TeacherContract | None = None

    @field_validator("genre")
    @classmethod
    def valid_genre(cls, v: str | None) -> str | None:
        if v is not None and v not in {"M", "F"}:
            raise ValueError("genre must be 'M' or 'F'")
        return v


class TeacherUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    speciality: str | None = None
    phone: str | None = None
    genre: str | None = None
    contract_type: TeacherContract | None = None

    @field_validator("genre")
    @classmethod
    def valid_genre(cls, v: str | None) -> str | None:
        if v is not None and v not in {"M", "F"}:
            raise ValueError("genre must be 'M' or 'F'")
        return v


class TeacherResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    first_name: str
    last_name: str
    speciality: str | None
    phone: str | None
    genre: str | None = None
    contract_type: TeacherContract | None = None
    photo_url: str | None = None
    created_at: datetime
    updated_at: datetime


class TeacherTaughtClass(BaseModel):
    """One class taught by a teacher in the current AY (aggregated from timetable_slots)."""

    id: int
    name: str
    level: str | None = None
    subjects: list[str] = []
    hours_per_week: float = 0
    student_count: int = 0


class TeacherFullResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    # Basic teacher info
    id: int
    user_id: int
    first_name: str
    last_name: str
    speciality: str | None
    phone: str | None
    genre: str | None = None
    contract_type: TeacherContract | None = None
    photo_url: str | None = None
    created_at: datetime
    updated_at: datetime

    # User account info
    user_email: str | None = None
    user_is_active: bool | None = None
    user_last_login: datetime | None = None
    user_created_at: datetime | None = None

    # Aggregated KPIs
    classes_count: int = 0
    students_count: int = 0
    evaluations_count: int = 0
    hours_per_week: float = 0
    availability_rate: float = 0
    # "configured" si saisies explicites, "implicit" si dérivé des slots EDT,
    # "none" si aucune donnée. Permet au FE d'afficher un tooltip approprié et
    # d'éviter le faux "0% indispo" pour un prof actif sans saisie.
    availability_source: str = "none"

    # Detailed classes (current AY, aggregated from timetable_slots)
    classes: list[TeacherTaughtClass] = []


class TeacherListResponse(BaseModel):
    items: list[TeacherResponse]
    total: int
    page: int
    size: int


# ---------------------------------------------------------------------------
# StaffProfile
# ---------------------------------------------------------------------------


class StaffCreate(BaseModel):
    first_name: str
    last_name: str
    email: str
    password: str
    position: str | None = None
    phone: str | None = None
    # Rôle d'accès RBAC (secrétariat, comptable, caissier, éducateur, directeur
    # des études, directeur). Pilote les permissions. Whitelist validée côté
    # service via STAFF_ASSIGNABLE_ROLES, jamais admin/super_admin.
    role: str | None = None


class StaffUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    position: str | None = None
    phone: str | None = None
    role: str | None = None


class StaffResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    first_name: str
    last_name: str
    position: str | None
    phone: str | None
    photo_url: str | None = None
    # Rôle d'accès RBAC résolu depuis user_roles (cf. STAFF_ASSIGNABLE_ROLES)
    role: str | None = None
    created_at: datetime
    updated_at: datetime


class StaffFullResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    # Basic staff info
    id: int
    user_id: int
    first_name: str
    last_name: str
    position: str | None
    phone: str | None
    photo_url: str | None = None
    role: str | None = None
    created_at: datetime
    updated_at: datetime

    # User account info
    user_email: str | None = None
    user_is_active: bool | None = None
    user_last_login: datetime | None = None
    user_created_at: datetime | None = None

    # Activité (versements encaissés, inscriptions traitées) — AY courante
    activity: dict = {}


class StaffListResponse(BaseModel):
    items: list[StaffResponse]
    total: int
    page: int
    size: int


# ---------------------------------------------------------------------------
# Parent
# ---------------------------------------------------------------------------


class ParentCreate(BaseModel):
    first_name: str
    last_name: str
    phone: str | None = None
    email: str | None = None
    city: str | None = None
    commune: str | None = None
    password: str | None = None
    relationship_type: str = "guardian"

    @field_validator("relationship_type")
    @classmethod
    def valid_relationship(cls, v: str) -> str:
        if v not in {"father", "mother", "guardian", "other"}:
            raise ValueError("relationship_type must be father, mother, guardian, or other")
        return v


class ParentUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    phone: str | None = None
    email: str | None = None
    city: str | None = None
    commune: str | None = None


class ParentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int | None = None
    first_name: str
    last_name: str
    phone: str | None = None
    email: str | None = None
    city: str | None = None
    commune: str | None = None
    created_at: datetime
    updated_at: datetime


class ParentLinkBody(BaseModel):
    relationship_type: str = "guardian"

    @field_validator("relationship_type")
    @classmethod
    def valid_relationship(cls, v: str) -> str:
        if v not in {"father", "mother", "guardian", "other"}:
            raise ValueError("relationship_type must be father, mother, guardian, or other")
        return v


class ParentFullResponse(ParentResponse):
    user_email: str | None = None
    user_is_active: bool | None = None
    user_last_login: datetime | None = None
    children: list[dict] = []
    summary: dict = {}


class ParentListResponse(BaseModel):
    items: list[ParentResponse]
    total: int
    page: int
    size: int


# ---------------------------------------------------------------------------
# Class
# ---------------------------------------------------------------------------


class ClassCreate(BaseModel):
    """Schéma création de classe.

    Refactor #97 : Class est universel, pas de academic_year_id. L'année est
    portée par Enrollment lors de l'inscription.
    """

    name: str
    level_id: int
    series_id: int | None = None
    room_id: int | None = None
    max_students: int = 40

    @field_validator("max_students")
    @classmethod
    def positive_max(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("max_students must be positive")
        return v


class ClassUpdate(BaseModel):
    name: str | None = None
    level_id: int | None = None
    series_id: int | None = None
    room_id: int | None = None
    max_students: int | None = None

    @field_validator("max_students")
    @classmethod
    def positive_max(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            raise ValueError("max_students must be positive")
        return v


class ClassResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    level_id: int
    series_id: int | None
    room_id: int | None
    max_students: int
    level_name: str | None = None
    series_name: str | None = None
    enrolled_count: int = 0
    created_at: datetime
    updated_at: datetime


class ClassListResponse(BaseModel):
    items: list[ClassResponse]
    total: int
    page: int
    size: int


# ---------------------------------------------------------------------------
# Subject
# ---------------------------------------------------------------------------


class SubjectCreate(BaseModel):
    name: str
    level_id: int | None = None
    series_id: int | None = None
    coefficient: int = 1
    hours_per_week: int = 2
    color: str | None = None
    teacher_id: int | None = None

    @field_validator("coefficient", "hours_per_week")
    @classmethod
    def positive_value(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("must be positive")
        return v


class SubjectUpdate(BaseModel):
    name: str | None = None
    level_id: int | None = None
    series_id: int | None = None
    coefficient: int | None = None
    hours_per_week: int | None = None
    color: str | None = None
    teacher_id: int | None = None

    @field_validator("coefficient", "hours_per_week")
    @classmethod
    def positive_value(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            raise ValueError("must be positive")
        return v


class SubjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    level_id: int | None
    series_id: int | None
    coefficient: int
    hours_per_week: int
    color: str | None = None
    teacher_id: int | None = None
    teacher_name: str | None = None
    level_name: str | None = None
    series_name: str | None = None
    created_at: datetime
    updated_at: datetime


class SubjectDuplicateRequest(BaseModel):
    subject_id: int
    level_id: int
    series_id: int | None = None
    coefficient: int | None = None
    hours_per_week: int | None = None
    teacher_id: int | None = None


class SubjectListResponse(BaseModel):
    items: list[SubjectResponse]
    total: int
    page: int
    size: int


# ---------------------------------------------------------------------------
# AcademicYear
# ---------------------------------------------------------------------------


class AcademicYearCreate(BaseModel):
    name: str
    start_date: date
    end_date: date
    is_current: bool = False

    @field_validator("end_date")
    @classmethod
    def end_after_start(cls, v: date, info: object) -> date:
        # info.data contains already-validated fields
        data = getattr(info, "data", {})
        start = data.get("start_date")
        if start and v <= start:
            raise ValueError("end_date must be after start_date")
        return v


class AcademicYearUpdate(BaseModel):
    name: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool | None = None


class AcademicYearResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    start_date: date
    end_date: date
    is_current: bool
    created_at: datetime
    updated_at: datetime


class AcademicYearListResponse(BaseModel):
    items: list[AcademicYearResponse]
    total: int
    page: int
    size: int


# ---------------------------------------------------------------------------
# Level
# ---------------------------------------------------------------------------


class LevelCreate(BaseModel):
    name: str
    order: int = 0


class LevelUpdate(BaseModel):
    name: str | None = None
    order: int | None = None


class LevelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    order: int


class LevelListResponse(BaseModel):
    items: list[LevelResponse]
    total: int
    page: int
    size: int


# ---------------------------------------------------------------------------
# Enrollment Number Pattern
# ---------------------------------------------------------------------------


class EnrollmentPatternUpdate(BaseModel):
    pattern: str
    reset_counter: bool = False


class EnrollmentPatternPreview(BaseModel):
    pattern: str
    preview: str
    next_sequence: int


# ---------------------------------------------------------------------------
# School Settings
# ---------------------------------------------------------------------------


class TrimesterDTO(BaseModel):
    """Une période de l'année scolaire. Le contrat FE attend seulement
    label/start_date/end_date — l'ordre est inféré par l'index dans la liste."""

    model_config = ConfigDict(from_attributes=True)

    label: str
    start_date: date
    end_date: date


class TrimesterUpdateRequest(BaseModel):
    """PUT /admin/settings/trimesters — remplace les 3 trimestres de l'AY courante."""

    trimesters: list[TrimesterDTO]


class SchoolHolidayDTO(BaseModel):
    """Un congé ou jour férié. Jour unique = start_date == end_date."""

    model_config = ConfigDict(from_attributes=True)

    label: str
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def _check_range(self) -> "SchoolHolidayDTO":
        if self.end_date < self.start_date:
            raise ValueError("La date de fin doit être postérieure ou égale à la date de début")
        return self


class HolidaysUpdateRequest(BaseModel):
    """PUT /admin/settings/holidays — remplace les congés de l'AY courante."""

    holidays: list[SchoolHolidayDTO]


class NotificationSettingsUpdate(BaseModel):
    """PUT /admin/settings/notifications — préférences globales école."""

    notify_by_email: bool
    notify_by_sms: bool
    notify_grades: bool
    notify_absences: bool
    notify_payments: bool
    notify_enrollment: bool
    notify_reenrollment: bool


class SchoolSettingsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    school_name: str
    address: str | None
    phone: str | None
    email: str | None
    logo_url: str | None
    ministry_code: str | None
    signature_image_url: str | None
    head_master_name: str | None
    head_master_title: str | None
    enrollment_number_pattern: str | None
    enrollment_number_counter: int
    primary_color: str | None = None
    accent_color: str | None = None
    website: str | None = None
    motto: str | None = None
    deletion_notice_emails: str | None = None
    #: L'école a-t-elle déclaré ses inscriptions des années passées
    #: exploitables ? Tant que c'est `false`, le serveur ne devine jamais si un
    #: élève est nouveau : l'écran d'inscription doit donc présenter la case
    #: comme un choix à faire, pas comme une aide déjà remplie.
    enrollment_history_is_reliable: bool = False
    trimesters: list[TrimesterDTO] = []
    holidays: list[SchoolHolidayDTO] = []
    notify_by_email: bool = False
    notify_by_sms: bool = False
    notify_grades: bool = False
    notify_absences: bool = False
    notify_payments: bool = False
    notify_enrollment: bool = False
    notify_reenrollment: bool = False
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Student Enrollment Fees (for payment modal)
# ---------------------------------------------------------------------------


class UserAccountCreate(BaseModel):
    """Create a user account for an existing profile (student/parent/teacher/staff).

    Uses Pydantic ``EmailStr`` so validation is consistent with ``/auth/login``
    (both rely on ``email-validator`` and reject special-use TLDs like
    ``.local`` or ``.test``). Previously this used plain ``str`` and accepted
    e-mails that could never log in — caught during the e2e regression on
    2026-05-20 when ``foo@bar.local`` was accepted at creation but rejected at
    login with HTTP 422.
    """

    email: EmailStr
    password: str


class UserAccountUpdate(BaseModel):
    email: EmailStr | None = None
    password: str | None = None

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str | None) -> str | None:
        if v is not None and len(v) < 8:
            raise ValueError("Le mot de passe doit contenir au moins 8 caractères")
        return v


class StudentEnrollmentFeeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int  # enrollment_fee.id ou student_option.id
    enrollment_id: int
    category_name: str
    #: Ce que ce frais ouvre a la famille. Repris de la categorie : sans lui,
    #: l'ecran affiche un montant sans jamais dire ce qu'il achete.
    entitlements: list[FeeEntitlement] = Field(default_factory=list)
    amount: float  # total dû
    paid: float  # somme des paiements complétés
    remaining: float
    status: str  # pending/partial/paid/waived/in_kind
    accepts_in_kind: bool = False
    is_optional: bool = False  # True pour les options facultatives
    option_name: str | None = None  # nom de l'option si facultatif


class StudentEnrollmentFeeListResponse(BaseModel):
    items: list[StudentEnrollmentFeeResponse]


class EnrollmentHistoryCoverageResponse(BaseModel):
    """Ce que l'ecole doit lire AVANT de declarer son historique exploitable.

    La faille n'a jamais ete dans le calcul de la facture : elle est dans la
    decision, prise sans que rien n'affiche ce qu'elle implique. Ce payload
    existe pour la poser sous les yeux de qui coche.
    """

    #: Eleves distincts inscrits sur l'annee courante, statuts comptes.
    enrolled_this_year: int
    #: Ceux d'entre eux rattaches a une inscription d'une annee anterieure.
    with_anterior: int
    #: Proportion couverte, entre 0 et 1.
    ratio: float
    #: En dessous, le logiciel refuse de deduire meme reglage active.
    threshold: float
    #: Vrai si la deduction pourra reellement s'appliquer.
    is_sufficient: bool
    #: La phrase a afficher telle quelle a cote de la case.
    warning: str | None


class SchoolInfoUpdate(BaseModel):
    school_name: str | None = None
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    logo_url: str | None = None
    ministry_code: str | None = None
    signature_image_url: str | None = None
    head_master_name: str | None = None
    head_master_title: str | None = None
    # Personnalisation PDF par école (migration 0029)
    primary_color: str | None = None
    accent_color: str | None = None
    website: str | None = None
    motto: str | None = None
    #: Destinataires du courriel envoyé à chaque archivage et à chaque
    #: suppression définitive, séparés par des virgules. Laisser vide fait
    #: retomber sur l'adresse de l'établissement.
    deletion_notice_emails: str | None = None
    #: L'école déclare que ses inscriptions des années passées sont
    #: exploitables. Le champ absent laisse le réglage intact ; `false` est une
    #: valeur, pas une absence, et c'est celle qui empêche le serveur de
    #: deviner qui est nouveau au milieu d'une reprise d'historique.
    enrollment_history_is_reliable: bool | None = None

    @field_validator("primary_color", "accent_color")
    @classmethod
    def validate_hex_color(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        import re

        if not re.match(r"^#[0-9A-Fa-f]{6}$", v):
            raise ValueError("Format hex attendu : #RRGGBB")
        return v.upper()


# ---------------------------------------------------------------------------
# Series
# ---------------------------------------------------------------------------


class SeriesCreate(BaseModel):
    name: str
    level_id: int


class SeriesUpdate(BaseModel):
    name: str | None = None
    level_id: int | None = None


class SeriesResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    level_id: int
    name: str
    level_name: str | None = None


class SeriesListResponse(BaseModel):
    items: list[SeriesResponse]
    total: int
    page: int
    size: int


# ---------------------------------------------------------------------------
# Role & Permission
# ---------------------------------------------------------------------------


class PermissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name: str
    description: str | None = None


class RoleCreate(BaseModel):
    name: str
    description: str | None = None
    permission_ids: list[int] = []


class RoleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    permission_ids: list[int] | None = None


class RoleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None = None
    permissions: list[PermissionResponse] = []


class RoleListResponse(BaseModel):
    items: list[RoleResponse]
    total: int
    page: int
    size: int


# ---------------------------------------------------------------------------
# Room
# ---------------------------------------------------------------------------

VALID_ROOM_TYPES = {"classroom", "laboratory", "computer_room", "library", "other"}


class RoomCreate(BaseModel):
    name: str
    capacity: int | None = None
    room_type: str = "classroom"
    class_id: int | None = None

    @field_validator("room_type")
    @classmethod
    def valid_room_type(cls, v: str) -> str:
        if v not in VALID_ROOM_TYPES:
            raise ValueError(f"room_type must be one of {VALID_ROOM_TYPES}")
        return v

    @field_validator("capacity")
    @classmethod
    def positive_capacity(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            raise ValueError("capacity must be positive")
        return v


class RoomUpdate(BaseModel):
    name: str | None = None
    capacity: int | None = None
    room_type: str | None = None
    class_id: int | None = None

    @field_validator("room_type")
    @classmethod
    def valid_room_type(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_ROOM_TYPES:
            raise ValueError(f"room_type must be one of {VALID_ROOM_TYPES}")
        return v

    @field_validator("capacity")
    @classmethod
    def positive_capacity(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            raise ValueError("capacity must be positive")
        return v


class RoomResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    capacity: int | None
    room_type: str
    class_name: str | None = None
    class_id: int | None = None
    created_at: datetime
    updated_at: datetime


class RoomListResponse(BaseModel):
    items: list[RoomResponse]
    total: int
    page: int
    size: int


class RoomBatchCreateResponse(BaseModel):
    created: int
    rooms: list[RoomResponse]


# ---------------------------------------------------------------------------
# Promotions (mass year rollover) — cycle 3 plan B
# ---------------------------------------------------------------------------


class PromotionPreviewRequest(BaseModel):
    """Demande de pre-flight pour une promotion bulk d'année.

    Le `class_mapping` est explicite : `{source_class_id: target_class_id}`.
    Aucun parsing automatique de nom de classe — décision design pour éviter
    les fragilités de naming convention entre tenants.
    """

    source_ay_id: int
    target_ay_id: int
    class_mapping: dict[int, int]
    # Inscriptions a NE PAS promouvoir : redoublants, departs, exclusions.
    # Sans cette liste, une promotion emmene tout le monde et il faudrait
    # annuler a la main les inscriptions creees a tort — ce que personne ne
    # fera correctement sur trois cents eleves. Le redoublement est courant
    # dans le systeme ivoirien, ce n'est pas un cas marginal.
    excluded_enrollment_ids: list[int] = Field(default_factory=list)


class SourceClassSummary(BaseModel):
    source_class_id: int
    target_class_id: int
    target_class_name: str
    students_to_promote: int
    target_capacity: int
    target_remaining: int


class PromotionCapacityWarning(BaseModel):
    source_class_id: int
    target_class_id: int
    target_class_name: str
    requested: int
    available: int
    overflow: int


class PromotionPreviewResponse(BaseModel):
    """Résumé pre-flight : nb d'élèves promotables par classe + warnings capacité.

    Les warnings ne bloquent pas l'execute (l'admin peut décider de couper la
    sélection) — ils informent. Seuls les erreurs structurelles (classes
    inexistantes, AY identiques) bloquent et lèvent une 422 dès le preview.
    """

    source_ay_id: int
    target_ay_id: int
    source_classes: list[SourceClassSummary]
    capacity_warnings: list[PromotionCapacityWarning]
    promotable_count: int


class PromotionExecuteRequest(PromotionPreviewRequest):
    """Identique au preview, dans une route séparée pour clarté HTTP."""

    pass


class PromotionExecuteError(BaseModel):
    student_id: int
    source_enrollment_id: int
    reason: str


class PromotionExecuteResponse(BaseModel):
    """Réponse partial-success-with-reporting (pattern fintech 2024+).

    `promoted_count` = nouvelles inscriptions créées dans cette exécution.
    `skipped_count` = élèves déjà inscrits dans target_ay (idempotency safe).
    `error_count` + `errors[]` = échecs explicites (capacité dépassée,
    classes non mappées, validations métier).
    """

    source_ay_id: int
    target_ay_id: int
    promoted_count: int
    promoted_enrollment_ids: list[int]
    skipped_count: int
    error_count: int
    errors: list[PromotionExecuteError]


class ArchiveRequest(BaseModel):
    """Motif d'un geste de corbeille — mise à la corbeille ou suppression définitive.

    Obligatoire : sans lui, le journal dirait qu'une fiche a disparu sans dire
    pourquoi, ce qui ne vaut guère mieux que pas de trace du tout.

    Il voyage dans le corps de la requête, y compris pour la suppression
    définitive. Un motif passé en paramètre d'URL finirait recopié dans les
    journaux d'accès du serveur et chez tous les intermédiaires ; « élève
    exclu pour vol » n'a rien à faire dans une adresse.
    """

    reason: str = Field(min_length=10, max_length=500)
