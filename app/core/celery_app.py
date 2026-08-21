"""Celery application — broker, backend Redis, et ordonnanceur."""

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings
from app.core.datetimes import school_time_as_utc

celery_app = Celery(
    "klassci",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "app.tasks.timetable_tasks",
        "app.tasks.audit_tasks",
        "app.tasks.cash_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    result_expires=3600,  # 1 heure
)

# Ordonnanceur. Celery tourne en UTC (`timezone` ci-dessus), l'école vit dans
# `SCHOOL_TIMEZONE` : l'heure du balayage est donc TRADUITE, pas écrite en dur.
# La Côte d'Ivoire étant à GMT+0, cela donne aujourd'hui 00:10 UTC — mais une
# école d'un autre fuseau décalera l'ordonnanceur sans qu'on y touche, au lieu
# de voir le balayage tomber en plein service de guichet.
#
# Dix minutes après minuit et non minuit pile : un versement saisi à 23h59 doit
# être committé avant qu'on fige le théorique de sa journée.
_SWEEP_HOUR_UTC, _SWEEP_MINUTE_UTC = school_time_as_utc(0, 10)

celery_app.conf.beat_schedule = {
    "cash-close-stale-sessions": {
        "task": "cash.close_stale_sessions_all_tenants",
        "schedule": crontab(hour=_SWEEP_HOUR_UTC, minute=_SWEEP_MINUTE_UTC),
    },
}
