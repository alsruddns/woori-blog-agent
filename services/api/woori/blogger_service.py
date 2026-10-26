"""Database-selected Blogger reads with per-language quotas and durable request history."""

from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from . import google_oauth as oauth
from .db import connection
from .google_http import BloggerReader, GoogleFailure, client, numeric_id


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
