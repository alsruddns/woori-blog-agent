"""Fail-closed publication requests and explicitly offline mock simulations."""

from __future__ import annotations

from typing import Any, Literal, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from .db import connection

router = APIRouter(prefix="/admin/publications")

PublicationState = Literal[
    "draft",
    "quality_held",
    "machine_checked",
    "human_review_pending",
    "human_review_rejected",
    "human_review_approved",
    "publication_blocked",
    "publication_queued",
    "publishing",
    "published",
    "publication_failed",
    "cancelled",
]


class RequestInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    content_version_id: UUID
    blog_id: UUID
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class SimulationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    scenario: Literal["success", "timeout", "auth_failure", "server_failure", "uncertain"]


class PublicationError(Exception):
    def __init__(self, category: str) -> None:
        self.category = category
        super().__init__(category)


class FakeBloggerPublisher:
    """Network-free adapter. Its fake identifiers can never be Blogger IDs."""

    def publish(self, scenario: str) -> dict[str, Any]:
        outcomes = {
            "success": "succeeded",
            "timeout": "failed",
            "auth_failure": "failed",
            "server_failure": "failed",
            "uncertain": "uncertain",
        }
        if scenario not in outcomes:
            raise PublicationError("invalid_mock_scenario")
        return {
            "adapter_type": "fake",
            "simulation_only": True,
            "outcome": outcomes[scenario],
            "scenario": scenario,
            "fake_post_id": f"fake-post-{uuid4()}" if scenario == "success" else None,
            "external_network_calls": 0,
            "real_blog_mutated": False,
        }


class DisabledRealBloggerPublisher:
    """Permanent fail-closed placeholder; deliberately exposes no HTTP client."""

    def publish(self, *_: Any, **__: Any) -> None:
        raise PublicationError("production_writes_disabled")


def transitions_allowed() -> dict[str, tuple[str, ...]]:
    return {
        "draft": ("quality_held", "machine_checked", "publication_blocked"),
        "quality_held": ("machine_checked", "publication_blocked"),
        "machine_checked": ("human_review_pending", "publication_blocked"),
        "human_review_pending": ("human_review_approved", "human_review_rejected"),
        "human_review_rejected": ("human_review_pending", "publication_blocked"),
        "human_review_approved": ("publication_queued", "publication_blocked"),
        "publication_blocked": ("human_review_pending", "cancelled"),
        "publication_queued": ("publishing", "cancelled", "publication_blocked"),
        "publishing": ("published", "publication_failed", "publication_blocked"),
        "publication_failed": ("publication_queued", "publication_blocked", "cancelled"),
        "published": (),
        "cancelled": (),
    }


def transition_allowed(current: str, target: str) -> bool:
    return target in transitions_allowed().get(current, ())


def _assess(row: dict[str, Any] | None) -> dict[str, Any]:
    if row is None:
        return {"state": "draft", "reasons": ["content_or_blog_not_found"]}
    reasons: list[str] = []
    if not row["language_active"]:
        reasons.append("language_inactive")
    if not row["blog_active"]:
        reasons.append("blog_inactive")
    if row["version_language"] != row["blog_language"]:
        reasons.append("blog_language_mismatch")
    if not row["blog_id_value"] or not row["connection_verified_at"]:
        reasons.append("blog_connection_unverified")
    if row["oauth_status"] != "connected":
        reasons.append("oauth_connection_unavailable")
    if row["test_publish_verified_at"] is None:
        reasons.append("test_publish_not_verified")
    if not row["policy_id"]:
        reasons.append("publication_policy_missing")
    elif not row["policy_active"]:
        reasons.append("publication_policy_inactive")
    if row["auto_publish_allowed"]:
        reasons.append("unexpected_auto_publish_enabled")
    if not row["machine_passed"]:
        reasons.append("machine_quality_not_passed")
    if row["human_review_required"] or not row["human_review_approved"]:
        reasons.append("human_review_pending")
    if row["publish_ready"]:
        # Phase policy and schema deliberately prohibit this state today.
        reasons.append("unexpected_publish_ready_state")
    else:
        reasons.append("publish_ready_disabled")
    reasons.append("production_writes_disabled")
    if "machine_quality_not_passed" in reasons:
        state = "quality_held"
    elif "human_review_pending" in reasons:
        state = "human_review_pending"
    else:
        state = "publication_blocked"
    return {"state": state, "reasons": reasons}


