"""Install shared document-seal keys into a dotenv file without leaking secrets."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

_ASSIGNMENT_RE = re.compile(r"^(?:export\s+)?([A-Z][A-Z0-9_]*)=(.*)$")
_CURRENT_KEY_NAMES = {
    "DOCUMENT_SEAL_ACTIVE_KEY_ID",
    "DOCUMENT_SEAL_PRIVATE_KEY_B64",
    "DOCUMENT_SEAL_PUBLIC_KEYS_JSON",
}


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _parse_value(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return json.loads(value) if value[0] == '"' else value[1:-1]
    return value


def _read_assignments(lines: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in lines:
        match = _ASSIGNMENT_RE.match(line.strip())
        if match:
            values[match.group(1)] = _parse_value(match.group(2))
    return values


def _validated_shared_keys(key_file: Path) -> dict[str, str]:
    source = _read_assignments(key_file.read_text(encoding="utf-8").splitlines())
    missing = sorted(name for name in _CURRENT_KEY_NAMES if not source.get(name))
    if missing:
        raise RuntimeError("Shared document seal key file is incomplete: " + ", ".join(missing))

    private_raw = _decode(source["DOCUMENT_SEAL_PRIVATE_KEY_B64"])
    if len(private_raw) != 32:
        raise RuntimeError("DOCUMENT_SEAL_PRIVATE_KEY_B64 must encode exactly 32 bytes")
    public_encoded = _encode(
        Ed25519PrivateKey.from_private_bytes(private_raw)
        .public_key()
        .public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    )
    try:
        public_keys = json.loads(source["DOCUMENT_SEAL_PUBLIC_KEYS_JSON"])
    except json.JSONDecodeError as exc:
        raise RuntimeError("DOCUMENT_SEAL_PUBLIC_KEYS_JSON is invalid") from exc
    key_id = source["DOCUMENT_SEAL_ACTIVE_KEY_ID"]
    if not isinstance(public_keys, dict) or public_keys.get(key_id) != public_encoded:
        raise RuntimeError("The active public and private document seal keys do not match")
    return {name: source[name] for name in _CURRENT_KEY_NAMES}


def _merge_assignments(lines: list[str], desired: dict[str, str]) -> list[str]:
    output: list[str] = []
    written: set[str] = set()
    for line in lines:
        match = _ASSIGNMENT_RE.match(line.strip())
        key = match.group(1) if match else None
        if key not in desired:
            output.append(line)
        elif key not in written:
            output.append(f"{key}={desired[key]}")
            written.add(key)
    missing = [key for key in desired if key not in written]
    if missing:
        if output and output[-1].strip():
            output.append("")
        output.append("# KLASSCI institutional document seal (managed by deploy)")
        output.extend(f"{key}={desired[key]}" for key in missing)
    return output


def _secure_env_file(env_file: Path) -> None:
    os.chmod(env_file, 0o600)
    if os.name == "posix":
        final_stat = env_file.stat()
        if final_stat.st_mode & 0o777 != 0o600 or final_stat.st_uid != os.geteuid():
            raise RuntimeError("The document seal dotenv must be owned by the deploy user at 0600")


def provision(env_file: Path, key_file: Path) -> set[str]:
    if not env_file.is_file() or not key_file.is_file():
        raise RuntimeError("The destination dotenv and shared key files are required")

    original = env_file.read_text(encoding="utf-8")
    lines = original.splitlines()
    current = _read_assignments(lines)
    legacy_secret = current.get("DOCUMENT_SEAL_LEGACY_SECRET_KEY") or current.get("SECRET_KEY")
    if not legacy_secret:
        raise RuntimeError("SECRET_KEY is required to preserve legacy document verification")

    desired = _validated_shared_keys(key_file)
    desired["DOCUMENT_SEAL_LEGACY_SECRET_KEY"] = json.dumps(legacy_secret)
    changed = {key for key, value in desired.items() if current.get(key) != _parse_value(value)}
    if not changed:
        _secure_env_file(env_file)
        return set()

    updated_lines = _merge_assignments(lines, desired)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        dir=env_file.parent,
        delete=False,
    ) as temporary:
        temporary.write("\n".join(updated_lines) + "\n")
        temporary_path = Path(temporary.name)
    os.chmod(temporary_path, 0o600)
    os.replace(temporary_path, env_file)
    _secure_env_file(env_file)
    return changed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--key-file", type=Path, required=True)
    args = parser.parse_args()
    updated = provision(args.env_file, args.key_file)
    print("Document seal environment ready; updated keys: " + ", ".join(sorted(updated)))


if __name__ == "__main__":
    main()
