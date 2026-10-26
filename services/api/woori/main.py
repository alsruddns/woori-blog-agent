import secrets
from typing import Annotated, Any

import psycopg
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from .config import settings
from .db import connection
from .multilingual import router

app = FastAPI(title="Woori Blog Agent", docs_url=None, redoc_url=None, openapi_url=None)
bearer = HTTPBearer(auto_error=False)


def authorize(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> None:
    if credentials is None or not secrets.compare_digest(
        credentials.credentials, settings().admin_token
    ):
        raise HTTPException(401, "Unauthorized")


app.include_router(router, dependencies=[Depends(authorize)])


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
            }
    except psycopg.Error:
        raise HTTPException(503, "Database unavailable") from None


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