def _candidate(conn: Any, version_id: UUID, blog_id: UUID) -> dict[str, Any] | None:
    return cast(
        dict[str, Any] | None,
        conn.execute(
            """SELECT v.id AS content_version_id,v.title,v.body,v.localization_id,
            l.language_code AS version_language,l.target_country,b.id AS blog_uuid,
            b.language_code AS blog_language,b.url,b.active AS blog_active,
            b.blog_id AS blog_id_value,b.connection_verified_at,b.test_publish_verified_at,
            lang.active AS language_active,g.status AS oauth_status,
            p.id AS policy_id,p.active AS policy_active,p.auto_publish_allowed,
            COALESCE(q.machine_passed,false) AS machine_passed,
            COALESCE(q.human_review_required,true) AS human_review_required,
            false AS human_review_approved,COALESCE(q.publish_ready,false) AS publish_ready,
            q.id AS quality_evaluation_id,q.status AS quality_status
        FROM content_versions v
        JOIN content_localizations l ON l.id=v.localization_id
        JOIN blogger_blogs b ON b.id=%s
        LEFT JOIN google_connections g ON g.id=b.oauth_connection_id
        JOIN languages lang ON lang.code=l.language_code
        LEFT JOIN language_profiles lp ON lp.language_code=l.language_code
          AND lp.target_country=l.target_country
        LEFT JOIN publishing_policies p ON p.blog_id=b.id AND p.profile_id=lp.id
        LEFT JOIN LATERAL (
          SELECT id,machine_passed,human_review_required,publish_ready,status
          FROM article_quality_evaluations WHERE content_version_id=v.id
          ORDER BY created_at DESC,id DESC LIMIT 1
        ) q ON true
        WHERE v.id=%s""",
            (blog_id, version_id),
        ).fetchone(),
    )


@router.get("")
def list_publications() -> dict[str, Any]:
    with connection() as conn:
        candidates = conn.execute(
            """SELECT v.id AS content_version_id,v.title,l.language_code,
                l.target_country,b.id AS blog_id,b.url,b.blog_id AS blogger_blog_id,
                v.created_at AS version_created_at,
                COALESCE(q.machine_passed,false) AS machine_passed,
                COALESCE(q.human_review_required,true) AS human_review_required,
                COALESCE(q.publish_ready,false) AS publish_ready,q.status AS quality_status,
                q.created_at AS evaluated_at
            FROM content_versions v JOIN content_localizations l ON l.id=v.localization_id
            JOIN blogger_blogs b ON b.language_code=l.language_code AND b.active
            LEFT JOIN LATERAL (SELECT machine_passed,human_review_required,publish_ready,status,created_at
                FROM article_quality_evaluations WHERE content_version_id=v.id
                ORDER BY created_at DESC,id DESC LIMIT 1) q ON true
            ORDER BY v.created_at DESC LIMIT 100"""
        ).fetchall()
        jobs = conn.execute(
            """SELECT j.id,j.content_version_id,j.blog_id,b.language_code,b.url,
                j.status,j.publication_state,j.scheduled_at,j.block_reasons,j.updated_at,
                (SELECT count(*) FROM publication_attempts a WHERE a.job_id=j.id) AS simulation_count
            FROM publishing_jobs j JOIN blogger_blogs b ON b.id=j.blog_id
            ORDER BY j.scheduled_at DESC,j.id DESC LIMIT 100"""
        ).fetchall()
        attempts = conn.execute(
            "SELECT id,job_id,scenario,outcome,fake_post_id,result,created_at FROM publication_attempts ORDER BY created_at DESC LIMIT 50"
        ).fetchall()
        return {
            "candidates": [dict(row) for row in candidates],
            "jobs": [dict(row) for row in jobs],
            "simulations": [dict(row) for row in attempts],
            "real_writes_enabled": False,
            "publish_ready_enabled": False,
            "adapter_available": "fake_only",
        }


