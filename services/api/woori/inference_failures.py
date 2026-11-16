"""Bounded structured-output retry and immutable parse-failure archival."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from .ai import Draft, EngineFailure, Provider
from .db import connection

MAX_ARCHIVED_RESPONSE_CHARS = 16_384
RETRYABLE_JSON_ERRORS = {"local_model_json_invalid", "local_model_output_schema_invalid"}


def archive_parse_failure(
    error: EngineFailure,
    *,
    batch_id: UUID,
    topic_key: str,
    language_code: str,
    model: str,
    prompt_version: str,
) -> None:
    artifact = error.failure_artifact
    if not artifact or error.category not in RETRYABLE_JSON_ERRORS:
        return
    raw = str(artifact.get("raw_response", ""))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    excerpt = raw[:MAX_ARCHIVED_RESPONSE_CHARS]
    with connection() as conn:
        conn.execute(
            """INSERT INTO model_failure_artifacts
            (batch_id,topic_key,language_code,model,prompt_version,error_category,
             response_sha256,response_excerpt,response_chars,truncated)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
            (
                batch_id,
                topic_key,
                language_code,
                model,
                prompt_version,
                error.category,
                digest,
                excerpt,
                len(raw),
                len(raw) > len(excerpt),
            ),
        )
        conn.execute(
            "INSERT INTO audit_events(event_type,payload) VALUES ('inference.parse_failure.archived',%s)",
            (
                Jsonb(
                    {
                        "batch_id": str(batch_id),
                        "topic_key": topic_key,
                        "language_code": language_code,
                        "model": model,
                        "prompt_version": prompt_version,
                        "error_category": error.category,
                        "response_sha256": digest,
                        "response_chars": len(raw),
                        "truncated": len(raw) > len(excerpt),
                    }
                ),
            ),
        )


def generate_with_bounded_json_retry(
    provider: Provider,
    context: dict[str, Any],
    policy: dict[str, Any],
    *,
    archive: Callable[[EngineFailure], None] | None = None,
    max_attempts: int = 2,
) -> tuple[Draft, int]:
    """Retry only malformed structured output, once, with a different fixed seed."""
    attempts = max(1, min(2, max_attempts))
    for attempt in range(attempts):
        current = {**policy, "seed": int(policy.get("seed", 35)) + attempt}
        try:
            return provider.generate(context, current), attempt + 1
        except EngineFailure as exc:
            exc.attempts = attempt + 1
            if archive:
                archive(exc)
            if exc.category not in RETRYABLE_JSON_ERRORS or attempt + 1 >= attempts:
                raise
    raise AssertionError("bounded output retry exited unexpectedly")
