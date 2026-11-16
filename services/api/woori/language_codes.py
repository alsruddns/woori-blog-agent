"""Shared BCP 47 validation and canonicalization for configured languages."""

import langcodes


def normalize_language_tag(value: str) -> str:
    candidate = value.strip()
    if "_" in candidate or not langcodes.tag_is_valid(candidate):
        raise ValueError("Use a valid BCP 47 language tag")
    return str(langcodes.standardize_tag(candidate))
