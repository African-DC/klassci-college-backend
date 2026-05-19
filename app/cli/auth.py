"""CLI auth — store and retrieve service-account / personal-access tokens.

Backend selection (in order of attempt):
1. ``KLASSCI_TOKEN`` environment variable — wins over everything (CI / agents / 1-shot).
2. OS-native keyring (DPAPI on Windows, Keychain on macOS, SecretService on Gnome).
3. Encrypted file fallback (``~/.config/klassci/credentials.enc``) for headless
   Linux / Docker / WSL where SecretService is unavailable.

Plaintext on disk is never an option.
"""

import os
from pathlib import Path

import keyring
import keyring.errors

SERVICE = "klassci-college"
CONFIG_DIR = Path(os.path.expanduser("~/.config/klassci"))


def _ensure_backend() -> None:
    try:
        keyring.get_password(SERVICE, "__probe__")
    except (keyring.errors.NoKeyringError, keyring.errors.KeyringLocked):
        from keyrings.alt.file import EncryptedKeyring

        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        fallback = EncryptedKeyring()
        fallback.file_path = str(CONFIG_DIR / "credentials.enc")
        keyring.set_keyring(fallback)


def save_token(profile: str, token: str) -> None:
    _ensure_backend()
    keyring.set_password(SERVICE, profile, token)


def get_token(profile: str = "default") -> str | None:
    env = os.getenv("KLASSCI_TOKEN")
    if env:
        return env
    _ensure_backend()
    try:
        return keyring.get_password(SERVICE, profile)
    except keyring.errors.KeyringError:
        return None


def delete_token(profile: str = "default") -> None:
    _ensure_backend()
    try:
        keyring.delete_password(SERVICE, profile)
    except keyring.errors.PasswordDeleteError:
        pass
