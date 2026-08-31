"""Schemas Pydantic pour le CRUD des frais scolaires (FeeCategory, FeeVariant)."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.fee import FeeAssignmentScope, FeeEnrollmentProfile, FeeEntitlementKind

# ---------------------------------------------------------------------------
# Contrepartie — ce que la famille recoit contre un frais
# ---------------------------------------------------------------------------


class FeeEntitlement(BaseModel):
    """Un element de ce qu'ouvre un frais : un objet remis ou un droit d'acces.

    Volontairement pauvre. Un libelle, une quantite quand elle veut dire
    quelque chose, une nature. Rien qui ressemble encore a un suivi de remise :
    le jour ou l'ecole voudra cocher « la tenue a ete remise », il faudra une
    ligne par eleve, pas un champ de plus ici.
    """

    model_config = ConfigDict(from_attributes=True)

    label: str = Field(min_length=1, max_length=120)
    #: `None` quand compter n'a pas de sens : on n'ecrit pas « 1 infirmerie ».
    quantity: int | None = Field(default=None, ge=1, le=999)
    kind: FeeEntitlementKind = FeeEntitlementKind.ITEM

    @field_validator("label")
    @classmethod
    def _trim_label(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("Le libellé ne peut pas être vide")
        return trimmed


def coerce_entitlements(v: object) -> object:
    """Lit la colonne JSON sans jamais faire tomber une reponse.

    La colonne est libre par nature : une ligne ecrite a la main en base, ou
    laissee par une version anterieure du formulaire, ne doit pas transformer
    la fiche d'un eleve en erreur 500. Ce qui est illisible est ignore, le
    reste passe.
    """
    if v is None:
        return []
    if not isinstance(v, list):
        return []
    propres: list[object] = []
    for element in v:
        if isinstance(element, dict) and str(element.get("label", "")).strip():
            propres.append(element)
    return propres


#: Nombre maximum d'elements retenus sur une categorie. Au-dela, ce n'est plus
#: une contrepartie lisible sur un recu, c'est un inventaire.
MAX_ENTITLEMENTS = 15


# ---------------------------------------------------------------------------
# FeeCategory
# ---------------------------------------------------------------------------


class FeeCategoryCreate(BaseModel):
    name: str
    description: str | None = None
    #: Ce que la famille recoit contre ce frais. Vide par defaut : une ecole
    #: qui n'a rien a promettre ne doit pas etre forcee d'inventer une ligne.
    entitlements: list[FeeEntitlement] = Field(default_factory=list, max_length=MAX_ENTITLEMENTS)
    is_mandatory: bool = True
    #: Le parent peut déposer l'article à la place de payer. Décoché par défaut.
    accepts_in_kind: bool = False
    # Ordre d'imputation des versements : plus petit = servi en premier.
    # Sans ce champ, toute categorie creee tombait a 100, donc derniere, et
    # rien ne permettait de la remonter depuis l'interface.
    priority: int = Field(default=100, ge=0, le=999)


class FeeCategoryUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    #: Une liste vide efface la contrepartie ; le champ absent la laisse
    #: intacte. Sans cette distinction, renommer une categorie effacerait au
    #: passage tout ce qu'elle promet.
    entitlements: list[FeeEntitlement] | None = Field(default=None, max_length=MAX_ENTITLEMENTS)
    is_mandatory: bool | None = None
    accepts_in_kind: bool | None = None
    priority: int | None = Field(default=None, ge=0, le=999)


class FeeCategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    entitlements: list[FeeEntitlement] = Field(default_factory=list)
    is_mandatory: bool
    accepts_in_kind: bool = False
    priority: int
    created_at: datetime
    updated_at: datetime

    @field_validator("entitlements", mode="before")
    @classmethod
    def _lire_entitlements(cls, v: object) -> object:
        return coerce_entitlements(v)


class FeeCategoryListResponse(BaseModel):
    items: list[FeeCategoryResponse]
    total: int
    page: int
    size: int


# ---------------------------------------------------------------------------
# FeeVariant
# ---------------------------------------------------------------------------


class FeeVariantCreate(BaseModel):
    fee_category_id: int
    level_id: int
    series_id: int | None = None
    academic_year_id: int
    amount: Decimal
    description: str | None = None

    @field_validator("amount")
    @classmethod
    def positive_amount(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("amount must be positive")
        return v

    # `None` = ce tarif s'applique a tout le monde. Sinon il ne vaut que
    # pour les affectes ou que pour les non affectes.
    assignment_scope: FeeAssignmentScope | None = None
    # `None` = ce tarif s'applique a tout le monde. Sinon il ne vaut que pour
    # les nouveaux eleves ou que pour les anciens.
    enrollment_profile: FeeEnrollmentProfile | None = None


class FeeVariantUpdate(BaseModel):
    amount: Decimal | None = None
    description: str | None = None

    @field_validator("amount")
    @classmethod
    def positive_amount(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and v <= 0:
            raise ValueError("amount must be positive")
        return v

    # `None` = ce tarif s'applique a tout le monde. Sinon il ne vaut que
    # pour les affectes ou que pour les non affectes. Remettre ce champ a
    # `None` doit rendre le tarif universel : le service distingue donc un
    # champ absent d'un champ envoye vide, sans quoi une portee posee par
    # erreur ne se retirerait plus jamais depuis l'ecran.
    assignment_scope: FeeAssignmentScope | None = None
    # Meme regle et meme piege que la portee ci-dessus : remettre ce champ a
    # `None` doit rendre le tarif applicable a tout le monde.
    enrollment_profile: FeeEnrollmentProfile | None = None


class FeeVariantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    fee_category_id: int
    level_id: int
    series_id: int | None
    academic_year_id: int
    amount: Decimal
    description: str | None
    created_at: datetime
    updated_at: datetime
    assignment_scope: str | None = None
    enrollment_profile: str | None = None


class FeeVariantListResponse(BaseModel):
    items: list[FeeVariantResponse]
    total: int
    page: int
    size: int


# ---------------------------------------------------------------------------
# Repercussion d'un tarif modifie sur les inscriptions existantes
# ---------------------------------------------------------------------------


class _FeePropagationImpact(BaseModel):
    """Le socle chiffre commun a l'apercu et au resultat.

    Les deux reponses portent les memes compteurs, sous les memes noms : c'est
    ce qui permet a l'ecole de comparer ce qu'on lui avait annonce et ce qui a
    ete fait.
    """

    variant_id: int
    fee_category_id: int
    category_name: str
    academic_year_id: int
    #: Le montant du tarif tel qu'il est aujourd'hui : celui qui sera recopie.
    amount: Decimal
    #: Somme des six paquets. Une categorie ne produisant qu'une ligne par
    #: inscription, ce total est aussi le nombre d'inscriptions touchees.
    enrollments_concerned: int
    fees_already_up_to_date: int
    fees_kept_with_payments: int
    fees_waived: int
    #: Lignes reglees par un depot d'article. Comptees a part de `fees_waived`
    #: parce qu'un depot n'est pas une exoneration DRENA, mais comptees quand
    #: meme : sans elles la somme des paquets serait inferieure au total.
    fees_in_kind: int
    #: Ecart de dette en francs, negatif quand le tarif baisse. Il ne chiffre
    #: JAMAIS que ce que l'appel ecrit : sur l'apercu et sur une repercussion
    #: sans creation, les seules reecritures ; avec `create_missing`, les
    #: reecritures plus le montant entier de chaque ligne creee. Ce que les
    #: lignes manquantes couteraient, quand on ne les cree pas, est annonce a
    #: part dans `message` : les fondre ici ferait lire un chiffre que la
    #: comptabilite ne retrouverait jamais.
    debt_delta: Decimal
    message: str


class FeePropagationRequest(BaseModel):
    """Ce que l'ecole demande en confirmant la repercussion.

    Deux gestes distincts derriere un meme bouton, et le second se demande.
    """

    #: `false`, le defaut : on ne fait que reecrire les lignes qui portent deja
    #: ce tarif. Corriger le prix de la tenue ne cree alors aucune dette.
    #: `true` : les inscriptions que ce tarif doit atteindre et qui ne portent
    #: aucune ligne de sa categorie en recoivent une.
    create_missing: bool = False


class FeePropagationPreview(_FeePropagationImpact):
    """Ce qui se passerait. Rien n'est ecrit."""

    fees_to_update: int
    #: Les inscriptions auxquelles ce tarif doit une ligne et qui n'en portent
    #: aucune de sa categorie : l'ecole vient d'ajouter un tarif que les eleves
    #: deja inscrits n'ont jamais recu. Compte dans TOUS les cas, creation
    #: demandee ou non : l'ecole doit voir l'occasion meme si elle ne la saisit
    #: pas ce jour-la.
    fees_to_create: int


