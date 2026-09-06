"""Le garde : ce qu'une ardoise d'un exercice révolu fait à une réinscription.

Les deux pas précédents ont posé le droit d'y déroger, puis le réglage par
établissement. Celui-ci est la porte elle-même.

## Deux portes, un seul garde

Une inscription naît de deux fonctions du service, et de deux seulement :
`create_enrollment` — qui sert aussi `/enrollments/re-enroll` et la promotion
de masse — et `create_enrollment_with_student`, le formulaire où la secrétaire
saisit l'élève et son inscription d'un seul geste. Garder la première seule ne
servirait à rien : la seconde est précisément celle par où une réinscription
saisie comme un nouvel élève passerait.

Les deux ne présentent pas l'élève de la même façon. La première le connaît par
son identifiant ; la seconde ne le connaît pas encore — elle est en train de le
créer — et n'a de lui que le matricule tapé au clavier. Le garde accepte donc
les deux entrées, et c'est la seule différence entre les deux appels. Un
matricule déjà en base, c'est la même personne : le dépôt le tient pour le
signal le plus sûr de doublon (`services/duplicates/detection.py`), et l'index
unique sur la colonne le confirme. Sans matricule saisi, il n'y a rien à
rapprocher, et le garde laisse passer plutôt que d'inventer un rapprochement.

## La promotion n'est pas un guichet

Une promotion de fin d'année fait passer trois cents élèves d'un coup. Refuser
sur une dette y produirait, non pas trois cents refus lisibles, mais trois
cents « Erreur inattendue, voir les logs » : `promotion_service` n'attrape que
`BusinessValidationError` et range tout le reste dans l'imprévu. Elle force
donc la politique à `inform` — `ArrearsClearance.INFORM_ONLY` — et le garde
sort à sa première ligne, avant même de lire le réglage.

## Il ne commet rien

`document_release_service` — dont ce module reprend la forme du refus — fait un
`db.commit()` au milieu de sa logique. Ici ce serait fatal : les deux créations
travaillent dans un `begin_nested()`, et un commit posé au milieu validerait la
moitié d'une inscription. Le garde s'exécute donc AVANT la transaction, ne
lit que, et confie sa ligne de journal au commit de l'appelant. Une dérogation
pour une inscription qui échoue ensuite n'est pas journalisée, ce qui est
exactement ce qu'on veut : il ne s'est rien passé.

## Ce module n'appelle pas son jumeau

`document_release_service.evaluate_release` refuse explicitement d'être ce
mécanisme, et le dit dans son docstring : « Un élève sans inscription validée
pour l'année courante n'est pas retenu ici : son cas relève des règles
d'inscription, pas du recouvrement. » C'est précisément notre cas. On copie sa
forme — le 402, le détail structuré, le `may_override` résolu au routeur, le
motif obligatoire — jamais son appel.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import ClassVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit_log
from app.core.exceptions import EnrollmentBlockedByArrearsError
from app.models.academic import AcademicYear
from app.models.enrollment import CLOSED_STATUSES, Enrollment
from app.models.user import Student
from app.services import arrears_policy, fees_paid
from app.services.finance_visibility import FinanceView

logger = logging.getLogger(__name__)

#: Le code que l'écran lit pour distinguer ce refus de tous les autres.
BLOCKED_CODE = "ENROLLMENT_BLOCKED_BY_ARREARS"

_OU_REGULARISER = "Passez par la comptabilité pour régulariser ou faire lever le blocage."


@dataclass(frozen=True, slots=True)
class PriorArrears:
    """Ce qu'un élève doit encore au titre d'exercices déjà commencés avant celui-ci.

    `years` ne porte que les années qui doivent réellement quelque chose : une
    année soldée n'a pas à figurer dans la phrase lue au guichet.
    """

    amount: Decimal
    years: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ArrearsClearance:
    """Ce que l'appelant a le droit de faire, et de voir, face à une ardoise.

    Se passe toujours explicitement, comme le `FinanceView` qu'elle porte, et
    pour la même raison : un garde dont l'oubli est permissif n'est pas un
    garde. Les quatre valeurs se résolvent au ROUTEUR — trois permissions lues
    en base et un motif saisi — et le service n'a jamais à connaître ni rôle ni
    slug.
    """

    #: Ce que l'appelant a le droit de lire des finances de la famille. Décide
    #: du montant annoncé dans le refus, jamais du refus lui-même.
    view: FinanceView
    #: Vient de `enrollments:arrears:override`, jamais d'un test de rôle.
    may_override: bool
    #: Motif de la dérogation. Vide, la dérogation n'a pas lieu : le journal
    #: dirait qu'on est passé outre sans dire pourquoi.
    override_reason: str | None = None
    #: Faux quand le geste n'est pas un guichet. La politique y vaut `inform`,
    #: quoi qu'ait réglé l'établissement, et le garde sort avant toute lecture.
    may_refuse: bool = True

    #: Le geste de masse : il informe, il ne refuse jamais, et il n'affiche
    #: aucun montant puisqu'il n'affiche rien. La promotion de fin d'année s'en
    #: sert, l'amorçage d'une démonstration aussi.
    INFORM_ONLY: ClassVar[ArrearsClearance]

    def avec_motif(self, motif: str | None) -> ArrearsClearance:
        """La même clairance, plus le motif que l'appelant a saisi.

        Les droits se résolvent en dépendance, avant que le corps ne soit lu ;
        le motif, lui, vient du corps. Il se greffe donc ici plutôt que de
        voyager dans l'adresse — il nomme une famille, et une URL finit dans
        les journaux d'accès du serveur et chez tous les intermédiaires.
        """
        return replace(self, override_reason=motif)


ArrearsClearance.INFORM_ONLY = ArrearsClearance(
    view=FinanceView(amounts=False, status=False),
    may_override=False,
    override_reason=None,
    may_refuse=False,
)


async def prior_year_arrears(db: AsyncSession, student_id: int, *, before: date) -> PriorArrears:
    """Ce que l'élève doit encore sur les exercices commencés avant celui-ci.

    L'antériorité se juge sur `AcademicYear.start_date`, jamais sur
    l'identifiant : rien ne garantit que les années aient été créées dans
    l'ordre où elles se sont déroulées. C'est déjà le critère d'
    `enrollment_history.anterior_enrollments`, et il n'y a aucune raison qu'une
    seconde définition de « l'année d'avant » vive dans le dépôt.

    Le montant vient de `fees_paid.remaining_by_enrollment`, le seul endroit
    qui dise ce qu'une famille doit. Cette fonction a d'abord calculé sa propre
    somme, sur les seuls frais obligatoires, pendant que le bandeau affiché
    deux écrans plus tôt sommait tous les frais encore dus : le même assistant
    annonçait une dette et en opposait une autre, et le seuil que la direction
    avait fixé en lisant la première ne mordait pas là où elle croyait.

    Ici on ne fait plus que **cadrer** : quelles inscriptions regarder, et
    comment les nommer. Le cadrage appartient à l'appelant ; le montant, non.

    Le reste est borné à zéro **par inscription**. Un trop-perçu sur une année
    ne doit pas éponger la dette d'une autre : ce sont deux exercices, et la
    comptabilité de l'un ne solde pas l'autre.

    Un dossier rejeté ou annulé ne doit rien : `CLOSED_STATUSES` l'écarte, du
    même périmètre que partout ailleurs.
    """
    stmt = (
        select(Enrollment.id, AcademicYear.name)
        .join(AcademicYear, AcademicYear.id == Enrollment.academic_year_id)
        .where(
            Enrollment.student_id == student_id,
            AcademicYear.start_date < before,
            Enrollment.status.not_in(CLOSED_STATUSES),
        )
        .order_by(AcademicYear.start_date)
    )

    anterieures = [
        (int(enrollment_id), str(year_name))
        for enrollment_id, year_name in (await db.execute(stmt)).all()
    ]
    if not anterieures:
        return PriorArrears(amount=Decimal("0"), years=())

    # Une seule lecture pour tout l'eleve, puis on ne garde que les exercices
    # anterieurs : la boucle d'avant interrogeait la base deux fois par
    # inscription.
    par_inscription = await fees_paid.remaining_by_enrollment(db, student_id=student_id)

    total = Decimal("0")
    annees: list[str] = []
    for enrollment_id, year_name in anterieures:
        reste = par_inscription.get(enrollment_id, Decimal("0"))
        if reste <= 0:
            continue
        total += reste
        if year_name not in annees:
            annees.append(year_name)

    return PriorArrears(amount=total, years=tuple(annees))


async def ensure_enrollable(
    db: AsyncSession,
    *,
    year: AcademicYear,
    actor_id: int,
    clearance: ArrearsClearance,
    student_id: int | None = None,
    matricule: str | None = None,
) -> None:
    """Laisse passer, ou refuse en 402 avec ce que l'appelant a le droit de lire.

    L'ordre des sorties n'est pas décoratif :

    1. Le geste qui n'est pas un guichet sort en premier, sans une requête.
       C'est ce qui rend une promotion de masse aussi coûteuse qu'avant.
    2. Puis la politique. `off` et `inform` rendent la main après la seule
       lecture du singleton de réglages : une école qui n'a rien décidé ne paie
       jamais la moindre requête sur une dette.
    3. Puis seulement l'élève, et sa dette.

    Le refus est un 402 et non un 403 : le dépôt distingue déjà « il faut
    payer » de « vous n'avez pas le droit », et l'écran doit pouvoir proposer
    un chemin de paiement plutôt qu'un refus sec.
    """
    if not clearance.may_refuse:
        return

    politique = await arrears_policy.policy_in_force(db)
    if politique is None or not politique.blocks:
        return

    if student_id is None:
        student_id = await _student_id_du_matricule(db, matricule)
    if student_id is None:
        return

    ardoise = await prior_year_arrears(db, student_id, before=year.start_date)
    if ardoise.amount <= politique.block_threshold_xof:
        return

    motif = (clearance.override_reason or "").strip()
    if not clearance.may_override or not motif:
        raise _refus(ardoise, student_id=student_id, year=year, clearance=clearance)

    # La trace de la dérogation est le seul geste qu'aucun croisement de
    # journaux ne reconstitue : l'inscription, elle, a sa propre ligne, et
    # rien dedans ne dirait qu'on est passé outre une dette.
    await audit_log(
        db,
        entity_type="enrollment_arrears_override",
        action=AuditAction.UPDATE,
        user_id=actor_id,
        entity_id=student_id,
        new_values={
            "student_id": student_id,
            "academic_year_id": year.id,
            "arrears_amount": float(ardoise.amount),
            "arrears_years": list(ardoise.years),
            "block_threshold_xof": politique.block_threshold_xof,
            "reason": motif,
        },
        notes=motif,
    )
    logger.info(
        "Derogation inscription pour l'eleve %s sur %s par l'utilisateur %s : %s",
        student_id,
        year.name,
        actor_id,
        motif,
    )


async def _student_id_du_matricule(db: AsyncSession, matricule: str | None) -> int | None:
    """L'élève que ce matricule désigne, s'il en désigne un.

    Le formulaire « nouvel élève » n'a que cela pour reconnaître un ancien.
    Sans matricule saisi, on ne rapproche rien : refuser sur une ressemblance
    de nom ferait retenir un vrai nouvel élève qui porte le nom de son cousin,
    et il n'existe aucun recours au guichet.
    """
    nu = (matricule or "").strip()
    if not nu:
        return None
    trouve = (
        await db.execute(select(Student.id).where(Student.enrollment_number == nu))
    ).scalar_one_or_none()
    return int(trouve) if trouve is not None else None


def _refus(
    ardoise: PriorArrears,
    *,
    student_id: int,
    year: AcademicYear,
    clearance: ArrearsClearance,
) -> EnrollmentBlockedByArrearsError:
    """Compose le refus, en n'y mettant que ce que l'appelant a le droit de lire.

    Trois niveaux, ceux de `finance_visibility` :

    - `payments:read` — le montant, et la phrase qui le nomme.
    - `payments:status:read` — un booléen, et rien de plus. Une secrétaire peut
      savoir qu'un dossier est en dette sans apprendre la situation économique
      du foyer.
    - ni l'un ni l'autre — `None` des deux côtés, **jamais `0`** : un zéro se
      lit « la famille ne doit rien », ce qui est un mensonge.

    Le motif du refus, lui, est toujours dit : sans lui, la personne au guichet
    ne saurait pas vers qui envoyer la famille. Ce qui se tait, c'est le
    chiffre, pas la raison.

    `can_override` est un booléen et pas un nom : l'écran doit pouvoir proposer
    la dérogation sans révéler qui, dans l'école, en a le droit.
    """
    if clearance.view.amounts:
        chiffre = f"{ardoise.amount:,.0f}".replace(",", " ")
        annees = ", ".join(ardoise.years)
        message = (
            f"Réinscription bloquée : {chiffre} FCFA restent dus au titre de "
            f"{annees}. {_OU_REGULARISER}"
        )
    else:
        message = (
            f"Réinscription bloquée : un exercice précédent n'est pas soldé. {_OU_REGULARISER}"
        )

    return EnrollmentBlockedByArrearsError(
        {
            "code": BLOCKED_CODE,
            "message": message,
            "arrears_amount": float(ardoise.amount) if clearance.view.amounts else None,
            "has_arrears": True if clearance.view.status else None,
            "student_id": student_id,
            "academic_year_id": year.id,
            "can_override": clearance.may_override,
        }
    )
