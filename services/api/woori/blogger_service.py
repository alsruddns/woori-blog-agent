"""Database-selected Blogger reads with per-language quotas and durable request history."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from . import external_policy
from . import google_oauth as oauth
from .db import connection
from .google_http import WRITE_SCOPE, BloggerReader, GoogleFailure, client, numeric_id


def blog_record(blog_id: UUID) -> dict[str, Any]:
    with connection() as conn:
        row = conn.execute(
            """SELECT b.*,l.active AS language_active,lim.read_enabled,lim.max_page_size,
            g.status AS oauth_status FROM blogger_blogs b JOIN languages l ON l.code=b.language_code
            JOIN language_execution_limits lim ON lim.language_code=l.code
            LEFT JOIN google_connections g ON g.id=b.oauth_connection_id WHERE b.id=%s""",
            (blog_id,),
        ).fetchone()
    if row is None:
        raise GoogleFailure("blog_not_found")
    if not row["active"] or not row["language_active"] or not row["read_enabled"]:
        raise GoogleFailure("language_or_blog_disabled")
    return row


def record(
    request_id: UUID,
    blog: dict[str, Any],
    connection_id: UUID,
    operation: str,
    attempt: int,
    status: str,
    http_status: int | None,
    category: str | None,
) -> None:
    blocked = False
    with connection() as conn:
        if status == "requested" and blog["language_code"] is None:
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                ("oauth:" + str(connection_id),),
            )
            count = conn.execute(
                """SELECT count(*) AS n FROM blogger_api_calls WHERE connection_id=%s
                AND language_code IS NULL AND status='requested'
                AND created_at>now()-interval '1 minute'""",
                (connection_id,),
            ).fetchone()
            assert count
            blocked = count["n"] >= 30
            if blocked:
                status, category = "blocked", "local_rate_limit"
        elif status == "requested":
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (blog["language_code"],)
            )
            limit = conn.execute(
                "SELECT requests_per_minute FROM language_execution_limits WHERE language_code=%s",
                (blog["language_code"],),
            ).fetchone()
            count = conn.execute(
                "SELECT count(*) AS n FROM blogger_api_calls WHERE language_code=%s AND status='requested' AND created_at>now()-interval '1 minute'",
                (blog["language_code"],),
            ).fetchone()
            assert limit and count
            blocked = count["n"] >= limit["requests_per_minute"]
            if blocked:
                status, category = "blocked", "local_rate_limit"
        conn.execute(
            """INSERT INTO blogger_api_calls(request_id,blog_id,connection_id,language_code,operation,attempt,status,http_status,error_category)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                request_id,
                blog["id"],
                connection_id,
                blog["language_code"],
                operation,
                attempt,
                status,
                http_status,
                category,
            ),
        )
        conn.execute(
            "INSERT INTO audit_events(event_type,blog_id,language_code,payload) VALUES (%s,%s,%s,%s)",
            (
                "blogger.api." + status,
                blog["id"],
                blog["language_code"],
                Jsonb(
                    {
                        "request_id": str(request_id),
                        "operation": operation,
                        "attempt": attempt,
                        "http_status": http_status,
                        "category": category,
                    }
                ),
            ),
        )
    if blocked:
        raise GoogleFailure("local_rate_limit")


def read(
    blog: dict[str, Any], connection_id: UUID, action: Callable[[BloggerReader], dict[str, Any]]
) -> dict[str, Any]:
    request_id = uuid4()
    network_attempt = 0

    def audit(
        operation: str, attempt: int, status: str, http_status: int | None, category: str | None
    ) -> None:
        nonlocal network_attempt
        if status == "requested":
            network_attempt += 1
            if network_attempt > 3:
                record(
                    request_id,
                    blog,
                    connection_id,
                    operation,
                    network_attempt,
                    "blocked",
                    None,
                    "retry_budget_exhausted",
                )
                raise GoogleFailure("retry_budget_exhausted")
        record(
            request_id,
            blog,
            connection_id,
            operation,
            network_attempt,
            status,
            http_status,
            category,
        )

    try:
        with client() as transport:
            reader = BloggerReader(transport, lambda: oauth.access_token(connection_id), audit)
            try:
                return action(reader)
            except GoogleFailure as exc:
                if exc.category != "unauthorized":
                    raise
                oauth.access_token(connection_id, force=True)
                return action(reader)
    except GoogleFailure as exc:
        if exc.category == "unauthorized":
            oauth.fail_connection(connection_id, "revoked")
        with connection() as conn:
            conn.execute(
                "UPDATE blogger_blogs SET connection_error=%s,last_checked_at=now() WHERE id=%s",
                (exc.category, blog["id"]),
            )
        raise


