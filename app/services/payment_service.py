"""Facade rétrocompat — voir `app.services.payments` package pour les sources.

Préférer les imports directs `from app.services.payments import record_enrollment_payment`
pour le nouveau code. Cette facade est conservée pour ne pas casser les call
sites historiques `from app.services import payment_service` ; elle pourra
disparaître à la prochaine release une fois les imports migrés.
"""

from app.services.payments import *  # noqa: F401, F403
from app.services.payments import __all__  # noqa: F401
