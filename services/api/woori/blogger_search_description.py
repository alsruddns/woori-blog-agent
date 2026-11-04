"""Revision-bound Blogger search descriptions without unsupported API fields."""

from __future__ import annotations

import hashlib
import html
import re
from collections.abc import Mapping
from typing import Any

from psycopg.types.json import Jsonb

MAX_SEARCH_DESCRIPTION_LENGTH = 150
_SOURCE_MARKER = re.compile(r"\[source:[A-Za-z0-9_-]+\]")
_MARKDOWN_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_MARKDOWN_NOISE = re.compile(r"(?:^|\s)(?:#{1,6}|>+|[-*+]\s+|\d+[.)]\s+)")
_HTML_TAG = re.compile(r"<[^>]*>")
_INTERNAL_PROCESS = re.compile(
    r"(?:research\s+package|research\s+worker|generated\s+by\s+codex|ai가 조사한 결과|수집된 데이터를 분석|이번 원고는)",
    re.IGNORECASE,
)


def _plain_article_text(value: str) -> str:
    text = html.unescape(value or "")
    text = _MARKDOWN_LINK.sub(r"\1", text)
    text = _HTML_TAG.sub(" ", text)
    text = _SOURCE_MARKER.sub("", text)
    text = _MARKDOWN_NOISE.sub(" ", text)
    text = re.sub(r"`{1,3}|[*_~]", "", text)
    text = re.sub(r"https?://\S+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _trim_at_boundary(value: str, maximum: int) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) <= maximum:
        return value
    clipped = value[:maximum + 1]
    # Word boundaries work for Latin scripts; CJK languages can be safely cut
    # at a character boundary because each Python code point is preserved.
    boundary = clipped.rfind(" ")
    if boundary >= int(maximum * 0.65):
        clipped = clipped[:boundary]
    else:
        clipped = clipped[:maximum]
    clipped = clipped.rstrip(" ,;:—-–·")
    return clipped.rstrip(".。!?！？")


def generate_search_description(
    *, title: str, body: str, language_code: str,
    existing_description: str | None = None,
) -> dict[str, Any]:
    """Reuse stored copy or summarize only the article's own lead text.

    This deterministic fallback does not create facts or translate the article.
    The registered BCP 47 locale is retained as provenance for the UI.
    """
    existing = _plain_article_text(existing_description or "")
    if _INTERNAL_PROCESS.search(existing):
        existing = ""
    source = "stored_metadata" if existing else "article_lead"
    plain = _plain_article_text(body)
    if existing:
        description = _trim_at_boundary(existing, MAX_SEARCH_DESCRIPTION_LENGTH)
    else:
        # Strip a duplicated opening title when authors include it in the body.
        plain_title = _plain_article_text(title)
        if plain_title and plain.casefold().startswith(plain_title.casefold()):
            plain = plain[len(plain_title):].lstrip(" .:：—–-")
        sentences = [part.strip() for part in re.split(r"(?<=[.!?。！？])\s+", plain) if part.strip()]
        selected = ""
        for sentence in sentences:
            if _INTERNAL_PROCESS.search(sentence):
                continue
            candidate = f"{selected} {sentence}".strip()
            if len(candidate) <= MAX_SEARCH_DESCRIPTION_LENGTH:
                selected = candidate
            else:
                if not selected:
                    selected = sentence
                break
        description = _trim_at_boundary(selected or plain, MAX_SEARCH_DESCRIPTION_LENGTH)
    return {
        "description": description,
        "language_code": language_code,
        "character_count": len(description),
        "generation_source": source,
        "status": "STORED_LOCALLY" if existing else ("GENERATED" if description else "APPLY_FAILED"),
        "blogger_status": "APPLY_PENDING" if description else "APPLY_FAILED",
        "blogger_api_supported": False,
        "manual_entry_required": bool(description),
        "html_meta_description_verified": False,
    }


def article_revision_sha256(*, title: str, body: str, language_code: str) -> str:
    value = f"{language_code}\n{title}\n{body}".encode()
    return hashlib.sha256(value).hexdigest()


def load_generated_description(
    conn: Any, *, content_version_id: str, article_sha256: str,
) -> dict[str, Any] | None:
    row = conn.execute(
        """SELECT payload FROM audit_events
        WHERE event_type='blogger.search_description.generated'
          AND payload->>'content_version_id'=%s AND payload->>'article_sha256'=%s
        ORDER BY id DESC LIMIT 1""",
        (content_version_id, article_sha256),
    ).fetchone()
    if not row:
        return None
    payload = row["payload"]
    description = str(payload.get("description") or "")
    return {
        "description": description,
        "language_code": str(payload.get("language_code") or ""),
        "character_count": len(description),
        "generation_source": "stored_generated_metadata",
        "status": "STORED_LOCALLY",
        "blogger_status": str(payload.get("blogger_status") or "APPLY_PENDING"),
        "blogger_api_supported": False,
        "manual_entry_required": bool(description),
        "html_meta_description_verified": False,
    }


def persist_generated_description(
    conn: Any, *, content_version_id: str, editorial_version_id: str | None,
    import_version_id: str | None, article_sha256: str,
    result: Mapping[str, Any],
) -> dict[str, Any]:
    """Append one local metadata audit record for a generated revision."""
    description = str(result.get("description") or "")
    if not description or result.get("generation_source") != "article_lead":
        return dict(result)
    conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
        (f"blogger-search-description:{content_version_id}:{article_sha256}",),
    )
    existing = conn.execute(
        """SELECT payload FROM audit_events
        WHERE event_type='blogger.search_description.generated'
          AND payload->>'content_version_id'=%s AND payload->>'article_sha256'=%s
        ORDER BY id DESC LIMIT 1""",
        (content_version_id, article_sha256),
    ).fetchone()
    if existing:
        stored = dict(result)
        stored.update({
            "description": str(existing["payload"].get("description") or description),
            "character_count": len(str(existing["payload"].get("description") or description)),
            "status": "STORED_LOCALLY",
            "blogger_status": "APPLY_PENDING",
        })
        return stored
    description_hash = hashlib.sha256(description.encode("utf-8")).hexdigest()
    conn.execute(
        """INSERT INTO audit_events(event_type,language_code,payload)
        VALUES ('blogger.search_description.generated',%s,%s)""",
        (str(result.get("language_code") or ""), Jsonb({
            "content_version_id": content_version_id,
            "editorial_version_id": editorial_version_id,
            "import_version_id": import_version_id,
            "article_sha256": article_sha256,
            "description": description,
            "description_sha256": description_hash,
            "character_count": len(description),
            "language_code": str(result.get("language_code") or ""),
            "generation_source": "article_lead",
            "status": "STORED_LOCALLY",
            "blogger_status": "APPLY_PENDING",
            "html_meta_description_verified": False,
        })),
    )
    return {**dict(result), "status": "STORED_LOCALLY", "blogger_status": "APPLY_PENDING"}
