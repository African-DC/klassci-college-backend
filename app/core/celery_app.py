"""Celery application — broker et backend Redis."""

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "klassci",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.tasks.timetable_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    result_expires=3600,  # 1 heure
)
