"""Schémas Pydantic pour les inscriptions."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.fee import FeeEntitlement


class InKindDeposit(BaseModel):
    """À l'inscription : le secrétariat coche ce qui a été déposé."""

    fee_category_id: int
    deposited: bool = False

    @field_validator("fee_category_id")
    @classmethod
    def _positive_category(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("must be a positive integer")
        return v


class EnrollmentCreate(BaseModel):
    student_id: int
    class_id: int
    academic_year_id: int
    fee_variant_id: int | None = None
    notes: str | None = None
    in_kind_deposits: list[InKindDeposit] = Field(default_factory=list)

    @field_validator("academic_year_id", "student_id", "class_id")
    @classmethod
    def must_be_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("must be a positive integer")
        return v

    assignment_status: str | None = None
    assignment_decision_number: str | None = None
    #: Trois etats distincts, et le client doit pouvoir les dire tous les
    #: trois :
    #:
    #: - `true` : nouvel eleve ;
    #: - `false` : deja inscrit dans l'etablissement auparavant ;
    #: - `null` ENVOYE explicitement : le guichet ne tranche pas. La valeur est
    #:   enregistree telle quelle, et l'inscription ne recoit alors aucun tarif
    #:   porteur d'un profil.
    #:
    #: Champ ABSENT du corps : personne ne s'est prononce, le serveur deduit
    #: depuis l'historique. Un client qui voulait dire « non tranche » doit donc
    #: envoyer `null` explicitement : en JavaScript, `JSON.stringify` supprime
    #: les cles `undefined`, le champ disparait du corps, et le serveur deduit
    #: alors que l'ecran promettait le contraire.
    is_new_student: bool | None = None
    #: Motif de la dérogation, quand on inscrit malgré une dette d'un exercice
    #: précédent. **Dans le corps, jamais dans l'adresse** : il nomme une
    #: famille — « cas social », « la mère est décédée » — et une URL finit
    #: dans les journaux d'accès du serveur et chez tous les intermédiaires,
    #: en clair et pour toujours. Le dépôt porte déjà cette règle, écrite noir
    #: sur blanc dans `tests/test_enrollment_purge.py`.
    override_reason: str | None = Field(default=None, max_length=500)


class EnrollmentUpdate(BaseModel):
    status: str | None = None
    notes: str | None = None
    class_id: int | None = None

    @field_validator("status")
    @classmethod
    def valid_status(cls, v: str | None) -> str | None:
        if v is None:
            return v
        allowed = {"prospect", "en_validation", "valide", "rejete", "annule"}
        if v not in allowed:
            raise ValueError(f"status must be one of {sorted(allowed)}")
        return v

    @field_validator("class_id")
    @classmethod
    def positive_class_id(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            raise ValueError("class_id must be a positive integer")
        return v

    assignment_status: str | None = None
    assignment_decision_number: str | None = None
    #: La decision se corrige : c'est pour cela qu'elle vit sur l'inscription.
    #: Le champ absent laisse la valeur intacte, le champ envoye a `null` la
    #: remet a « on n'a pas tranche ». Le service distingue les deux, comme
    #: pour la portee d'un tarif. Corriger ce champ regenere les frais de
    #: l'inscription, exactement comme un changement de classe.
    is_new_student: bool | None = None

    @field_validator("assignment_status")
    @classmethod
    def valid_assignment_status(cls, v: str | None) -> str | None:
        if v is None:
            return v
        allowed = {"affecte", "reaffecte", "non_affecte"}
        if v not in allowed:
            raise ValueError(f"assignment_status must be one of {sorted(allowed)}")
        return v


class SubscribeOptionRequest(BaseModel):
    optional_fee_option_id: int

    @field_validator("optional_fee_option_id")
    @classmethod
    def positive_option_id(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("optional_fee_option_id must be a positive integer")
        return v


class EnrollmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    student_id: int
    class_id: int
    academic_year_id: int
    academic_year_name: str
    status: str
    fee_variant_id: int | None
    notes: str | None
    created_by: int | None
    created_at: datetime
    updated_at: datetime
    student_first_name: str | None = None
    student_last_name: str | None = None
    class_name: str | None = None
    assignment_status: str | None = None
    assignment_decision_number: str | None = None
    #: `None` = on n'a pas tranche. L'ecran doit l'afficher comme tel, pas
    #: comme « ancien » : c'est une case a cocher, pas une case decochee.
    is_new_student: bool | None = None


class EnrollmentListResponse(BaseModel):
    items: list[EnrollmentResponse]
    total: int
    page: int
    size: int


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    enrollment_id: int
    type: str
    file_url: str
    original_name: str | None
    created_at: datetime


# ---------------------------------------------------------------------------
# Composite enrollment (student + parent + enrollment in one call)
# ---------------------------------------------------------------------------


class ParentInput(BaseModel):
    first_name: str
    last_name: str
    phone: str | None = None
    email: str | None = None
    city: str | None = None
    commune: str | None = None
    password: str | None = None  # If email+password provided, creates a User account
    relationship_type: str = "guardian"

    @field_validator("relationship_type")
    @classmethod
    def valid_relationship(cls, v: str) -> str:
        allowed = {"father", "mother", "guardian", "other"}
        if v not in allowed:
            raise ValueError(f"relationship_type must be one of {sorted(allowed)}")
        return v


class EnrollmentWithStudentCreate(BaseModel):
    """Creates a Student + optional Parent + Enrollment in one transaction."""

    # Student info
    first_name: str
    last_name: str
    birth_date: date | None = None
    birth_place: str | None = None
    genre: str | None = None
    enrollment_number: str | None = None
    city: str | None = None
    commune: str | None = None
    # Optional parent
    parent: ParentInput | None = None
    # Enrollment info
    class_id: int
    academic_year_id: int | None = None  # if None, use current year
    # Statut d'affectation : il decide du tarif applique, il doit donc
    # etre saisi au moment ou l'inscription est creee.
    assignment_status: str | None = None
    assignment_decision_number: str | None = None
    # Le profil decide lui aussi du tarif applique : meme raison, meme place,
    # memes trois etats que sur `EnrollmentCreate`. Absent, il est deduit de
    # l'historique ; envoye a `null`, il reste « non tranche ».
    is_new_student: bool | None = None
    fee_variant_id: int | None = None
    notes: str | None = None
    in_kind_deposits: list[InKindDeposit] = Field(default_factory=list)

    @field_validator("genre")
    @classmethod
    def valid_genre(cls, v: str | None) -> str | None:
        if v is not None and v not in {"M", "F"}:
            raise ValueError("genre must be 'M' or 'F'")
        return v

    @field_validator("class_id")
    @classmethod
    def positive_class_id(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("must be a positive integer")
        return v

    #: Motif de la dérogation, quand on inscrit malgré une dette d'un exercice
    #: précédent. **Dans le corps, jamais dans l'adresse** : il nomme une
    #: famille — « cas social », « la mère est décédée » — et une URL finit
    #: dans les journaux d'accès du serveur et chez tous les intermédiaires,
    #: en clair et pour toujours. Le dépôt porte déjà cette règle, écrite noir
    #: sur blanc dans `tests/test_enrollment_purge.py`.
    override_reason: str | None = Field(default=None, max_length=500)


class ReEnrollmentCreate(BaseModel):
    """Re-enrolls an existing student for a new year/class."""

    student_id: int
    class_id: int
    academic_year_id: int | None = None  # if None, use current year
    fee_variant_id: int | None = None
    notes: str | None = None
    in_kind_deposits: list[InKindDeposit] = Field(default_factory=list)

    @field_validator("student_id", "class_id")
    @classmethod
    def must_be_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("must be a positive integer")
        return v

    #: Motif de la dérogation, quand on inscrit malgré une dette d'un exercice
    #: précédent. **Dans le corps, jamais dans l'adresse** : il nomme une
    #: famille — « cas social », « la mère est décédée » — et une URL finit
    #: dans les journaux d'accès du serveur et chez tous les intermédiaires,
    #: en clair et pour toujours. Le dépôt porte déjà cette règle, écrite noir
    #: sur blanc dans `tests/test_enrollment_purge.py`.
    override_reason: str | None = Field(default=None, max_length=500)


# ---------------------------------------------------------------------------
# Fee variant resolution
# ---------------------------------------------------------------------------


class FeeVariantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    fee_category_id: int
    category_name: str
    #: Ce que ce frais ouvre a la famille. Repris de la categorie : sans lui,
    #: l'ecran affiche un montant sans jamais dire ce qu'il achete.
    entitlements: list[FeeEntitlement] = Field(default_factory=list)
    is_mandatory: bool = True
    accepts_in_kind: bool = False
    level_id: int | None
    series_id: int | None
    academic_year_id: int
    amount: Decimal
    description: str | None


class InKindDepositResponse(BaseModel):
    id: int
    status: str
    deposited_at: datetime | None
    deposited_by_user_id: int | None


class BulkValidateRequest(BaseModel):
    """Les inscriptions à valider en une fois."""

    enrollment_ids: list[int] = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Identifiants des inscriptions à valider.",
    )


class BulkValidateFailure(BaseModel):
    enrollment_id: int
    #: Le motif, en clair : sans lui l'ecran ne peut que dire « certaines ont
    #: echoue », ce qui oblige a rouvrir chaque dossier pour comprendre.
    reason: str


class BulkValidateResponse(BaseModel):
    validated: list[int]
    failed: list[BulkValidateFailure]


class NewStudentSuggestionResponse(BaseModel):
    """Ce que l'ecran doit pre-cocher dans la case « nouvel eleve », et pourquoi.

    Trois reponses, jamais deux. `null` n'est pas une panne : c'est
    l'etablissement qui n'a pas declare ses annees passees exploitables, et la
    secretaire qui reste seule a savoir. La phrase le lui dit en clair, plutot
    que de laisser une case vide sans explication.
    """

    suggested: bool | None
    reason: str


class DepositableFeeResponse(BaseModel):
    """Un article que cette inscription peut recevoir en depot."""

    model_config = ConfigDict(from_attributes=True)

    fee_id: int
    fee_category_id: int
    category_name: str
    #: `pending` reste a deposer, `in_kind` deja depose. Les autres statuts ne
    #: remontent pas : une ligne payee ou exoneree ne se depose plus.
    status: str


class InKindRosterRowResponse(BaseModel):
    """Une ligne de la liste de saisie : un eleve, son profil, ses articles."""

    model_config = ConfigDict(from_attributes=True)

    enrollment_id: int
    student_id: int
    first_name: str
    last_name: str
    #: `null` = profil non tranche. L'ecran n'a rien a pre-cocher.
    is_new_student: bool | None
    fees: list[DepositableFeeResponse]


class InKindRosterResponse(BaseModel):
    """La classe entiere, en un appel.

    L'educateur travaille classe par classe, debout, sur un telephone. Lui
    faire ouvrir soixante-dix-huit fiches revient a ne pas faire le travail.
    """

    items: list[InKindRosterRowResponse]
