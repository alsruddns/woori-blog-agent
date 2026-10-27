"""One-per-blog, explicitly approved live Blogger private-draft test flow."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
from psycopg.types.json import Jsonb

from . import blogger_service as service
from . import external_policy
from . import google_oauth as oauth
from .db import connection
from .external_policy import FreeQuotaExceeded
from .google_http import BASE, WRITE_SCOPE, BloggerReader, GoogleFailure, classify, numeric_id

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


def _record(
    blog: dict[str, Any],
    connection_id: UUID,
    request_id: UUID,
    status: str,
    http_status: int | None = None,
    category: str | None = None,
) -> None:
    service.record(
        request_id, blog, connection_id, "create_draft", 1, status, http_status, category
    )


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
    """Make exactly one POST after explicit confirmation of the stored preview."""
    if confirmation != CONFIRMATION_PHRASE:
        raise GoogleFailure("explicit_private_draft_approval_required")
    _require_cost_approval()
    request_id = uuid4()
    duplicate_found = False
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
        if row["status"] != "pending":
            raise GoogleFailure("draft_write_uncertain_or_failed_no_retry")
        result = row["result"]
        blog_id = UUID(result["blog_record_id"])
        connection_id = UUID(result["connection_id"])
        blog = service.blog_record(blog_id)
        _verified_target(conn, blog, connection_id)
        if row["request_fingerprint"] != result["payload_sha256"]:
            raise GoogleFailure("draft_preview_fingerprint_mismatch")
        # A remote duplicate check precedes the one-shot write. An exact title match
        # blocks the insert even if its body differs; this test title is unique and fixed.
        pages_checked, duplicate_post_id = _find_existing_test_draft(
            blog, connection_id, result["title"]
        )
        if duplicate_post_id is not None:
            duplicate_result = {
                **result,
                "final_status": "duplicate_blocked",
                "duplicate_post_id": duplicate_post_id,
                "duplicate_check_pages": pages_checked,
                "external_call_made": False,
            }
            conn.execute(
                "UPDATE blogger_write_operations SET status='duplicate_blocked',result=%s WHERE idempotency_key=%s",
                (Jsonb(duplicate_result), row["idempotency_key"]),
            )
            conn.execute(
                """INSERT INTO audit_events(event_type,blog_id,language_code,payload)
                VALUES ('blogger.draft.duplicate_blocked',%s,%s,%s)""",
                (
                    blog_id,
                    blog["language_code"],
                    Jsonb(
                        {
                            "request_id": str(request_id),
                            "preview_id": str(preview_id),
                            "blog_id": result["blog_id"],
                            "language_code": result["language_code"],
                            "duplicate_post_id": duplicate_post_id,
                            "draft_list_pages": pages_checked,
                            "insert_sent": False,
                        }
                    ),
                ),
            )
            duplicate_found = True
        else:
            conn.execute(
                """INSERT INTO audit_events(event_type,blog_id,language_code,payload)
                VALUES ('blogger.draft.duplicate_check_completed',%s,%s,%s)""",
                (
                    blog_id,
                    blog["language_code"],
                    Jsonb(
                        {
                            "request_id": str(request_id),
                            "preview_id": str(preview_id),
                            "blog_id": result["blog_id"],
                            "draft_list_pages": pages_checked,
                            "matching_title_found": False,
                            "insert_sent": False,
                        }
                    ),
                ),
            )
            # Mark uncertain before network I/O; a crash can never cause an automatic replay.
            conn.execute(
                "UPDATE blogger_write_operations SET status='uncertain' WHERE idempotency_key=%s",
                (row["idempotency_key"],),
            )
            conn.execute(
                """INSERT INTO audit_events(event_type,blog_id,language_code,payload)
                VALUES ('blogger.draft.requested',%s,%s,%s)""",
                (
                    blog_id,
                    blog["language_code"],
                    Jsonb(
                        {
                            "request_id": str(request_id),
                            "preview_id": str(preview_id),
                            "connection_id": str(connection_id),
                            "blog_id": result["blog_id"],
                            "language_code": result["language_code"],
                            "title": result["title"],
                            "content": result["content"],
                            "is_draft": True,
                            "attempt": 1,
                        }
                    ),
                ),
            )
    if duplicate_found:
        raise GoogleFailure("matching_remote_test_draft_exists")
    _record(blog, connection_id, request_id, "requested")
    failure_status: str
    http_status: int | None
    category: str | None
    response_payload: dict[str, Any]
    try:
        token = oauth.access_token(connection_id)
        with external_policy.client(
            "google_blogger_read", "blogger_draft_create", timeout=20
        ) as http:
            response = http.post(
                f"{BASE}/blogs/{numeric_id(result['blog_id'])}/posts",
                params={"isDraft": "true"},
                json={"title": result["title"], "content": result["content"]},
                headers={"Authorization": "Bearer " + token},
            )
    except FreeQuotaExceeded:
        failure_status, http_status, category = "failed", None, "free_quota_exceeded"
        response_payload = {}
    except httpx.TransportError:
        failure_status, http_status, category = "uncertain", None, "network_uncertain"
        response_payload = {}
    except GoogleFailure as exc:
        failure_status, http_status, category = "failed", exc.status, exc.category
        response_payload = {}
    else:
        http_status = response.status_code
        try:
            response_payload = response.json()
            if not isinstance(response_payload, dict):
                raise TypeError
        except (ValueError, TypeError):
            response_payload = {}
        if not response.is_success:
            failure_status, category = "failed", classify(response)
        elif not response_payload.get("id"):
            failure_status, category = "uncertain", "successful_response_missing_post_id"
        else:
            failure_status, category = "succeeded", None
    safe_response = {
        key: response_payload.get(key)
        for key in ("id", "blog", "title", "content", "status", "published", "url")
        if key in response_payload
    }
    final = {
        **result,
        "http_status": http_status,
        "response": safe_response,
        "external_post_id": str(response_payload.get("id", "")) or None,
        "verification": {
            "checked": False,
            "is_draft": None,
            "title_matches": None,
            "content_matches": None,
        },
        "final_status": failure_status,
        "error_category": category,
    }
    with connection() as conn:
        conn.execute(
            "UPDATE blogger_write_operations SET status=%s,result=%s WHERE idempotency_key=%s",
            (failure_status, Jsonb(final), row["idempotency_key"]),
        )
        conn.execute(
            """INSERT INTO audit_events(event_type,blog_id,language_code,payload)
            VALUES (%s,%s,%s,%s)""",
            (
                "blogger.draft.succeeded"
                if failure_status == "succeeded"
                else "blogger.draft.failed",
                blog_id,
                blog["language_code"],
                Jsonb(
                    {
                        "request_id": str(request_id),
                        "preview_id": str(preview_id),
                        "connection_id": str(connection_id),
                        "blog_id": result["blog_id"],
                        "language_code": result["language_code"],
                        "title": result["title"],
                        "content": result["content"],
                        "is_draft": True,
                        "http_status": http_status,
                        "response": safe_response,
                        "post_id": final["external_post_id"],
                        "status": failure_status,
                        "error_category": category,
                    }
                ),
            ),
        )
    _record(
        blog,
        connection_id,
        request_id,
        "succeeded" if failure_status == "succeeded" else "failed",
        http_status,
        category,
    )
    if failure_status != "succeeded":
        raise GoogleFailure(category or "draft_insert_failed", http_status)

    post_id = numeric_id(str(response_payload["id"]))
    try:
        reader = BloggerReader(
            external_policy.client("google_blogger_read", "blogger_read", timeout=20),
            lambda: oauth.access_token(connection_id),
            lambda operation, attempt, status, code, error: service.record(
                request_id, blog, connection_id, operation, attempt, status, code, error
            ),
        )
        try:
            checked = reader.post(result["blog_id"], post_id)
        finally:
            reader.transport.close()
        verification = {
            "checked": True,
            "is_draft": str(checked.get("status", "")).casefold() == "draft",
            "title_matches": checked.get("title") == result["title"],
            "content_matches": checked.get("content") == result["content"],
        }
    except GoogleFailure as exc:
        verification = {
            "checked": False,
            "is_draft": None,
            "title_matches": None,
            "content_matches": None,
            "error_category": exc.category,
        }
    final["verification"] = verification
    with connection() as conn:
        conn.execute(
            "UPDATE blogger_write_operations SET result=%s WHERE idempotency_key=%s",
            (Jsonb(final), row["idempotency_key"]),
        )
        conn.execute(
            """INSERT INTO audit_events(event_type,blog_id,language_code,payload)
            VALUES ('blogger.draft.rechecked',%s,%s,%s)""",
            (
                blog_id,
                blog["language_code"],
                Jsonb({"request_id": str(request_id), "post_id": post_id, **verification}),
            ),
        )
    return final


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
