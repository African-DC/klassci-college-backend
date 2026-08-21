"""Datetime helpers.

The DB uses naive `DateTime` columns (no `timezone=True`) so we
strip tzinfo from UTC `datetime.now()` everywhere. This helper exists
so the strip is one-line and consistent.
"""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo


def utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# Fuseau de l'établissement. La Côte d'Ivoire est à GMT+0 : minuit local est
# donc aujourd'hui minuit UTC, et les serveurs (démo comme production) tournent
# eux-mêmes en UTC. Cette égalité est une coïncidence, pas une propriété : le
# jour où une école d'un autre fuseau arrive, une clôture d'office calée sur
# l'UTC tomberait en plein service de guichet. La journée de caisse est donc
# calculée ici, explicitement, dans le fuseau de l'école.
SCHOOL_TIMEZONE = ZoneInfo("Africa/Abidjan")


def current_business_date(*, tz: ZoneInfo = SCHOOL_TIMEZONE) -> date:
    """Date de la journée de guichet en cours, dans le fuseau de l'école.

    À ne pas remplacer par `date.today()` : celui-ci lit l'horloge du serveur,
    qui est en UTC et ne dit rien de l'heure qu'il est devant la caisse.
    """
    return datetime.now(tz).date()


def school_time_as_utc(
    hour: int, minute: int, *, tz: ZoneInfo = SCHOOL_TIMEZONE
) -> tuple[int, int]:
    """Traduit une heure locale de l'école en heure UTC, pour l'ordonnanceur.

    Celery tourne en UTC : y écrire « minuit » en dur ne veut dire minuit
    devant la caisse que tant que l'école est à GMT+0. Dériver l'heure ici
    empêche l'ordonnanceur et `SCHOOL_TIMEZONE` de diverger le jour où une
    école d'un autre fuseau arrive — un balayage décalé couperait une journée
    de caisse en plein service.

    Le décalage est lu sur la date du jour. Les fuseaux d'Afrique de l'Ouest
    n'ont pas d'heure d'été ; un fuseau qui en aurait une demanderait un
    crontab recalculé, pas figé au démarrage.
    """
    local = datetime.now(tz).replace(hour=hour, minute=minute, second=0, microsecond=0)
    as_utc = local.astimezone(UTC)
    return as_utc.hour, as_utc.minute
