"""Facade rétrocompat — voir `app.services.pdf` package pour les sources.

Préférer les imports directs `from app.services.pdf import generate_X_pdf`
pour le nouveau code. Cette facade conserve les call sites historiques
`from app.services.pdf_service import generate_X_pdf` ; elle pourra
disparaître à la prochaine release une fois les imports migrés.
"""

from app.services.pdf import *  # noqa: F401, F403
from app.services.pdf import __all__  # noqa: F401
