"""Read-model-only duplicate suppression for manuscript lists.

Historical imports remain untouched. Similarity is deliberately conservative:
exact body matches dedupe within a blog/language, while near matches also need
the same normalized title and a high body similarity ratio.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

_MARKDOWN = re.compile(r"[`*_>#~\[\]()!]+")
_SPACE = re.compile(r"\s+")


def normalized_title(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return _SPACE.sub(" ", text).strip()


def normalized_body(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = _MARKDOWN.sub(" ", text)
    return _SPACE.sub(" ", text).strip()


def body_digest(value: Any) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def same_manuscript_content(title: Any, body: Any, prior_title: Any, prior_body: Any) -> bool:
    current = normalized_body(body)
    prior = normalized_body(prior_body)
    if not current or not prior:
        return False
    if hashlib.sha256(current.encode("utf-8")).digest() == hashlib.sha256(prior.encode("utf-8")).digest():
        return True
    if normalized_title(title) != normalized_title(prior_title) or min(len(current), len(prior)) / max(len(current), len(prior)) < 0.70:
        return False
    return SequenceMatcher(None, current, prior, autojunk=False).ratio() >= 0.88


def dedupe_manuscript_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Keep the newest representative per explicit lineage or confirmed body duplicate.

    Rows must arrive newest-first. Missing/ambiguous target blogs are isolated by
    import ID so unrelated blogs are never merged based on language alone.
    """
    kept: list[dict[str, Any]] = []
    lineage_keys: set[tuple[str, str, str]] = set()
    exact_body_keys: set[tuple[str, str, str]] = set()
    title_body_buckets: dict[tuple[str, str, str], list[str]] = {}
    suppressed = 0

    for source in rows:
        row = dict(source)
        lang = str(row.get("language_code") or "")
        target = str(row.get("target_blog_id") or f"unknown:{row.get('id', '')}")
        lineage = str(row.get("representative_group") or "")
        lineage_key = (target, lang, lineage) if lineage else None
        title = normalized_title(row.get("title"))
        body = normalized_body(row.get("body_markdown", row.get("body", "")))
        normalized_digest = hashlib.sha256(body.encode("utf-8")).hexdigest() if body else ""
        exact_key = (target, lang, normalized_digest or f"empty:{row.get('id', len(kept))}")
        near_key = (target, lang, title)

        duplicate = bool(lineage_key and lineage_key in lineage_keys) or exact_key in exact_body_keys
        if not duplicate and title and len(body) >= 120:
            for prior_body in title_body_buckets.get(near_key, []):
                length_ratio = min(len(body), len(prior_body)) / max(len(body), len(prior_body))
                if length_ratio >= 0.70 and SequenceMatcher(None, body, prior_body, autojunk=False).ratio() >= 0.88:
                    duplicate = True
                    break

        if duplicate:
            suppressed += 1
            continue

        if lineage_key:
            lineage_keys.add(lineage_key)
        exact_body_keys.add(exact_key)
        if title and len(body) >= 120:
            title_body_buckets.setdefault(near_key, []).append(body)
        row["body_sha256"] = body_digest(row.get("body_markdown", row.get("body", "")))
        kept.append(row)

    return kept, suppressed
