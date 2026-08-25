"""Qui prévenir quand une inscription avance d'un cran.

Une inscription se déroule en trois gestes que trois personnes différentes
peuvent poser : on ouvre le dossier, on encaisse, on valide. Sans lien entre
eux, chaque geste attend que quelqu'un pense à regarder, et dans une école
personne ne regarde : on est au guichet, en classe, ou au téléphone.

Les destinataires sont désignés par la permission qui garde l'action, jamais
par un nom de rôle. Une école confie l'encaissement à sa secrétaire, une autre
à un caissier, une troisième au directeur : nommer un rôle ici obligerait à
modifier le produit école par école.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import notification_dispatch_service as dispatch

logger = logging.getLogger(__name__)

#: Garde l'encaissement d'un versement.
PERMISSION_ENCAISSER = "payments:create"

#: Garde la validation d'une inscription.
#:
#: C'etait `enrollments:update` tant que la validation n'avait pas de droit
#: propre. Le probleme n'etait pas le routage de la notification mais le
#: modele : confier la validation obligeait a ouvrir l'edition complete des
#: dossiers, et la permission n'apparaissait nulle part dans l'ecran des roles
#: puisqu'elle n'existait pas.
PERMISSION_VALIDER = "enrollments:validate"


async def prevenir_qu_il_faut_encaisser(
    db: AsyncSession,
    *,
    enrollment_id: int,
    student_name: str,
    class_name: str,
    acteur_id: int | None,
) -> None:
    """Le dossier est ouvert : quelqu'un doit encaisser.

    L'échec ne remonte pas. Prévenir est un effet de l'inscription, jamais sa
    condition : une cloche en panne ne doit pas empêcher d'inscrire un enfant.
    """
    try:
        await dispatch.dispatch_to_permission(
            db,
            PERMISSION_ENCAISSER,
            "enrollment_awaiting_payment",
            {
                "student_name": student_name,
                "class_name": class_name,
                # Le repli du dispatch lit `title` et `body` quand aucun gabarit
                # n'est defini : la notification reste lisible sans seed.
                "title": "Versement attendu",
                "body": f"{student_name} ({class_name}) vient d'être inscrit. "
                "Le premier versement reste à encaisser.",
            },
            action_url=f"/admin/enrollments/{enrollment_id}?action=encaisser",
            entity_type="enrollment",
            entity_id=enrollment_id,
            exclude_user_id=acteur_id,
        )
    except Exception:
        logger.exception("Notification d'encaissement echouee pour l'inscription %d", enrollment_id)


async def prevenir_qu_il_faut_valider(
    db: AsyncSession,
    *,
    enrollment_id: int,
    student_name: str,
    acteur_id: int | None,
) -> None:
    """Le versement est passé : l'inscription attend sa validation.

    N'est appelée que tant que l'inscription n'est pas validée. Une famille qui
    paie en plusieurs fois déclencherait sinon une alerte par versement, et
    c'est exactement ainsi qu'un compteur cesse d'être lu.
    """
    try:
        await dispatch.dispatch_to_permission(
            db,
            PERMISSION_VALIDER,
            "enrollment_awaiting_validation",
            {
                "student_name": student_name,
                "title": "Inscription à valider",
                "body": f"Le versement de {student_name} est enregistré. "
                "L'inscription attend votre validation.",
            },
            action_url=f"/admin/enrollments/{enrollment_id}?action=valider",
            entity_type="enrollment",
            entity_id=enrollment_id,
            exclude_user_id=acteur_id,
        )
    except Exception:
        logger.exception("Notification de validation echouee pour l'inscription %d", enrollment_id)