@router.post("/requests", status_code=201)
def create_request(request: RequestInput) -> dict[str, Any]:
    with connection() as conn:
        row = _candidate(conn, request.content_version_id, request.blog_id)
        if row is None:
            raise HTTPException(404, "Content version or registered blog not found")
        assessed = _assess(dict(row))
        if row["policy_id"] is None:
            conn.execute(
                "INSERT INTO audit_events(event_type,blog_id,payload) VALUES ('publication.request.blocked',%s,%s)",
                (
                    request.blog_id,
                    Jsonb(
                        {
                            "content_version_id": str(request.content_version_id),
                            "reasons": assessed["reasons"],
                        }
                    ),
                ),
            )
            return {
                "recorded": False,
                "state": assessed["state"],
                "reasons": assessed["reasons"],
                "real_writes_enabled": False,
            }
        inserted = conn.execute(
            """INSERT INTO publishing_jobs(policy_id,blog_id,content_version_id,idempotency_key,
                scheduled_at,status,publication_state,adapter_type,simulation_only,block_reasons)
            VALUES (%s,%s,%s,%s,now(),'blocked',%s,'fake',true,%s)
            ON CONFLICT(idempotency_key) DO NOTHING RETURNING id,status,publication_state,block_reasons""",
            (
                row["policy_id"],
                request.blog_id,
                request.content_version_id,
                request.idempotency_key,
                assessed["state"],
                Jsonb(assessed["reasons"]),
            ),
        ).fetchone()
        if inserted is None:
            existing = conn.execute(
                "SELECT id,blog_id,content_version_id,status,publication_state,block_reasons FROM publishing_jobs WHERE idempotency_key=%s",
                (request.idempotency_key,),
            ).fetchone()
            if (
                existing is None
                or str(existing["blog_id"]) != str(request.blog_id)
                or str(existing["content_version_id"]) != str(request.content_version_id)
            ):
                raise HTTPException(409, "Idempotency key conflict")
            conn.execute(
                "INSERT INTO audit_events(event_type,payload) VALUES ('publication.request.duplicate_blocked',%s)",
                (Jsonb({"job_id": str(existing["id"]), "simulation_only": True}),),
            )
            return {**dict(existing), "duplicate": True, "real_writes_enabled": False}
        event = conn.execute(
            """INSERT INTO publication_state_events(job_id,from_state,to_state,reason,details)
                VALUES (%s,NULL,%s,'eligibility_gate_failed',%s) RETURNING id""",
            (
                inserted["id"],
                assessed["state"],
                Jsonb(
                    {
                        "reasons": assessed["reasons"],
                        "machine_passed": row["machine_passed"],
                        "human_review_required": row["human_review_required"],
                        "simulation_only": True,
                    }
                ),
            ),
        ).fetchone()
        assert event is not None and inserted is not None
        conn.execute(
            "INSERT INTO audit_events(event_type,blog_id,payload) VALUES ('publication.request.blocked',%s,%s)",
            (
                request.blog_id,
                Jsonb(
                    {
                        "job_id": str(inserted["id"]),
                        "event_id": event["id"],
                        "reasons": assessed["reasons"],
                        "simulation_only": True,
                    }
                ),
            ),
        )
        return {**dict(inserted), "duplicate": False, "real_writes_enabled": False}


@router.post("/{job_id}/simulate")
def simulate(job_id: UUID, request: SimulationInput) -> dict[str, Any]:
    with connection() as conn:
        job = conn.execute(
            "SELECT id,status,publication_state FROM publishing_jobs WHERE id=%s", (job_id,)
        ).fetchone()
        if job is None:
            raise HTTPException(404, "Publication request not found")
        existing = conn.execute(
            "SELECT * FROM publication_attempts WHERE idempotency_key=%s",
            (request.idempotency_key,),
        ).fetchone()
        if existing:
            if str(existing["job_id"]) != str(job_id) or existing["scenario"] != request.scenario:
                raise HTTPException(409, "Idempotency key conflict")
            conn.execute(
                "INSERT INTO audit_events(event_type,payload) VALUES ('publication.mock.duplicate_blocked',%s)",
                (
                    Jsonb(
                        {
                            "job_id": str(job_id),
                            "attempt_id": str(existing["id"]),
                            "simulation_only": True,
                        }
                    ),
                ),
            )
            return {**dict(existing), "duplicate": True, "real_writes_enabled": False}
        result = FakeBloggerPublisher().publish(request.scenario)
        attempt = conn.execute(
            """INSERT INTO publication_attempts(job_id,idempotency_key,scenario,outcome,fake_post_id,result)
              VALUES (%s,%s,%s,%s,%s,%s) RETURNING *""",
            (
                job_id,
                request.idempotency_key,
                request.scenario,
                result["outcome"],
                result["fake_post_id"],
                Jsonb(result),
            ),
        ).fetchone()
        assert attempt is not None
        conn.execute(
            "INSERT INTO audit_events(event_type,payload) VALUES ('publication.mock.simulated',%s)",
            (
                Jsonb(
                    {
                        "job_id": str(job_id),
                        "attempt_id": str(attempt["id"]),
                        "scenario": request.scenario,
                        "outcome": result["outcome"],
                        "external_network_calls": 0,
                        "publication_state_unchanged": job["publication_state"],
                    }
                ),
            ),
        )
        return {
            **dict(attempt),
            "duplicate": False,
            "real_writes_enabled": False,
            "publication_state_unchanged": job["publication_state"],
        }