def connect_blog(blog_id: UUID, connection_id: UUID) -> dict[str, Any]:
    blog = blog_record(blog_id)
    if blog["oauth_connection_id"] and blog["oauth_connection_id"] != connection_id:
        raise GoogleFailure("disconnect_existing_connection_first")
    remote = read(blog, connection_id, lambda r: r.blog_by_url(blog["url"]))
    remote_id = numeric_id(str(remote.get("id", "")))
    if urlsplit(str(remote.get("url", ""))).hostname != urlsplit(blog["url"]).hostname:
        raise GoogleFailure("blog_url_mismatch")
    if blog["blog_id"] and blog["blog_id"] != remote_id:
        raise GoogleFailure("blog_id_mismatch")
    # Author-view listing proves the consenting account can read this blog, not just its public URL.
    read(blog, connection_id, lambda r: r.posts(remote_id, 1))
    with connection() as conn:
        account = conn.execute(
            "SELECT status FROM google_connections WHERE id=%s FOR UPDATE", (connection_id,)
        ).fetchone()
        current = conn.execute(
            "SELECT oauth_connection_id FROM blogger_blogs WHERE id=%s FOR UPDATE", (blog_id,)
        ).fetchone()
        if not account or account["status"] != "connected" or not current:
            raise GoogleFailure("oauth_not_connected")
        if current["oauth_connection_id"] and current["oauth_connection_id"] != connection_id:
            raise GoogleFailure("disconnect_existing_connection_first")
        conn.execute(
            """UPDATE blogger_blogs SET blog_id=%s,oauth_connection_id=%s,connection_verified_at=now(),
            connection_error=NULL,last_checked_at=now() WHERE id=%s""",
            (remote_id, connection_id, blog_id),
        )
        conn.execute(
            "INSERT INTO audit_events(event_type,blog_id,language_code,payload) VALUES ('blogger.id.verified',%s,%s,%s)",
            (
                blog_id,
                blog["language_code"],
                Jsonb({"connection_id": str(connection_id), "google_blog_id": remote_id}),
            ),
        )
    return {"verified": True, "blog_id": remote_id}


def account_blogs(connection_id: UUID) -> dict[str, Any]:
    """Account-scoped read: no fabricated language or blog association in audit."""
    return read({"id": None, "language_code": None}, connection_id, lambda r: r.account_blogs())


def account_identity(connection_id: UUID) -> dict[str, Any]:
    """Return the official Blogger profile ID; this does not expose or imply email."""
    result = read({"id": None, "language_code": None}, connection_id, lambda r: r.user())
    user_id = numeric_id(str(result.get("id", "")))
    with connection() as conn:
        conn.execute(
            "INSERT INTO audit_events(event_type,payload) VALUES ('blogger.identity.verified',%s)",
            (Jsonb({"connection_id": str(connection_id), "blogger_user_id": user_id,
                    "email_verified": False, "source": "blogger_users_get_self"}),),
        )
    return {"blogger_user_id": user_id, "email_verified": False}


COMMON_CONNECTION_APPROVAL = "I_APPROVE_SHARED_BLOGGER_CONNECTION"
COMMON_CONNECTION_VERIFICATION_TTL = timedelta(minutes=5)


def _common_connection_gate() -> None:
    provider = next(
        item
        for item in external_policy.status()["providers"]
        if item["name"] == "google_blogger_read"
    )
    if not provider["calls_allowed"]:
        raise GoogleFailure(str(provider["block_reason"] or "provider_cost_unverified"))


