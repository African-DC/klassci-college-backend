"""CLI — vérifier que chaque versement encaissé est ventilé pour son montant.

    python -m app.cli.check_allocations
    python -m app.cli.check_allocations --tenant rostan-bouake

LECTURE SEULE. Elle ne répare rien : elle nomme. Réparer choisirait à la place
d'un comptable où ranger de l'argent réel, et c'est précisément la décision
qu'une machine ne doit pas prendre seule.

## Pourquoi elle existe

Le point par catégorie ne lit QUE `payment_allocations`, jamais
`payments.amount`. Un versement dont les allocations manqueraient, ou ne
couvriraient pas son montant, sortirait de tous les totaux par catégorie sans
qu'aucun signal ne le dise, pendant que le journal de caisse continuerait de le
compter. C'est le contrôle a posteriori du trio décrit en tête de
`app/services/payments/allocation_invariant.py` — la contrainte unique et la
vérification à l'écriture en sont les deux autres. Elle juge par la même
fonction pure qu'eux : un audit qui jugerait autrement passerait ce que la
caisse refuse.

## Sortie

`0` — rien à signaler sur aucune base.
`1` — au moins un versement en défaut, listé. Le code de sortie est fait pour
qu'une surveillance s'en saisisse sans lire le texte, comme la commande
`frais:verifier-allocations` de KLASSCIv2 dont elle reprend le principe.

## Deux emplois

Le premier est périodique, sous surveillance. Le second est ponctuel : elle est
l'ÉTAPE 0 du déploiement de la migration 0079, qui pose la contrainte unique et
s'arrête si des doublons existent. La passer d'abord, c'est apprendre le
problème avant la fenêtre de déploiement plutôt que pendant.

## Une base par établissement

Comme `migrate_all`, elle les parcourt toutes, et pour la même raison : une
base oubliée est une école entière dont personne ne signalera rien. La liste
vient de `migrate_all.list_tenant_databases` — écrite une fois, avec ses
marqueurs de schéma et son filtrage par privilèges.
"""

import argparse
import asyncio
import logging
import sys

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

#: Combien de ruptures on rapporte par base. Au-delà, ce n'est plus une liste
#: d'incidents à traiter un par un, c'est un chemin d'écriture à retrouver.
_PLAFOND = 200


async def _auditer_un_tenant(tenant: str) -> int:
    """Le nombre de versements en défaut sur cette base. Aucune écriture."""
    from app.core.database import tenant_database_url
    from app.services.payments import allocation_invariant

    moteur = create_async_engine(tenant_database_url(tenant), pool_pre_ping=True)
    try:
        fabrique = async_sessionmaker(moteur, class_=AsyncSession, expire_on_commit=False)
        async with fabrique() as db:
            ruptures = await allocation_invariant.auditer(db, limite=_PLAFOND)
    finally:
        await moteur.dispose()

    if not ruptures:
        logger.info("  %s : aucune ventilation en défaut", tenant)
        return 0

    logger.error("  %s : %d versement(s) en défaut", tenant, len(ruptures))
    for rupture in ruptures:
        logger.error("    - %s", rupture.message())
    if len(ruptures) == _PLAFOND:
        logger.error(
            "    (liste arrêtée à %d : il y en a probablement davantage)",
            _PLAFOND,
        )
    return len(ruptures)


async def check_allocations(tenant: str | None = None) -> None:
    """Passe l'audit sur une base, ou sur toutes."""
    from app.cli.migrate_all import list_tenant_databases

    if tenant:
        tenants = [tenant]
    else:
        tenants = await list_tenant_databases()
        logger.info("Found %d tenant databases", len(tenants))
        if not tenants:
            # Le même refus que `migrate_all` : rendre « tout va bien » après
            # n'avoir rien trouvé serait le pire des deux résultats possibles.
            raise RuntimeError("No KLASSCI tenant database found; refusing to report success")

    total = 0
    for nom in tenants:
        logger.info("Audit de « %s »...", nom)
        total += await _auditer_un_tenant(nom)

    if total:
        logger.error(
            "%d versement(s) dont la ventilation ne couvre pas le montant. "
            "Aucun n'a été modifié : les reprendre avec un comptable.",
            total,
        )
        sys.exit(1)
    logger.info("Ventilation conforme sur %d base(s).", len(tenants))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Vérifier la ventilation des versements encaissés (lecture seule)"
    )
    parser.add_argument(
        "--tenant",
        default=None,
        help="Auditer une seule base (défaut : toutes les bases tenant)",
    )
    args = parser.parse_args()
    asyncio.run(check_allocations(args.tenant))


if __name__ == "__main__":
    main()
