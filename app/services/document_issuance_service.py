"""Service : émission + vérification des documents officiels (CEV).

Chaque document officiel (certificat, attestation, bulletin) crée une ligne
`document_issuances` et reçoit un **Cachet Électronique Visible (CEV)** :

- un **Datamatrix** (norme 2D-Doc) encodant l'URL de vérification publique
  `{PUBLIC_BASE_URL}/verifier/{tenant}/{token}` — scanné, il ouvre la page ;
- un **code CEV lisible** (`CEV-XXXX-XXXX-XXXX`) dérivé d'une **signature
  Ed25519** des données du document — infalsifiable sans la clé serveur,
  saisissable à la main pour vérifier sans scanner.

La clé Ed25519 est dérivée de `SECRET_KEY` (HKDF) : déterministe, stable entre
redémarrages, et jamais stockée en clair. La signature Ed25519 étant
déterministe (RFC 8032), le code CEV est reproductible donc revérifiable.
"""

from __future__ import annotations

import base64
import secrets
from dataclasses import dataclass
from datetime import datetime

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import current_tenant_id
from app.models.document_issuance import DocumentIssuance
from app.services.pdf._cev import datamatrix_svg

# Libellés FR des types de documents (affichés sur la page de vérification).
DOCUMENT_TYPE_LABELS_FR: dict[str, str] = {
    "certificat_scolarite": "Certificat de scolarité",
    "attestation_frequentation": "Attestation de fréquentation",
    "bulletin": "Bulletin de notes",
}

# Longueur du code CEV lisible (caractères base32, hors préfixe/tirets).
_CEV_LEN = 12


@dataclass(frozen=True)
class IssuedVerification:
    """Tout ce dont un générateur PDF a besoin pour imprimer le bloc CEV."""

    token: str
    reference: str
    verify_url: str
    cev_code: str  # format lisible "CEV-XXXX-XXXX-XXXX"
    datamatrix_svg: str


def _signing_key() -> Ed25519PrivateKey:
    """Dérive une clé Ed25519 stable depuis SECRET_KEY (HKDF-SHA256)."""
    seed = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"klassci-cev-ed25519-v1",
    ).derive(settings.SECRET_KEY.encode("utf-8"))
    return Ed25519PrivateKey.from_private_bytes(seed)


def _public_key() -> Ed25519PublicKey:
    return _signing_key().public_key()


def _canonical_payload(
    *,
    tenant: str,
    document_type: str,
    reference: str,
    student_name: str,
    class_name: str | None,
    academic_year: str | None,
    issued_at: datetime,
) -> bytes:
    """Sérialisation canonique signée (ordre + séparateur figés)."""
    parts = [
        "KCEV1",
        tenant,
        document_type,
        reference,
        student_name,
        class_name or "",
        academic_year or "",
        issued_at.strftime("%Y-%m-%dT%H:%M:%S"),
    ]
    return "".join(parts).encode("utf-8")


def _cev_code_from_signature(signature: bytes) -> str:
    """Code CEV lisible : base32 de la signature, tronqué, en groupes de 4."""
    b32 = base64.b32encode(signature).decode("ascii").rstrip("=")
    short = b32[:_CEV_LEN]
    groups = [short[i : i + 4] for i in range(0, len(short), 4)]
    return "CEV-" + "-".join(groups)


def _verify_url(token: str, tenant: str) -> str:
    base = settings.PUBLIC_BASE_URL.rstrip("/")
    return f"{base}/verifier/{tenant}/{token}"


def _normalize_cev(code: str) -> str:
    """Normalise un code CEV saisi à la main (casse, tirets, préfixe)."""
    cleaned = code.strip().upper().replace("-", "").replace(" ", "")
    if cleaned.startswith("CEV"):
        cleaned = cleaned[3:]
    return cleaned


async def issue_document(
    db: AsyncSession,
    *,
    document_type: str,
    reference: str,
    student_name: str,
    class_name: str | None = None,
    academic_year: str | None = None,
    student_id: int | None = None,
    issued_at: datetime | None = None,
) -> IssuedVerification:
    """Enregistre une émission et renvoie le bloc CEV (Datamatrix + code signé)."""
    tenant = current_tenant_id.get() or settings.LOCAL_TENANT_ID
    # Tronquer à la seconde : MySQL DATETIME(0) ARRONDIT les fractions de seconde,
    # ce qui décalerait la valeur stockée par rapport à celle signée et casserait
    # la revérification de signature. On signe et stocke exactement la même seconde.
    issued = (issued_at or datetime.utcnow()).replace(microsecond=0)
    token = secrets.token_urlsafe(32)

    signature = _signing_key().sign(
        _canonical_payload(
            tenant=tenant,
            document_type=document_type,
            reference=reference,
            student_name=student_name,
            class_name=class_name,
            academic_year=academic_year,
            issued_at=issued,
        )
    )
    cev_code = _cev_code_from_signature(signature)

    issuance = DocumentIssuance(
        token=token,
        cev_code=cev_code,
        document_type=document_type,
        reference=reference,
        student_name=student_name,
        class_name=class_name,
        academic_year=academic_year,
        student_id=student_id,
        issued_at=issued,
    )
    db.add(issuance)
    await db.commit()

    url = _verify_url(token, tenant)
    return IssuedVerification(
        token=token,
        reference=reference,
        verify_url=url,
        cev_code=cev_code,
        datamatrix_svg=datamatrix_svg(url),
    )


async def get_issuance_by_token(db: AsyncSession, token: str) -> DocumentIssuance | None:
    stmt = select(DocumentIssuance).where(DocumentIssuance.token == token).limit(1)
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_issuance_by_cev_code(db: AsyncSession, code: str) -> DocumentIssuance | None:
    """Recherche par code CEV saisi à la main (normalisé)."""
    normalized = _normalize_cev(code)
    if not normalized:
        return None
    # Reconstitue le format stocké "CEV-XXXX-XXXX-XXXX".
    groups = [normalized[i : i + 4] for i in range(0, len(normalized), 4)]
    stored = "CEV-" + "-".join(groups)
    stmt = select(DocumentIssuance).where(DocumentIssuance.cev_code == stored).limit(1)
    return (await db.execute(stmt)).scalar_one_or_none()


def verify_signature(issuance: DocumentIssuance, *, tenant: str) -> bool:
    """Revérifie la signature Ed25519 du document (détection de falsification)."""
    expected = _cev_code_from_signature(
        _signing_key().sign(
            _canonical_payload(
                tenant=tenant,
                document_type=issuance.document_type,
                reference=issuance.reference,
                student_name=issuance.student_name,
                class_name=issuance.class_name,
                academic_year=issuance.academic_year,
                issued_at=issuance.issued_at,
            )
        )
    )
    return secrets.compare_digest(expected, issuance.cev_code)