def verify_common_connection(connection_id: UUID) -> dict[str, Any]:
    """Read-only proof that one full-scope OAuth connection lists every active blog."""
    _common_connection_gate()
    with connection() as conn:
        account = conn.execute(
            """SELECT id,status,scopes,refresh_ciphertext FROM google_connections
            WHERE id=%s""",
            (connection_id,),
        ).fetchone()
        if (
            account is None
            or account["status"] != "connected"
            or account["scopes"] != [WRITE_SCOPE]
            or not account["refresh_ciphertext"]
        ):
            raise GoogleFailure("connected_write_oauth_required")
        blogs = conn.execute(
            """SELECT b.id,b.language_code,b.url,b.blog_id,b.oauth_connection_id
            FROM blogger_blogs b JOIN languages l ON l.code=b.language_code
            WHERE b.active AND l.active ORDER BY b.language_code,b.url"""
        ).fetchall()
    if not blogs:
        raise GoogleFailure("active_blogs_not_configured")
    identity = account_identity(connection_id)
    result = account_blogs(connection_id)
    items = result.get("items")
    if not isinstance(items, list):
        raise GoogleFailure("account_blog_list_invalid")
    accessible: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            remote_id = numeric_id(str(item.get("id", "")))
        except GoogleFailure:
            continue
        accessible[remote_id] = item

    verified: list[dict[str, str | None]] = []
    for blog in blogs:
        item = accessible.get(str(blog["blog_id"])) if blog["blog_id"] else None
        if item is None and not blog["blog_id"]:
            host = (urlsplit(blog["url"]).hostname or "").casefold()
            matches = [
                entry
                for entry in accessible.values()
                if (urlsplit(str(entry.get("url", ""))).hostname or "").casefold() == host
            ]
            if len(matches) == 1:
                item = matches[0]
        if item is None:
            raise GoogleFailure("oauth_connection_cannot_access_all_blogs")
        remote_id = numeric_id(str(item.get("id", "")))
        remote_host = urlsplit(str(item.get("url", ""))).hostname
        registered_host = urlsplit(blog["url"]).hostname
        if not remote_host or remote_host.casefold() != (registered_host or "").casefold():
            raise GoogleFailure("blog_url_mismatch")
        verified.append(
            {
                "blog_record_id": str(blog["id"]),
                "language_code": blog["language_code"],
                "url": blog["url"],
                "blog_id": remote_id,
                "registered_blog_id": str(blog["blog_id"]) if blog["blog_id"] else None,
                "previous_connection_id": (
                    str(blog["oauth_connection_id"]) if blog["oauth_connection_id"] else None
                ),
            }
        )

    verification_id = uuid4()
    with connection() as conn:
        conn.execute(
            """INSERT INTO audit_events(event_type,payload) VALUES
            ('blogger.common_connection.verified',%s)""",
            (
                Jsonb(
                    {
                        "verification_id": str(verification_id),
                        "connection_id": str(connection_id),
                        "blogger_user_id": identity["blogger_user_id"],
                        "email_verified": False,
                        "verified_blog_count": len(verified),
                        "blogs": verified,
                        "identity_verified": False,
                        "writes_enabled": False,
                    }
                ),
            ),
        )
    return {
        "verification_id": str(verification_id),
        "connection_id": str(connection_id),
        "blogger_user_id": identity["blogger_user_id"],
        "email_verified": False,
        "verified_blog_count": len(verified),
        "blogs": verified,
        "identity_verified": False,
        "writes_enabled": False,
    }


