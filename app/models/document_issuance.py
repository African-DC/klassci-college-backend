"""Émission de document officiel — registre pour la vérification publique.

Chaque génération d'un document officiel (certificat, attestation, bulletin)
crée une ligne ici avec un jeton non devinable. Un QR code encodant
`{PUBLIC_BASE_URL}/verifier/{tenant}/{token}` est imprimé sur le PDF ; le
public scanne le QR et atterrit sur une page qui confirme l'authenticité du
document à partir de ce registre.
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin


class DocumentIssuance(Base, TimestampMixin):
    """Registre d'émission d'un document officiel (1 ligne par génération)."""

    __tablename__ = "document_issuances"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # Jeton public non devinable (secrets.token_urlsafe(32) → ~43 chars),
    # encodé dans le Datamatrix du cachet (URL de vérification).
    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    # Code CEV lisible (signature Ed25519 tronquée, base32), saisissable à la
    # main sur le portail pour vérifier sans scanner. Ex: "7F3A9B2C1E40".
    cev_code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    # Code interne du type : certificat_scolarite / attestation_frequentation / bulletin.
    document_type: Mapped[str] = mapped_column(String(50), nullable=False)
    reference: Mapped[str] = mapped_column(String(100), nullable=False)
    student_name: Mapped[str] = mapped_column(String(200), nullable=False)
    class_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    academic_year: Mapped[str | None] = mapped_column(String(50), nullable=True)
    student_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
