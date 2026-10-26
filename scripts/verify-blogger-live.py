"""Explicit live readonly verification; requires user-completed Google consent."""

from woori import blogger_service as blogger
from woori import google_oauth as oauth
from woori.db import connection

if not oauth.configured():
    print("LIVE READ NOT RUN: Google OAuth client is not configured.")
    raise SystemExit(2)
with connection() as conn:
    account = conn.execute(
        "SELECT id FROM google_connections WHERE status='connected' ORDER BY updated_at DESC LIMIT 1"
    ).fetchone()
    blogs = conn.execute(
        "SELECT id FROM blogger_blogs WHERE active ORDER BY language_code"
    ).fetchall()
if not account:
    print("LIVE READ NOT RUN: user Google consent has not completed.")
    raise SystemExit(2)
for blog in blogs:
    blogger.connect_blog(blog["id"], account["id"])
    blogger.test_connection(blog["id"])
    posts = blogger.posts(blog["id"])
    print(
        "Live readonly verification passed for configured internal blog",
        blog["id"],
        "returned posts",
        len(posts.get("items", [])),
    )
