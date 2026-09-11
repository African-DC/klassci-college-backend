"""Ce qu'exige toute correction d'un versement : un motif écrit, et l'autorité.

Deux gestes corrigent une écriture de caisse — l'annuler, et déplacer une de
ses imputations vers le bon frais. Ils ne font pas la même chose, mais ils
posent la même question : *qui a le droit de revenir sur cette ligne, et
qu'écrit-il pour l'expliquer ?* Les deux règles vivent donc ici, à un seul
endroit, plutôt qu'en double chez chacun.

Elles étaient privées à `lifecycle`, du temps où l'annulation était la seule
correction possible. Les y laisser aurait fait importer un module de
transitions de statut par un module qui n'en fait aucune, ou — plus
probablement — recopier dix lignes de validation de motif avec un seuil qui
aurait fini par diverger.
"""

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessValidationError
from app.models.fee import Payment

#: La longueur minimale d'un motif, une fois les espaces réduits.
#: L'écran mesure la même chose, sur la même chaîne normalisée.
MOTIF_MINIMUM = 10

#: La colonne fait 500 caractères ; au-delà MySQL tronquerait sans le dire.
MOTIF_MAXIMUM = 500


def motif_valide(motif: str) -> str:
    """Un motif court n'est pas un motif.

    « erreur », « test », « ok » ne disent rien a qui relira le bordereau dans
    six mois — et c'est precisement a ce moment qu'on le relit. On exige une
    phrase, pas un mot.
    """
    propre = " ".join(motif.split())
    if len(propre) < MOTIF_MINIMUM:
        raise BusinessValidationError(
            "Indiquez le motif de la correction en une phrase : elle figurera sur "
            "le bordereau de caisse et dans le journal."
        )
    return propre[:MOTIF_MAXIMUM]


async def ensure_cashier_may_correct(
    db: AsyncSession, payment: Payment, cashier_id: int, *, geste: str
) -> None:
    """Un caissier ne corrige que sa propre saisie, journée encore ouverte.

    `geste` est le participe qui termine la phrase — « annulé », « réimputé ».
    Le message doit nommer ce qu'on vient de refuser : « ce versement ne peut
    plus être corrigé ici » laisserait la caissière chercher lequel de ses deux
    boutons a échoué.

    Après clôture, l'écart a été constaté et signé : revenir dessus rendrait
    faux un document déjà remis.
    """
    from app.repositories import cash_session_repository as cash_repo

    if payment.received_by != cashier_id:
        raise HTTPException(
            status_code=403,
            detail=(
                "Ce versement a été encaissé par une autre caisse. "
                "Demandez la correction à la comptabilité."
            ),
        )
    if await cash_repo.is_day_locked(db, cashier_id, payment.created_at.date()):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Votre journée de caisse est clôturée : ce versement ne peut plus être "
                f"{geste} ici. Demandez la correction à la comptabilité."
            ),
        )
