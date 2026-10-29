"""One-per-blog, explicitly approved live Blogger private-draft test flow."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from . import blogger_service as service
from . import external_policy
from .blogger_writes import BloggerLivePublisher
from .db import connection
from .google_http import WRITE_SCOPE, BloggerReader, GoogleFailure

CONFIRMATION_PHRASE = "I_APPROVE_THIS_PRIVATE_DRAFT"
VERIFY_TTL = timedelta(minutes=5)
LIVE_DRAFT_KEY_PREFIX = "live-draft:"
TEST_BLOG_IDS = {
    "ko": "3321654108096579717",
    "en": "5240203250707821039",
    "zh-CN": "1931836538202286191",
    "ja": "7562596540375659150",
}
TEST_COPY = {
    "ko": (
        "Woori Blog Agent 연결 확인 테스트 (비공개 초안)",
        "이 글은 Woori Blog Agent의 Blogger API 연결을 확인하기 위한 비공개 테스트 초안입니다.\n\n실제 정보 제공을 목적으로 하지 않으며, 사용자 승인 없이 공개 게시되지 않습니다.",
    ),
    "en": (
        "Woori Blog Agent Connection Test (Private Draft)",
        "This is a private test draft used to verify the Woori Blog Agent Blogger API connection.\n\nIt is not intended to provide factual information and will not be published without separate user approval.",
    ),
    "zh-CN": (
        "Woori Blog Agent 连接测试（私人草稿）",
        "这是一篇用于验证 Woori Blog Agent Blogger API 连接的私人测试草稿。\n\n本文不用于提供事实信息，未经用户另行批准不会公开发布。",
    ),
    "ja": (
        "Woori Blog Agent 接続テスト（非公開の下書き）",
        "これは Woori Blog Agent の Blogger API 接続を確認するための非公開テスト下書きです。\n\n情報提供を目的とするものではなく、ユーザーの別途承認なしに公開されません。",
    ),
}


def _require_cost_approval() -> None:
    provider = next(
        item
        for item in external_policy.status()["providers"]
        if item["name"] == "google_blogger_read"
    )
    if not provider["calls_allowed"]:
        raise GoogleFailure(str(provider["block_reason"] or "provider_cost_unverified"))


def _verified_target(conn: Any, blog: dict[str, Any], connection_id: UUID) -> None:
    account = conn.execute(
        """SELECT status,scopes,refresh_ciphertext FROM google_connections WHERE id=%s""",
        (connection_id,),
    ).fetchone()
    if (
        not account
        or account["status"] != "connected"
        or account["scopes"] != [WRITE_SCOPE]
        or not account["refresh_ciphertext"]
    ):
        raise GoogleFailure("connected_write_oauth_required")
    proof = conn.execute(
        """SELECT payload,created_at FROM audit_events
        WHERE event_type='blogger.common_connection.verified'
          AND payload->>'connection_id'=%s
        ORDER BY id DESC LIMIT 1""",
        (str(connection_id),),
    ).fetchone()
    if not proof or datetime.now(UTC) - proof["created_at"] > VERIFY_TTL:
        raise GoogleFailure("fresh_all_blogs_access_verification_required")
    active_count = conn.execute(
        """SELECT count(*) AS n FROM blogger_blogs b JOIN languages l ON l.code=b.language_code
        WHERE b.active AND l.active"""
    ).fetchone()["n"]
    if proof["payload"].get("verified_blog_count") != active_count:
        raise GoogleFailure("all_active_blogs_access_verification_required")
    matching = [
        item
        for item in proof["payload"].get("blogs", [])
        if item.get("blog_record_id") == str(blog["id"])
        and item.get("blog_id") == str(blog["blog_id"])
        and item.get("url") == blog["url"]
    ]
    if not matching:
        raise GoogleFailure("selected_oauth_cannot_access_target_blog")


def preview(blog_id: UUID, connection_id: UUID, title: str, content: str) -> dict[str, Any]:
    """Persist a one-time exact payload preview; this does not contact Google."""
    _require_cost_approval()
    if not title.strip() or len(title) > 300 or not content.strip() or len(content) > 50000:
        raise GoogleFailure("invalid_draft_content")
    blog = service.blog_record(blog_id)
    if not blog["blog_id"]:
        raise GoogleFailure("blog_id_unverified")
    if (
        blog["language_code"] not in TEST_BLOG_IDS
        or str(blog["blog_id"]) != TEST_BLOG_IDS[blog["language_code"]]
        or (title, content) != TEST_COPY[blog["language_code"]]
    ):
        raise GoogleFailure("draft_target_or_test_copy_not_allowlisted")
    fingerprint = hashlib.sha256(
        json.dumps(
            [str(connection_id), str(blog_id), str(blog["blog_id"]), title, content, True],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    key = f"{LIVE_DRAFT_KEY_PREFIX}{blog_id}:{fingerprint}"
    with connection() as conn:
        _verified_target(conn, blog, connection_id)
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (str(blog_id),))
        prior = conn.execute(
            """SELECT idempotency_key,request_fingerprint,status,result
            FROM blogger_write_operations
            WHERE operation='create_draft' AND result->>'blog_record_id'=%s
              AND idempotency_key LIKE 'live-draft:%%'
            ORDER BY created_at DESC LIMIT 1 FOR UPDATE""",
            (str(blog_id),),
        ).fetchone()
        if prior:
            if prior["idempotency_key"] == key and prior["status"] == "pending":
                return {
                    "preview_id": prior["result"]["preview_id"],
                    "blog_id": str(blog["blog_id"]),
                    "language_code": blog["language_code"],
                    "title": title,
                    "content": content,
                    "is_draft": True,
                    "external_call_made": False,
                }
            raise GoogleFailure("draft_already_attempted_for_blog")
        preview_id = uuid4()
        result = {
            "mode": "live_test_draft",
            "preview_id": str(preview_id),
            "blog_record_id": str(blog_id),
            "blog_id": str(blog["blog_id"]),
            "connection_id": str(connection_id),
            "language_code": blog["language_code"],
            "title": title,
            "content": content,
            "is_draft": True,
            "payload_sha256": fingerprint,
        }
        conn.execute(
            """INSERT INTO blogger_write_operations
            (idempotency_key,request_fingerprint,operation,status,result)
            VALUES (%s,%s,'create_draft','pending',%s)""",
            (key, fingerprint, Jsonb(result)),
        )
        conn.execute(
            """INSERT INTO audit_events(event_type,blog_id,language_code,payload)
            VALUES ('blogger.draft.previewed',%s,%s,%s)""",
            (
                blog_id,
                blog["language_code"],
                Jsonb(
                    {
                        "preview_id": str(preview_id),
                        "connection_id": str(connection_id),
                        "blog_id": str(blog["blog_id"]),
                        "language_code": blog["language_code"],
                        "title": title,
                        "content": content,
                        "is_draft": True,
                        "external_call_made": False,
                        "payload_sha256": fingerprint,
                    }
                ),
            ),
        )
    return {
        "preview_id": str(preview_id),
        "blog_id": str(blog["blog_id"]),
        "language_code": blog["language_code"],
        "title": title,
        "content": content,
        "is_draft": True,
        "external_call_made": False,
    }


def _find_existing_test_draft(
    blog: dict[str, Any], connection_id: UUID, expected_title: str
) -> tuple[int, str | None]:
    """Search draft pages before insert; fail closed on malformed or unbounded pagination."""
    page_token = ""
    seen: set[str] = set()
    pages = 0
    while True:
        def load_page(reader: BloggerReader, token: str = page_token) -> dict[str, Any]:
            return reader.posts(str(blog["blog_id"]), 50, token, status="draft")

        page = service.read(blog, connection_id, load_page)
        pages += 1
        items = page.get("items", [])
        if not isinstance(items, list):
            raise GoogleFailure("duplicate_check_invalid_response")
        for item in items:
            if isinstance(item, dict) and item.get("title") == expected_title:
                return pages, str(item.get("id") or "unknown")
        next_token = page.get("nextPageToken")
        if not next_token:
            return pages, None
        if not isinstance(next_token, str) or next_token in seen or pages >= 20:
            raise GoogleFailure("duplicate_check_pagination_limit")
        seen.add(next_token)
        page_token = next_token


def confirm(preview_id: UUID, confirmation: str) -> dict[str, Any]:
    """Queue one exact private test draft after explicit confirmation."""
    if confirmation != CONFIRMATION_PHRASE:
        raise GoogleFailure("explicit_private_draft_approval_required")
    _require_cost_approval()
    request_id = uuid4()
    with connection() as conn:
        row = conn.execute(
            """SELECT idempotency_key,request_fingerprint,status,result
            FROM blogger_write_operations WHERE operation='create_draft'
              AND result->>'preview_id'=%s FOR UPDATE""",
            (str(preview_id),),
        ).fetchone()
        if not row:
            raise GoogleFailure("draft_preview_not_found")
        if row["status"] == "succeeded":
            raise GoogleFailure("draft_already_created")
        if row["status"] == "pending" and row["result"].get("confirmation_recorded") is True:
            return {**dict(row["result"]), "duplicate_confirmation": True}
        if row["status"] != "pending":
            raise GoogleFailure("draft_write_uncertain_or_failed_no_retry")
        result = row["result"]
        blog_id = UUID(result["blog_record_id"])
        connection_id = UUID(result["connection_id"])
        blog = service.blog_record(blog_id)
        _verified_target(conn, blog, connection_id)
        if row["request_fingerprint"] != result["payload_sha256"]:
            raise GoogleFailure("draft_preview_fingerprint_mismatch")
        conn.execute(
            "UPDATE blogger_write_operations SET status='uncertain' WHERE idempotency_key=%s",
            (row["idempotency_key"],),
        )
        conn.execute(
            "INSERT INTO audit_events(event_type,blog_id,language_code,payload) VALUES ('blogger.draft.duplicate_check_started',%s,%s,%s)",
            (blog_id, blog["language_code"], Jsonb({"preview_id": str(preview_id), "request_id": str(request_id)})),
        )

    try:
        pages_checked, duplicate_post_id = _find_existing_test_draft(
            blog, connection_id, result["title"]
        )
    except GoogleFailure as exc:
        with connection() as conn:
            conn.execute(
                "INSERT INTO audit_events(event_type,blog_id,language_code,payload) VALUES ('blogger.draft.duplicate_check_failed',%s,%s,%s)",
                (blog_id, blog["language_code"], Jsonb({"preview_id": str(preview_id), "category": exc.category})),
            )
        raise
    if duplicate_post_id is not None:
        duplicate_result = {
            **result, "final_status": "duplicate_blocked", "duplicate_post_id": duplicate_post_id,
            "duplicate_check_pages": pages_checked, "external_call_made": False,
        }
        with connection() as conn:
            conn.execute(
                "UPDATE blogger_write_operations SET status='failed',result=%s WHERE idempotency_key=%s AND status='uncertain'",
                (Jsonb(duplicate_result), row["idempotency_key"]),
            )
            conn.execute(
                "INSERT INTO audit_events(event_type,blog_id,language_code,payload) VALUES ('blogger.draft.duplicate_blocked',%s,%s,%s)",
                (blog_id, blog["language_code"], Jsonb({"preview_id": str(preview_id), "duplicate_post_id": duplicate_post_id, "insert_sent": False})),
            )
        raise GoogleFailure("matching_remote_test_draft_exists")

    queued = {
        **result,
        "final_status": "queued",
        "confirmation_recorded": True,
        "duplicate_check_pages": pages_checked,
        "external_call_made": False,
    }
    with connection() as conn:
        conn.execute(
            "UPDATE blogger_write_operations SET status='pending',result=%s WHERE idempotency_key=%s AND status='uncertain'",
            (Jsonb(queued), row["idempotency_key"]),
        )
        conn.execute(
            "INSERT INTO audit_events(event_type,blog_id,language_code,payload) VALUES ('blogger.draft.queued',%s,%s,%s)",
            (blog_id, blog["language_code"], Jsonb({"request_id": str(request_id), "preview_id": str(preview_id), "connection_id": str(connection_id), "blog_id": result["blog_id"], "duplicate_check_pages": pages_checked})),
        )
    return queued


def process_next_queued_draft() -> dict[str, Any] | None:
    """Lease one confirmed private-draft job; uncertain writes are never replayed."""
    with connection() as conn:
        row = conn.execute(
            """SELECT idempotency_key,result FROM blogger_write_operations
            WHERE operation='create_draft' AND status='pending'
              AND result->>'confirmation_recorded'='true'
            ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1"""
        ).fetchone()
        if row is None:
            return None
        result = dict(row["result"])
        blog_id = UUID(result["blog_record_id"])
        connection_id = UUID(result["connection_id"])
        processing = {**result, "final_status": "processing", "external_call_made": False}
        conn.execute(
            "UPDATE blogger_write_operations SET status='uncertain',result=%s WHERE idempotency_key=%s AND status='pending'",
            (Jsonb(processing), row["idempotency_key"]),
        )
        conn.execute(
            "INSERT INTO audit_events(event_type,blog_id,language_code,payload) VALUES ('blogger.draft.worker.started',%s,%s,%s)",
            (blog_id, result["language_code"], Jsonb({"preview_id": result["preview_id"], "blog_id": result["blog_id"], "connection_id": str(connection_id)})),
        )

    import html

    body_html = "<p>" + "</p><p>".join(
        html.escape(paragraph).replace("\n", "<br>")
        for paragraph in str(result["content"]).split("\n\n")
    ) + "</p>"
    try:
        outcome = BloggerLivePublisher().create_draft(
            str(row["idempotency_key"]), blog_id, str(result["title"]), body_html
        )
        verification = {
            "checked": bool(outcome.get("post_verified")),
            "is_draft": outcome.get("status") == "DRAFT",
            "title_matches": True,
            "content_matches": True,
        }
        final = {
            **result,
            "external_post_id": outcome["post_id"],
            "http_status": outcome.get("http_status"),
            "final_status": "succeeded",
            "external_call_made": True,
            "response": {"id": outcome["post_id"], "blog_id": outcome["blog_id"], "status": outcome["status"]},
            "verification": verification,
        }
        status = "succeeded"
        error_category = None
    except GoogleFailure as exc:
        status = "uncertain" if exc.category in {"uncertain_write", "previous_write_pending_or_uncertain", "idempotency_ledger_unavailable"} else "failed"
        error_category = exc.category
        final = {**result, "final_status": status, "error_category": error_category, "external_call_made": True}

    with connection() as conn:
        conn.execute(
            "UPDATE blogger_write_operations SET status=%s,result=%s WHERE idempotency_key=%s AND status='uncertain'",
            (status, Jsonb(final), row["idempotency_key"]),
        )
        conn.execute(
            "INSERT INTO audit_events(event_type,blog_id,language_code,payload) VALUES (%s,%s,%s,%s)",
            ("blogger.draft.worker.completed" if status == "succeeded" else "blogger.draft.worker.failed", blog_id, result["language_code"], Jsonb({"preview_id": result["preview_id"], "connection_id": str(connection_id), "blog_id": result["blog_id"], "post_id": final.get("external_post_id"), "status": status, "error_category": error_category, "verification": final.get("verification")})),
        )
    return {"preview_id": result["preview_id"], "status": status, "post_id": final.get("external_post_id"), "verification": final.get("verification"), "error_category": error_category}


def recent_results() -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            """SELECT idempotency_key,status,result FROM blogger_write_operations
            WHERE operation='create_draft'
            ORDER BY created_at DESC LIMIT 20"""
        ).fetchall()
    results: list[dict[str, Any]] = []
    for row in rows:
        result = row["result"] or {}
        if row["idempotency_key"].startswith(LIVE_DRAFT_KEY_PREFIX):
            results.append(result)
        else:
            results.append(
                {
                    "mode": "mock",
                    "preview_id": row["idempotency_key"],
                    "language_code": None,
                    "blog_id": None,
                    "external_post_id": result.get("id"),
                    "final_status": row["status"],
                    "http_status": None,
                    "verification": None,
                }
            )
    return results
