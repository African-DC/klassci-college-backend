"""Ce que l'école a décidé de faire d'une dette d'un exercice précédent.

Deux réglages seulement : la politique, et le seuil au-delà duquel `block`
refuse. Ils vivent sur `school_settings`, le singleton qui porte déjà une
vingtaine de préférences de même nature, et non dans une table à eux — un
réglage par établissement n'est pas une entité.

## Le défaut est l'identité, et c'est écrit ici

`policy_in_force` rend `None` quand la politique vaut `off`. `None` n'est pas
un échec de lecture : c'est « il n'y a rien à faire », et l'appelant sort à la
première ligne, sans avoir de quoi interroger la moindre dette. Une école qui
n'ouvre jamais cet écran ne voit donc aucun bandeau, ne subit aucun refus, et
ne paie pas une requête de plus — la lecture du singleton est la seule, et elle
s'arrête là.

C'est la forme du retour qui le garantit, pas un commentaire : un appelant qui
oublierait le cas `off` n'aurait de toute façon ni seuil ni politique en main.

## Deux lectures, deux fonctions, et ce n'est pas un doublon

`get_settings` sert l'écran des réglages : il passe par
`admin_service.get_school_settings`, qui crée la ligne au premier appel d'un
tenant neuf. `policy_in_force` sert le chemin de garde : il lit deux colonnes
et n'écrit JAMAIS. Un garde qui provisionne une ligne en passant écrirait dans
la base à chaque réinscription, et ferait dépendre une lecture d'une
transaction ouverte ailleurs.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit_log
from app.models.academic import ArrearsPolicy, SchoolSettings
from app.schemas.arrears_policy import ArrearsPolicyResponse, ArrearsPolicyUpdate
from app.services import admin_service


@dataclass(frozen=True)
class ArrearsPolicyInForce:
    """La politique d'un établissement qui en a activé une.

    `policy` n'y vaut jamais `OFF` : l'absence de politique est représentée par
    l'absence de cet objet, pas par une de ses valeurs. C'est ce qui empêche un
    appelant de lire un seuil qui n'a aucune raison de s'appliquer.
    """

    policy: ArrearsPolicy
    block_threshold_xof: int

    @property
    def blocks(self) -> bool:
        """Vrai quand la politique refuse ; faux quand elle se contente d'informer."""
        return self.policy is ArrearsPolicy.BLOCK


async def policy_in_force(db: AsyncSession) -> ArrearsPolicyInForce | None:
    """La politique de l'établissement, ou `None` quand il n'y a rien à faire.

    Relu à chaque fois, sans mémoire : le réglage se lève au milieu d'une
    journée de rentrée, et une valeur gardée en cache ferait inscrire
    l'après-midi sous la règle du matin.

    Un tenant fraîchement provisionné n'a pas encore de ligne de réglages :
    l'absence vaut `off`, comme la colonne.
    """
    stmt = select(
        SchoolSettings.arrears_policy,
        SchoolSettings.arrears_block_threshold_xof,
    ).limit(1)
    row = (await db.execute(stmt)).first()
    if row is None:
        return None
    policy = ArrearsPolicy(row[0])
    if policy is ArrearsPolicy.OFF:
        return None
    return ArrearsPolicyInForce(policy=policy, block_threshold_xof=int(row[1] or 0))


async def get_settings(db: AsyncSession) -> ArrearsPolicyResponse:
    """L'état du réglage, pour l'écran qui le présente."""
    school = await admin_service.get_school_settings(db)
    return ArrearsPolicyResponse.model_validate(school)


async def update_settings(
    db: AsyncSession, data: ArrearsPolicyUpdate, *, updated_by: int
) -> ArrearsPolicyResponse:
    """Applique la politique et laisse une trace de qui l'a changée, et quand.

    La trace n'est pas un ornement. C'est elle qui permet, des mois plus tard,
    de savoir sous quelle règle un dossier a été accepté, en la croisant avec
    le journal des inscriptions. Sans elle, il faudrait dater la règle sur
    chaque inscription — une colonne de plus sur `enrollments`, recopiée à
    chaque ligne, pour une information qui ne change que deux fois par an.

    Un PUT qui n'énonce que l'état déjà en place n'écrit rien et ne journalise
    rien : le journal enregistre des transitions, et il n'y en a aucune.
    """
    school = await admin_service.get_school_settings(db)
    anciennes = {
        "arrears_policy": ArrearsPolicy(school.arrears_policy).value,
        "arrears_block_threshold_xof": int(school.arrears_block_threshold_xof),
    }
    nouvelles = {
        "arrears_policy": data.arrears_policy.value,
        "arrears_block_threshold_xof": data.arrears_block_threshold_xof,
    }
    if nouvelles == anciennes:
        return ArrearsPolicyResponse.model_validate(school)

    async with db.begin_nested():
        school.arrears_policy = data.arrears_policy
        school.arrears_block_threshold_xof = data.arrears_block_threshold_xof
        await db.flush()
        await audit_log(
            db,
            entity_type="school_settings",
            action=AuditAction.UPDATE,
            user_id=updated_by,
            entity_id=school.id,
            old_values=anciennes,
            new_values=nouvelles,
        )
    await db.commit()
    return ArrearsPolicyResponse.model_validate(await admin_service.get_school_settings(db))
