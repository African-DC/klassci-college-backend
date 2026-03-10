"""JWT + bcrypt — création, décodage de tokens et hachage de mots de passe."""

from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.core.config import settings

# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------

def hash_password(plain: str) -> str:
    """Retourne le hash bcrypt du mot de passe."""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Vérifie qu'un mot de passe correspond à son hash."""
    return bcrypt.checkpw(plain.encode(), hashed.encode())


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------

def _build_token(data: dict[str, Any], expires_delta: timedelta) -> str:
    payload = data.copy()
    now = datetime.now(UTC)
    payload["iat"] = now
    payload["exp"] = now + expires_delta
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_access_token(user_id: int, tenant_id: str, email: str) -> str:
    """Crée un JWT access token (durée : ACCESS_TOKEN_EXPIRE_MINUTES)."""
    return _build_token(
        {"sub": str(user_id), "tenant_id": tenant_id, "email": email, "type": "access"},
        timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )


def create_refresh_token(user_id: int, tenant_id: str) -> str:
    """Crée un JWT refresh token (durée : REFRESH_TOKEN_EXPIRE_DAYS)."""
    return _build_token(
        {"sub": str(user_id), "tenant_id": tenant_id, "type": "refresh"},
        timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )


def decode_token(token: str) -> dict[str, Any]:
    """Décode et valide un JWT. Lève jwt.InvalidTokenError si invalide ou expiré.

    Une tolérance de 30 secondes est accordée pour absorber les petits décalages
    d'horloge entre le serveur émetteur et le serveur validateur.
    """
    return jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[settings.ALGORITHM],
        leeway=timedelta(seconds=30),
    )
