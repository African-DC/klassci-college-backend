"""Les frais d'une réinscription, présentés à part de l'année en cours."""

from decimal import Decimal

from pydantic import BaseModel


class UpcomingEnrollmentFees(BaseModel):
    academic_year_name: str
    class_name: str | None = None
    total_due: Decimal
    total_paid: Decimal
    remaining: Decimal
