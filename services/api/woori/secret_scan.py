"""Exact secret detection, excluding short accidental substrings within public UUIDs."""

import re
from urllib.parse import unquote, urlsplit

UUID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE
)
DATABASE_PASSWORD = re.compile(
    r"(?i)(\bpostgres(?:ql)?://[^\s:/@]+:)[^\s/@]+(@)"
)
SECRET_ASSIGNMENT = re.compile(
    r"(?i)(\b(?:[\w-]*password[\w-]*|[\w-]*passwd[\w-]*|[\w-]*token[\w-]*|"
    r"[\w-]*secret[\w-]*|api[_-]?key)[\"']?\s*[:=]\s*[\"']?)"
    r"([^\s,;\"']+)"
)


def contains_secret(text: str, secret: str) -> bool:
    if not secret:
        return False
    if len(secret) >= 16:
        return secret in text
    identifiers = [(match.start(), match.end()) for match in UUID.finditer(text)]
    return any(
        not any(start <= match.start() and match.end() <= end for start, end in identifiers)
        for match in re.finditer(re.escape(secret), text)
    )


def redact_sensitive_text(text: str) -> str:
    """Redact common credential forms before a diagnostic can be displayed or persisted."""
    redacted = DATABASE_PASSWORD.sub(r"\1[REDACTED]\2", text)
    return SECRET_ASSIGNMENT.sub(r"\1[REDACTED]", redacted)


def database_url_metadata(url: str) -> dict[str, str | int | bool | None]:
    """Return connection identity metadata while deliberately omitting credentials."""
    parsed = urlsplit(url)
    return {
        "scheme": parsed.scheme,
        "username": unquote(parsed.username or "") or None,
        "host": parsed.hostname,
        "port": parsed.port,
        "database": parsed.path.lstrip("/") or None,
        "credential_present": parsed.password is not None,
    }