class FeePropagationResult(_FeePropagationImpact):
    """Ce qui a ete ecrit : le compte des lignes reellement reecrites et creees."""

    fees_updated: int
    #: Zero quand `create_missing` valait `false` : rien n'a ete cree, et le
    #: total `enrollments_concerned` ne compte alors pas ces inscriptions-la.
    fees_created: int


# ---------------------------------------------------------------------------
# OptionalFeeOption
# ---------------------------------------------------------------------------


class OptionalFeeOptionCreate(BaseModel):
    fee_category_id: int
    academic_year_id: int
    name: str
    amount: Decimal
    description: str | None = None

    @field_validator("amount")
    @classmethod
    def positive_amount(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("amount must be positive")
        return v


class OptionalFeeOptionUpdate(BaseModel):
    name: str | None = None
    amount: Decimal | None = None
    description: str | None = None

    @field_validator("amount")
    @classmethod
    def positive_amount(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and v <= 0:
            raise ValueError("amount must be positive")
        return v


class OptionalFeeOptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    fee_category_id: int
    academic_year_id: int
    name: str
    amount: Decimal
    description: str | None
    created_at: datetime
    updated_at: datetime


class OptionalFeeOptionListResponse(BaseModel):
    items: list[OptionalFeeOptionResponse]
    total: int
    page: int
    size: int
