from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from psycopg.types.json import Jsonb
from pydantic import Field

from . import blogger_service as blogger
from . import google_oauth as oauth
from .db import connection
from .google_http import GoogleFailure
from .multilingual import Input
from .operations import health as operations_health

router = APIRouter(prefix="/admin/blogger")


class Start(Input):
    binding: str = Field(min_length=32, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")
    label: str = Field(default="Google Blogger", min_length=1, max_length=100)


class Callback(Start):
    state: str = Field(min_length=20, max_length=200)
    code: str = Field(default="", max_length=4096)
    denied: bool = False


class Connect(Input):
    connection_id: UUID


class Limits(Input):
    read_enabled: bool
    requests_per_minute: int = Field(ge=1, le=60)
    max_page_size: int = Field(ge=1, le=100)
    publishing_enabled: Literal[False] = False


@router.get("/status")
def status() -> dict[str, Any]:
    with connection() as conn:
        return {
            "configured": oauth.configured(),
            "operations": operations_health(),
            "writes_enabled": False,
            "connections": conn.execute(
                "SELECT id,label,status,scopes,expires_at,error_category,updated_at FROM google_connections ORDER BY created_at DESC"
            ).fetchall(),
            "blogs": conn.execute("""SELECT b.*,l.active AS language_active,g.status AS oauth_status
                    FROM blogger_blogs b JOIN languages l ON l.code=b.language_code
                    LEFT JOIN google_connections g ON g.id=b.oauth_connection_id ORDER BY b.language_code,b.url""").fetchall(),
            "limits": conn.execute(
                "SELECT * FROM language_execution_limits ORDER BY language_code"
            ).fetchall(),
            "calls": conn.execute(
                "SELECT * FROM blogger_api_calls ORDER BY id DESC LIMIT 50"
            ).fetchall(),
            "events": conn.execute(
                "SELECT id,event_type,blog_id,payload,created_at FROM audit_events WHERE event_type LIKE 'oauth.%' OR event_type LIKE 'blogger.%' ORDER BY id DESC LIMIT 50"
            ).fetchall(),
        }


@router.post("/oauth/start")
def start(request: Start) -> dict[str, str]:
    return oauth.start(request.binding, request.label)


@router.post("/oauth/callback")
def callback(request: Callback) -> dict[str, str]:
    return {
        "connection_id": str(
            oauth.callback(request.state, request.binding, request.code, request.denied)
        )
    }


@router.post("/oauth/{connection_id}/disconnect")
def disconnect(connection_id: UUID) -> dict[str, bool]:
    return oauth.disconnect(connection_id)


@router.post("/blogs/{blog_id}/connect")
def connect(blog_id: UUID, request: Connect) -> dict[str, Any]:
    return blogger.connect_blog(blog_id, request.connection_id)


@router.post("/blogs/{blog_id}/disconnect")
def disconnect_blog(blog_id: UUID) -> dict[str, bool]:
    return blogger.disconnect_blog(blog_id)


@router.post("/blogs/{blog_id}/test")
def test(blog_id: UUID) -> dict[str, Any]:
    return blogger.test_connection(blog_id)


@router.get("/blogs/{blog_id}/posts")
def posts(
    blog_id: UUID,
    page_token: str = Query(default="", max_length=2048),
    status: Literal["live", "draft", "scheduled"] = "live",
) -> dict[str, Any]:
    return blogger.posts(blog_id, page_token, status)


@router.get("/blogs/{blog_id}/posts/{post_id}")
def post(blog_id: UUID, post_id: str) -> dict[str, Any]:
    return blogger.post(blog_id, post_id)


@router.put("/limits/{code}")
def update_limits(code: str, request: Limits) -> dict[str, Any]:
    with connection() as conn:
        row = conn.execute(
            "UPDATE language_execution_limits SET read_enabled=%s,requests_per_minute=%s,max_page_size=%s WHERE language_code=%s RETURNING *",
            (request.read_enabled, request.requests_per_minute, request.max_page_size, code),
        ).fetchone()
        if row is None:
            raise GoogleFailure("language_not_found")
        return row


class Content(Input):
    language_code: str = Field(min_length=1, max_length=100)
    target_country: str = Field(default="", pattern=r"^([A-Z]{2}|[0-9]{3})?$")
    group_id: UUID | None = None
    source_version_id: UUID | None = None
    title: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=50000)
    category_ids: list[UUID] = Field(default_factory=list, max_length=20)


@router.get("/content")
def content(language_code: str = Query(default="", max_length=100)) -> dict[str, Any]:
    with connection() as conn:
        rows = conn.execute(
            """SELECT v.*,l.target_country FROM content_versions v
            JOIN content_localizations l ON l.id=v.localization_id
            WHERE (%s='' OR v.language=%s) ORDER BY v.created_at DESC LIMIT 100""",
            (language_code, language_code),
        ).fetchall()
        return {
            "versions": rows,
            "categories": conn.execute("SELECT * FROM categories ORDER BY slug").fetchall(),
        }


@router.post("/content", status_code=201)
def version(request: Content) -> dict[str, Any]:
    with connection() as conn:
        profile = conn.execute(
            """SELECT p.id FROM language_profiles p JOIN languages l ON l.code=p.language_code
            WHERE p.language_code=%s AND p.target_country=%s AND l.active""",
            (request.language_code, request.target_country),
        ).fetchone()
        if profile is None:
            raise GoogleFailure("active_language_profile_required")
        group_id = request.group_id
        if request.source_version_id:
            source = conn.execute(
                "SELECT group_id FROM content_versions WHERE id=%s", (request.source_version_id,)
            ).fetchone()
            if source is None or (group_id and source["group_id"] != group_id):
                raise GoogleFailure("source_group_mismatch")
            group_id = source["group_id"]
        if not group_id:
            row = conn.execute("INSERT INTO content_groups DEFAULT VALUES RETURNING id").fetchone()
            assert row is not None
            group_id = row["id"]
        conn.execute(
            "INSERT INTO content_localizations(group_id,language_code,target_country) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
            (group_id, request.language_code, request.target_country),
        )
        localization = conn.execute(
            "SELECT id FROM content_localizations WHERE group_id=%s AND language_code=%s AND target_country=%s",
            (group_id, request.language_code, request.target_country),
        ).fetchone()
        assert localization is not None
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (str(localization["id"]),)
        )
        row = conn.execute(
            """INSERT INTO content_versions(localization_id,group_id,language,version,title,body,source_version_id)
            SELECT %s,%s,%s,COALESCE(max(version),0)+1,%s,%s,%s FROM content_versions WHERE localization_id=%s RETURNING *""",
            (
                localization["id"],
                group_id,
                request.language_code,
                request.title,
                request.body,
                request.source_version_id,
                localization["id"],
            ),
        ).fetchone()
        for category_id in request.category_ids:
            conn.execute(
                "INSERT INTO localization_categories(localization_id,category_id) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                (localization["id"], category_id),
            )
        assert row is not None
        conn.execute(
            "INSERT INTO audit_events(event_type,language_code,payload) VALUES ('content.version.created',%s,%s)",
            (
                request.language_code,
                Jsonb(
                    {
                        "version_id": str(row["id"]),
                        "group_id": str(group_id),
                        "localization_id": str(localization["id"]),
                        "version": row["version"],
                    }
                ),
            ),
        )
        return row
