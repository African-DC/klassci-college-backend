"""Personal Access Token service — generation, hashing, validation, scope check.

Token format on the wire: ``klc_pat_<32 hex>``  (40 chars total)
Stored hash:              SHA-256 hex of the full plaintext token (64 chars)
Display prefix:           first 12 chars of the plaintext, safe to log/render

SHA-256 is intentional (not bcrypt): PATs are 128-bit random strings, so
salt+slow-hashing buy nothing meaningful while costing CPU on every request.
"""

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.datetimes import utcnow_naive
from app.models.personal_access_token import PersonalAccessToken

PAT_PREFIX = "klc_pat_"
PAT_RANDOM_BYTES = 16
DEFAULT_EXPIRY_DAYS = 90


def is_pat_token(token: str) -> bool:
    return token.startswith(PAT_PREFIX)


def generate_token() -> tuple[str, str, str]:
    """Generate a new plaintext token + return (plaintext, hash, display_prefix).

    The plaintext MUST be returned to the caller exactly once and never stored.
    """
    plaintext = PAT_PREFIX + secrets.token_hex(PAT_RANDOM_BYTES)
    token_hash = hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
    return plaintext, token_hash, plaintext[:12]


def hash_token(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


async def create_pat(
    db: AsyncSession,
    *,
    user_id: int,
    name: str,
    scopes: list[str],
    expires_in_days: int = DEFAULT_EXPIRY_DAYS,
) -> tuple[PersonalAccessToken, str]:
    """Insert a new PAT and return both the row and the plaintext (one-shot)."""
    plaintext, token_hash, prefix = generate_token()
    pat = PersonalAccessToken(
        name=name,
        token_hash=token_hash,
        token_prefix=prefix,
        user_id=user_id,
        scopes=list(scopes),
        expires_at=utcnow_naive() + timedelta(days=expires_in_days),
    )
    db.add(pat)
    await db.flush()
    return pat, plaintext


async def lookup_pat(db: AsyncSession, plaintext: str) -> PersonalAccessToken | None:
    """Return the PAT if the plaintext matches a non-revoked, non-expired record."""
    if not is_pat_token(plaintext):
        return None
    token_hash = hash_token(plaintext)
    stmt = select(PersonalAccessToken).where(PersonalAccessToken.token_hash == token_hash)
    result = await db.execute(stmt)
    pat = result.scalar_one_or_none()
    if pat is None or pat.revoked_at is not None:
        return None
    if pat.expires_at < utcnow_naive():
        return None
    return pat


async def touch_last_used(db: AsyncSession, pat_id: int) -> None:
    """Update last_used_at — best-effort, never blocks the request."""
    stmt = (
        update(PersonalAccessToken)
        .where(PersonalAccessToken.id == pat_id)
        .values(last_used_at=utcnow_naive())
    )
    await db.execute(stmt)


async def revoke_pat(db: AsyncSession, pat_id: int) -> bool:
    """Mark a PAT as revoked. Returns True if a row was updated."""
    stmt = (
        update(PersonalAccessToken)
        .where(
            PersonalAccessToken.id == pat_id,
            PersonalAccessToken.revoked_at.is_(None),
        )
        .values(revoked_at=utcnow_naive())
    )
    result = await db.execute(stmt)
    return result.rowcount > 0


async def revoke_user_pats(db: AsyncSession, user_id: int) -> int:
    """Revoke every live token of one user. Returns how many were revoked.

    Used when an account loses its right to enter: ``users.is_active`` alone
    would not be enough, since a later reactivation would silently bring the
    tokens — and their scopes — back to life.
    """
    stmt = (
        update(PersonalAccessToken)
        .where(
            PersonalAccessToken.user_id == user_id,
            PersonalAccessToken.revoked_at.is_(None),
        )
        .values(revoked_at=utcnow_naive())
    )
    result = await db.execute(stmt)
    return int(result.rowcount or 0)


async def list_user_pats(db: AsyncSession, user_id: int) -> list[PersonalAccessToken]:
    stmt = (
        select(PersonalAccessToken)
        .where(PersonalAccessToken.user_id == user_id)
        .order_by(PersonalAccessToken.created_at.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


def scope_matches(scopes: list[str], required: str) -> bool:
    """Wildcard-aware scope check.

    ``super-admin:*`` covers ``super-admin:tenants:read`` and any other
    sub-segment. ``*`` covers everything.
    """
    if required in scopes:
        return True
    parts = required.split(":")
    for i in range(len(parts)):
        wildcard = ":".join(parts[:i]) + (":*" if i > 0 else "*")
        if wildcard in scopes:
            return True
    return False


def has_scope(pat: PersonalAccessToken, required: str) -> bool:
    return scope_matches(pat.scopes, required)