def assign_common_connection(
    connection_id: UUID, verification_id: UUID, approval: str
) -> dict[str, Any]:
    """Atomically map all active blogs only after fresh read proof and explicit approval."""
    if approval != COMMON_CONNECTION_APPROVAL:
        raise GoogleFailure("explicit_common_connection_approval_required")
    _common_connection_gate()
    with connection() as conn:
        account = conn.execute(
            """SELECT id,status,scopes,refresh_ciphertext FROM google_connections
            WHERE id=%s FOR UPDATE""",
            (connection_id,),
        ).fetchone()
        if (
            account is None
            or account["status"] != "connected"
            or account["scopes"] != [WRITE_SCOPE]
            or not account["refresh_ciphertext"]
        ):
            raise GoogleFailure("connected_write_oauth_required")
        event = conn.execute(
            """SELECT payload,created_at FROM audit_events
            WHERE event_type='blogger.common_connection.verified'
            AND payload->>'verification_id'=%s
            AND payload->>'connection_id'=%s
            ORDER BY id DESC LIMIT 1""",
            (str(verification_id), str(connection_id)),
        ).fetchone()
        if event is None or datetime.now(UTC) - event["created_at"] > COMMON_CONNECTION_VERIFICATION_TTL:
            raise GoogleFailure("common_connection_verification_expired")
        snapshot = event["payload"].get("blogs")
        if not isinstance(snapshot, list) or not snapshot:
            raise GoogleFailure("common_connection_verification_invalid")
        current = conn.execute(
            """SELECT b.id,b.language_code,b.url,b.blog_id,b.oauth_connection_id
            FROM blogger_blogs b JOIN languages l ON l.code=b.language_code
            WHERE b.active AND l.active ORDER BY b.language_code,b.url FOR UPDATE OF b"""
        ).fetchall()
        current_snapshot = [
            {
                "blog_record_id": str(blog["id"]),
                "language_code": blog["language_code"],
                "url": blog["url"],
                "blog_id": str(blog["blog_id"]) if blog["blog_id"] else None,
                "registered_blog_id": str(blog["blog_id"]) if blog["blog_id"] else None,
                "previous_connection_id": (
                    str(blog["oauth_connection_id"]) if blog["oauth_connection_id"] else None
                ),
            }
            for blog in current
        ]
        expected_current_snapshot = [
            {
                **entry,
                "blog_id": entry.get("registered_blog_id"),
            }
            for entry in snapshot
        ]
        if current_snapshot != expected_current_snapshot:
            raise GoogleFailure("blog_mapping_changed_after_verification")
        verified_ids = {
            entry["blog_record_id"]: entry["blog_id"] for entry in snapshot
        }
        for blog in current:
            conn.execute(
                """UPDATE blogger_blogs SET blog_id=%s,oauth_connection_id=%s,
                connection_verified_at=now(),last_checked_at=now(),connection_error=NULL,
                test_publish_verified_at=NULL WHERE id=%s""",
                (verified_ids[str(blog["id"])], connection_id, blog["id"]),
            )
        conn.execute(
            """INSERT INTO audit_events(event_type,payload) VALUES
            ('blogger.common_connection.assigned',%s)""",
            (
                Jsonb(
                    {
                        "connection_id": str(connection_id),
                        "verification_id": str(verification_id),
                        "blogger_user_id": event["payload"].get("blogger_user_id"),
                        "email_verified": False,
                        "blogs": snapshot,
                        "approval": "explicit_admin_confirmation",
                        "selection_reason": "operator_preferred_duplicate_blogger_identity",
                        "writes_enabled": False,
                    }
                ),
            ),
        )
    return {
        "assigned": True,
        "connection_id": str(connection_id),
        "blogger_user_id": event["payload"].get("blogger_user_id"),
        "blog_count": len(snapshot),
        "writes_enabled": False,
        "publish_ready": False,
    }


def disconnect_blog(blog_id: UUID) -> dict[str, bool]:
    with connection() as conn:
        row = conn.execute(
            """UPDATE blogger_blogs SET oauth_connection_id=NULL,connection_verified_at=NULL,
            test_publish_verified_at=NULL,connection_error=NULL WHERE id=%s RETURNING id""",
            (blog_id,),
        ).fetchone()
        if row is None:
            raise GoogleFailure("blog_not_found")
        conn.execute(
            "INSERT INTO audit_events(event_type,blog_id,payload) VALUES ('blogger.disconnected',%s,'{}')",
            (blog_id,),
        )
    return {"disconnected": True}


def connected(blog_id: UUID) -> dict[str, Any]:
    blog = blog_record(blog_id)
    if (
        not blog["oauth_connection_id"]
        or not blog["connection_verified_at"]
        or blog["oauth_status"] != "connected"
    ):
        raise GoogleFailure("blog_not_connected")
    return blog


def posts(blog_id: UUID, page_token: str = "", status: str = "live") -> dict[str, Any]:
    blog = connected(blog_id)
    result = read(
        blog,
        blog["oauth_connection_id"],
        lambda r: r.posts(blog["blog_id"], blog["max_page_size"], page_token, status),
    )
    result.setdefault("items", [])
    with connection() as conn:
        conn.execute(
            "UPDATE blogger_blogs SET last_checked_at=now(),connection_error=NULL WHERE id=%s",
            (blog_id,),
        )
    return result


def post(blog_id: UUID, post_id: str) -> dict[str, Any]:
    blog = connected(blog_id)
    return read(blog, blog["oauth_connection_id"], lambda r: r.post(blog["blog_id"], post_id))


def test_connection(blog_id: UUID) -> dict[str, Any]:
    blog = connected(blog_id)
    remote = read(blog, blog["oauth_connection_id"], lambda r: r.blog(blog["blog_id"]))
    with connection() as conn:
        conn.execute(
            "UPDATE blogger_blogs SET last_checked_at=now(),connection_error=NULL WHERE id=%s",
            (blog_id,),
        )
    return {
        "blog_id": remote.get("id"),
        "name": remote.get("name"),
        "posts": remote.get("posts"),
        "tested": True,
    }
