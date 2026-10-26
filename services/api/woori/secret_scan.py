"""Exact secret detection, excluding short accidental substrings within public UUIDs."""

import re

UUID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE
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
