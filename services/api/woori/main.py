import logging
import secrets
from typing import Annotated, Any

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from .ai import EngineFailure
from .blogger_routes import router as blogger_router
from .config import settings
from .content_imports import router as content_imports_router
from .db import connection
from .google_http import GoogleFailure
from .localized_publications import router as localized_publications_router
from .multilingual import router
from .operations import health as operations_health
from .operations_dashboard import dashboard_snapshot
from .publications import router as publications_router
from .research_routes import router as research_router

app = FastAPI(title="Woori Blog Agent", docs_url=None, redoc_url=None, openapi_url=None)
logger = logging.getLogger("woori.api.database")
bearer = HTTPBearer(auto_error=False)


def authorize(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> None:
    if credentials is None or not secrets.compare_digest(
        credentials.credentials, settings().admin_token
    ):
        raise HTTPException(401, "Unauthorized")


app.include_router(research_router, dependencies=[Depends(authorize)])
app.include_router(localized_publications_router, dependencies=[Depends(authorize)])
app.include_router(content_imports_router, dependencies=[Depends(authorize)])
app.include_router(router, dependencies=[Depends(authorize)])
app.include_router(blogger_router, dependencies=[Depends(authorize)])
app.include_router(publications_router, dependencies=[Depends(authorize)])


@app.exception_handler(EngineFailure)
async def engine_error(request: Request, exc: EngineFailure) -> JSONResponse:
    return JSONResponse({"error": exc.category}, status_code=409)


@app.exception_handler(GoogleFailure)
async def google_error(request: Request, exc: GoogleFailure) -> JSONResponse:
    status = 429 if exc.category in ("local_rate_limit", "rate_limit") else 409
    if exc.category.endswith("not_found"):
        status = 404
    return JSONResponse({"error": exc.category}, status_code=status)


@app.exception_handler(psycopg.Error)
async def database_error(request: Request, exc: psycopg.Error) -> JSONResponse:
    diag = exc.diag
    request_id = secrets.token_hex(12)
    known_rule_messages = {
        "post_publication_review_requires_verified_live_record": "verified_live_review_guard",
        "prepublication_review_requires_bound_job": "review_job_binding_guard",
        "prepublication_review_requires_active_scheduled_job": "scheduled_review_policy_guard",
        "prepublication_review_requires_manual_user_confirmation": "manual_confirmation_guard",
        "prepublication_review_requires_active_publication_job": "active_job_guard",
        "Localization does not match language/country policy": "publication_locale_guard",
    }
    primary = getattr(diag, "message_primary", None) or ""
    safe_rule_code = known_rule_messages.get(primary, "database_rule_rejected")
    if exc.sqlstate == "42P10":
        safe_rule_code = "db_conflict_target_missing"
    elif exc.sqlstate == "23514":
        safe_rule_code = "database_constraint_violation"
    elif exc.sqlstate != "P0001":
        safe_rule_code = "database_operation_failed"
    source_function = getattr(diag, "source_function", None) or "unknown"
    logger.error(
        "Database request failed: request_id=%s path=%s method=%s sqlstate=%s error_code=%s db_function=%s schema=%s table=%s column=%s constraint=%s",
        request_id,
        request.url.path,
        request.method,
        exc.sqlstate or "unknown",
        safe_rule_code,
        source_function,
        getattr(diag, "schema_name", None) or "unknown",
        getattr(diag, "table_name", None) or "unknown",
        getattr(diag, "column_name", None) or "unknown",
        getattr(diag, "constraint_name", None) or "unknown",
    )
    return JSONResponse(
        {"error": "Database operation unavailable", "code": safe_rule_code,
         "request_id": request_id}, status_code=503,
    )


class RunRequest(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/admin/summary", dependencies=[Depends(authorize)])
def summary() -> dict[str, Any]:
    try:
        with connection() as conn:
            runs = conn.execute(
                "SELECT * FROM job_runs ORDER BY created_at DESC LIMIT 50"
            ).fetchall()
            events = conn.execute("SELECT * FROM audit_events ORDER BY id DESC LIMIT 50").fetchall()
            languages = conn.execute(
                "SELECT code,display_name,active FROM languages ORDER BY code"
            ).fetchall()
            return {
                "runs": runs,
                "events": events,
                "languages": [row["code"] for row in languages],
                "language_details": languages,
                "blogs": conn.execute(
                    "SELECT * FROM blogger_blogs ORDER BY language_code,url"
                ).fetchall(),
                "publishing_enabled": False,
                "paid_ai_enabled": False,
                "operations": operations_health(),
            }
    except psycopg.Error:
        raise HTTPException(503, "Database unavailable") from None


@app.get("/admin/operations/dashboard", dependencies=[Depends(authorize)])
def operations_dashboard() -> dict[str, Any]:
    """Compact read-only status for the operator home screen."""
    try:
        with connection() as conn:
            return dashboard_snapshot(conn)
    except psycopg.Error:
        raise HTTPException(503, "운영 현황을 조회할 수 없습니다.") from None


@app.post("/admin/runs", dependencies=[Depends(authorize)], status_code=201)
def create_run(request: RunRequest) -> dict[str, Any]:
    try:
        with connection() as conn:
            row = conn.execute(
                """INSERT INTO job_runs(idempotency_key) VALUES (%s)
                ON CONFLICT (idempotency_key) DO NOTHING RETURNING *""",
                (request.idempotency_key,),
            ).fetchone()
            if row is None:
                row = conn.execute(
                    "SELECT * FROM job_runs WHERE idempotency_key=%s", (request.idempotency_key,)
                ).fetchone()
            else:
                conn.execute(
                    "INSERT INTO audit_events(run_id,event_type) VALUES (%s,'run.queued')",
                    (row["id"],),
                )
            assert row is not None
            return row
    except psycopg.Error:
        raise HTTPException(503, "Database unavailable") from None
