"""Explicit live readonly verification; requires user-completed Google consent."""

import json
import sys
from datetime import UTC, datetime
from urllib.parse import urlsplit

from psycopg.types.json import Jsonb
from woori import blogger_service as blogger
from woori import google_oauth as oauth
from woori.db import connection
from woori.external_policy import ExternalCallBlocked
from woori.google_http import READ_SCOPE, GoogleFailure

sys.stdout.reconfigure(encoding="utf-8")

if not oauth.configured():
    print("LIVE READ NOT RUN: Google OAuth client is not configured.")
    raise SystemExit(2)
with connection() as conn:
    account = conn.execute(
        "SELECT id,scopes FROM google_connections WHERE status='connected' ORDER BY updated_at DESC LIMIT 1"
    ).fetchone()
    blogs = conn.execute(
        """SELECT b.id FROM blogger_blogs b JOIN languages l ON l.code=b.language_code
        WHERE b.active AND l.active ORDER BY b.language_code,b.url"""
    ).fetchall()
if not account or account["scopes"] != [READ_SCOPE]:
    print("LIVE READ NOT RUN: user Google consent has not completed.")
    raise SystemExit(2)
try:
    accessible = blogger.account_blogs(account["id"]).get("items", [])
except ExternalCallBlocked:
    print(json.dumps({"account_error": "external_provider_blocked_by_zero_cost_policy", "http_requests_sent": 0}))
    raise SystemExit(2) from None
except GoogleFailure as exc:
    print(json.dumps({"account_error": exc.category, "http_status": exc.status}))
    raise SystemExit(1) from None
print(
    json.dumps(
        {"accessible_blogs": [{k: b.get(k) for k in ("id", "name", "url")} for b in accessible]},
        ensure_ascii=False,
    )
)
failed = False
for blog in blogs:
    result = {"internal_id": str(blog["id"])}
    with connection() as conn:
        conn.execute(
            "INSERT INTO audit_events(event_type,blog_id,payload) VALUES ('blogger.verification.started',%s,%s)",
            (blog["id"], Jsonb({"work_id": "P2-003", "mode": "readonly"})),
        )
    try:
        remote = blogger.connect_blog(blog["id"], account["id"])
        detail = blogger.test_connection(blog["id"])
        count, pages, token, seen = 0, 0, "", set()
        while True:
            posts = blogger.posts(blog["id"], token)
            pages += 1
            count += len(posts.get("items", []))
            token = posts.get("nextPageToken", "")
            if not token:
                break
            if token in seen or pages >= 100:
                raise GoogleFailure("pagination_limit_or_cycle")
            seen.add(token)
        with connection() as conn:
            row = conn.execute(
                "SELECT language_code,url,last_checked_at FROM blogger_blogs WHERE id=%s",
                (blog["id"],),
            ).fetchone()
        match = [b for b in accessible if b.get("id") == remote["blog_id"]]
        if not match or urlsplit(match[0].get("url", "")).hostname != urlsplit(row["url"]).hostname:
            raise GoogleFailure("account_blog_mismatch")
        result.update(
            language=row["language_code"],
            url=row["url"],
            blog_id=remote["blog_id"],
            title=detail["name"],
            posts=count,
            pages=pages,
            terminal_page=True,
            account_access=True,
            last_checked_at=row["last_checked_at"].isoformat(),
            error=None,
        )
    except GoogleFailure as exc:
        failed = True
        result.update(error=exc.category, http_status=exc.status)
    with connection() as conn:
        conn.execute(
            "INSERT INTO audit_events(event_type,blog_id,payload) VALUES (%s,%s,%s)",
            (
                "blogger.verification.failed"
                if result["error"]
                else "blogger.verification.completed",
                blog["id"],
                Jsonb(result),
            ),
        )
    print(json.dumps(result, ensure_ascii=False))
print("Verified at", datetime.now(UTC).isoformat())
raise SystemExit(int(failed))
