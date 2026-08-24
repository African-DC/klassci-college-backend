"""Validated key material for KLASSCI institutional document seals."""

from __future__ import annotations

import base64
import hashlib
import json

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import settings


def b64decode(value: str) -> bytes:
    padded = value.strip() + "=" * (-len(value.strip()) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def active_private_key() -> Ed25519PrivateKey:
    encoded = settings.DOCUMENT_SEAL_PRIVATE_KEY_B64.strip()
    if encoded:
        seed = b64decode(encoded)
        if len(seed) != 32:
            raise RuntimeError("DOCUMENT_SEAL_PRIVATE_KEY_B64 must encode exactly 32 bytes")
        return Ed25519PrivateKey.from_private_bytes(seed)

    if settings.APP_ENV.lower() in {"production", "prod"}:
        raise RuntimeError("DOCUMENT_SEAL_PRIVATE_KEY_B64 is required in production")
    seed = hashlib.sha256(b"klassci-college-development-document-seal-v2").digest()
    return Ed25519PrivateKey.from_private_bytes(seed)


def public_keyring() -> dict[str, Ed25519PublicKey]:
    try:
        configured = json.loads(settings.DOCUMENT_SEAL_PUBLIC_KEYS_JSON or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError("DOCUMENT_SEAL_PUBLIC_KEYS_JSON must be valid JSON") from exc
    if not isinstance(configured, dict):
        raise RuntimeError("DOCUMENT_SEAL_PUBLIC_KEYS_JSON must be a JSON object")

    keyring: dict[str, Ed25519PublicKey] = {}
    for key_id, encoded in configured.items():
        if not isinstance(key_id, str) or not isinstance(encoded, str):
            raise RuntimeError("Document seal public key entries must be strings")
        raw = b64decode(encoded)
        if len(raw) != 32:
            raise RuntimeError(f"Public key {key_id!r} must encode exactly 32 bytes")
        keyring[key_id] = Ed25519PublicKey.from_public_bytes(raw)

    keyring[settings.DOCUMENT_SEAL_ACTIVE_KEY_ID] = active_private_key().public_key()
    return keyring


def legacy_signing_key() -> Ed25519PrivateKey:
    legacy_secret = settings.DOCUMENT_SEAL_LEGACY_SECRET_KEY.strip()
    if not legacy_secret:
        if settings.APP_ENV.lower() in {"production", "prod"}:
            raise RuntimeError("DOCUMENT_SEAL_LEGACY_SECRET_KEY is required in production")
        legacy_secret = settings.SECRET_KEY
    seed = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"klassci-cev-ed25519-v1",
    ).derive(legacy_secret.encode("utf-8"))
    return Ed25519PrivateKey.from_private_bytes(seed)
