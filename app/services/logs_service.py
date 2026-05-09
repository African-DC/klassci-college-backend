"""Read system logs via journalctl with secret redaction.

Risky endpoint by design (Path F). Mitigations:
- Service name must match a tight regex; never passed to a shell.
- Hard cap on the number of lines to bound memory.
- Multi-pattern regex redaction for Authorization headers, bearer tokens,
  passwords, JWT-shaped strings, and PAT prefixes.
- Returns a `redacted_count` so the operator sees the redaction worked.

On Windows / non-systemd hosts the call returns 501.
"""

import logging
import re
import subprocess
from dataclasses import dataclass

logger = logging.getLogger(__name__)

MAX_LINES = 5_000
SERVICE_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,49}$")


_REDACTION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)(authorization\s*[:=]\s*)(bearer\s+)?[\w.\-+/=]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(password|pwd|secret|api[_-]?key)\s*[:=]\s*\S+"), r"\1=[REDACTED]"),
    (re.compile(r"klc_pat_[0-9a-fA-F]+"), "[REDACTED-PAT]"),
    (
        re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
        "[REDACTED-JWT]",
    ),
    (re.compile(r"\b[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}\b"), "[REDACTED-EMAIL]"),
]


@dataclass
class LogReadResult:
    lines: list[str]
    truncated: bool
    redacted_count: int


def is_valid_service_name(name: str) -> bool:
    return bool(SERVICE_NAME_RE.match(name))


def redact(line: str) -> tuple[str, int]:
    redactions = 0
    for pattern, replacement in _REDACTION_PATTERNS:
        line, n = pattern.subn(replacement, line)
        redactions += n
    return line, redactions


def read_journalctl(service: str, lines: int) -> LogReadResult:
    """Run ``journalctl -u <service> -n <lines>`` and apply redaction.

    Raises NotImplementedError if journalctl is unavailable (Windows dev,
    macOS, non-systemd Linux). The router maps this to 501.
    """
    if not is_valid_service_name(service):
        raise ValueError(f"Invalid service name '{service}'")

    capped = min(lines, MAX_LINES)
    try:
        result = subprocess.run(
            ["journalctl", "-u", service, "-n", str(capped), "--no-pager", "--output=short-iso"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError as exc:
        raise NotImplementedError("journalctl not available on this host") from exc

    if result.returncode != 0:
        logger.warning("journalctl failed: %s", result.stderr[:500])
        raise RuntimeError(f"journalctl exit {result.returncode}: {result.stderr[:200]}")

    raw_lines = [ln for ln in result.stdout.splitlines() if ln]
    total_redactions = 0
    redacted_lines: list[str] = []
    for raw in raw_lines:
        clean, n = redact(raw)
        total_redactions += n
        redacted_lines.append(clean)

    return LogReadResult(
        lines=redacted_lines,
        truncated=lines > MAX_LINES,
        redacted_count=total_redactions,
    )
