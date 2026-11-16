"""Trusted local credential broker, generation only; never expose credentials to prompts.

This fixed project helper may load service configuration. Its caller may not
read .env, supply credentials, SQL, URLs, or use this lane for publication.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import psycopg
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[3]
API = "http://127.0.0.1:8100"
PATH = "/admin/research/content-imports/duplicate-check"


def unavailable(reason: str) -> dict[str, Any]:
    return {
        "status": "unknown",
        "local_status": "unknown",
        "remote_status": "not_checked",
        "draft_import_allowed": False,
        "blogger_read_complete": False,
        "publication_recheck_required": True,
        "reason": reason,
        "research_allowed": True,
        "local_save_allowed": True,
        "import_status": "pending",
        "hold_reason": "duplicate_check_unavailable",
    }


def check_generation(
    payload: dict[str, Any], *, transport: httpx.BaseTransport | None = None
) -> dict[str, Any]:
    from .config import settings
    from .content_imports import DuplicateCheckRequest, scheduled_duplicate_check

    request = DuplicateCheckRequest.model_validate(payload)
    if request.stage != "generation":
        raise ValueError("broker_generation_only")
    attempts: list[dict[str, Any]] = []
    try:
        with httpx.Client(
            base_url=API,
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(4, connect=1),
            transport=transport,
        ) as client:
            response = client.post(
                PATH,
                json=request.model_dump(mode="json"),
                headers={"Authorization": "Bearer " + settings().admin_token},
            )
        if response.status_code == 200:
            result = response.json()
            if isinstance(result, dict) and result.get("local_status") in {
                "not_found",
                "failed_only",
                "already_imported",
                "already_published",
                "unknown",
            }:
                return {**result, "lookup_route": "backend_api"}
        # Authentication/schema rejection is not an outage and cannot be bypassed.
        if response.status_code < 500:
            return unavailable("backend_request_rejected") | {"http_status": response.status_code}
        attempts.append({"route": "backend_api", "http_status": response.status_code})
    except (httpx.HTTPError, ValueError):
        attempts.append({"route": "backend_api", "status": "unavailable"})
    try:
        result = scheduled_duplicate_check(request)
        return {**result, "lookup_route": "repository", "lookup_attempts": attempts}
    except (psycopg.Error, HTTPException, OSError, ValueError):
        # Never leak config, SQL diagnostics, request values or credentials.
        attempts.append({"route": "repository", "status": "unavailable"})
    # A preserved index can prove presence, never completeness or absence.
    from .scheduled_import_inbox import _is_reparse_point

    root = ROOT / ".local" / "gpt-scheduled-import"
    try:
        if _is_reparse_point(root.parent) or _is_reparse_point(root):
            raise ValueError("unsafe_index")
        for folder in ("processed", "ready", "processing"):
            directory = root / folder
            if _is_reparse_point(directory):
                raise ValueError("unsafe_index")
            for file in sorted(directory.glob("*.json")):
                if _is_reparse_point(file) or file.stat().st_size > 262144:
                    continue
                data = json.loads(file.read_text(encoding="utf-8"))
                item = data.get("item", {})
                origin = data.get("scheduled_origin", data.get("manual_origin", {}))
                if (
                    origin.get("target_blog_id") == request.target_blog_id
                    and item.get("language_code") == request.language_code
                    and (
                        item.get("event_group_id") == request.event_group_id
                        or (request.content_id and item.get("content_id") == request.content_id)
                    )
                ):
                    return unavailable("preserved_index_match_requires_reconciliation") | {
                        "lookup_route": "preserved_index",
                        "matching_content_id": item.get("content_id"),
                        "research_allowed": False,
                        "local_save_allowed": False,
                    }
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return unavailable("duplicate_check_unavailable") | {"lookup_attempts": attempts}
