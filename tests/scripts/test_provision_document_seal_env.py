from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts.provision_document_seal_env import _encode, main, provision


def _write_shared_key(path: Path) -> None:
    private_key = Ed25519PrivateKey.from_private_bytes(b"K" * 32)
    private_encoded = _encode(
        private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    public_encoded = _encode(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    )
    path.write_text(
        "DOCUMENT_SEAL_ACTIVE_KEY_ID=shared-2026-01\n"
        f"DOCUMENT_SEAL_PRIVATE_KEY_B64={private_encoded}\n"
        "DOCUMENT_SEAL_PUBLIC_KEYS_JSON="
        f"{json.dumps({'shared-2026-01': public_encoded}, separators=(',', ':'))}\n",
        encoding="utf-8",
    )


def test_provision_is_idempotent_and_uses_shared_material(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    key_file = tmp_path / "document-seal.env"
    env_file.write_text("APP_ENV=production\nSECRET_KEY=legacy-secret\n", encoding="utf-8")
    _write_shared_key(key_file)

    first_updates = provision(env_file, key_file)
    first_content = env_file.read_text(encoding="utf-8")
    with patch("scripts.provision_document_seal_env.os.chmod", wraps=os.chmod) as chmod:
        second_updates = provision(env_file, key_file)

    assert first_updates == {
        "DOCUMENT_SEAL_ACTIVE_KEY_ID",
        "DOCUMENT_SEAL_PRIVATE_KEY_B64",
        "DOCUMENT_SEAL_PUBLIC_KEYS_JSON",
        "DOCUMENT_SEAL_LEGACY_SECRET_KEY",
    }
    assert second_updates == set()
    assert env_file.read_text(encoding="utf-8") == first_content
    assert 'DOCUMENT_SEAL_LEGACY_SECRET_KEY="legacy-secret"' in first_content
    assert "DOCUMENT_SEAL_PRIVATE_KEY_B64=" in first_content
    chmod.assert_any_call(env_file, 0o600)
    if os.name == "posix":
        assert env_file.stat().st_mode & 0o777 == 0o600


def test_provision_replaces_env_example_placeholders(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    key_file = tmp_path / "document-seal.env"
    env_file.write_text(
        "SECRET_KEY=legacy-secret\n"
        "DOCUMENT_SEAL_ACTIVE_KEY_ID=placeholder\n"
        "DOCUMENT_SEAL_PRIVATE_KEY_B64=\n"
        "DOCUMENT_SEAL_PUBLIC_KEYS_JSON={}\n"
        "DOCUMENT_SEAL_LEGACY_SECRET_KEY=\n",
        encoding="utf-8",
    )
    _write_shared_key(key_file)

    provision(env_file, key_file)
    content = env_file.read_text(encoding="utf-8")

    assert "DOCUMENT_SEAL_ACTIVE_KEY_ID=shared-2026-01" in content
    assert "DOCUMENT_SEAL_PUBLIC_KEYS_JSON={}" not in content
    assert content.count("DOCUMENT_SEAL_PRIVATE_KEY_B64=") == 1


def test_cli_accepts_the_exact_deploy_contract(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    key_file = tmp_path / "document-seal.env"
    with (
        patch.object(
            sys,
            "argv",
            ["provision", "--env-file", str(env_file), "--key-file", str(key_file)],
        ),
        patch("scripts.provision_document_seal_env.provision", return_value=set()) as mocked,
    ):
        main()

    mocked.assert_called_once_with(env_file, key_file)
