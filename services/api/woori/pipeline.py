"""Durable research-to-internal-draft orchestration. No Blogger dependency."""

import hashlib
import json
import time
import unicodedata
from datetime import UTC, datetime
from difflib import SequenceMatcher
from typing import Any
from uuid import UUID

import psutil
import psycopg
from croniter import croniter
from psycopg.types.json import Jsonb

from .ai import Draft, EngineFailure, provider
from .db import connection
from .grounding import inspect


def required(row: dict[str, Any] | None) -> dict[str, Any]:
    if row is None:
        raise EngineFailure("required_database_row_missing")
    return row


def normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def emit(conn: Any, kind: str, run_id: UUID | None = None, **data: Any) -> None:
    conn.execute(
        "INSERT INTO audit_events(run_id,event_type,payload) VALUES (%s,%s,%s)",
        (run_id, "research." + kind, Jsonb(data)),
    )


def evidence(keyword_id: UUID) -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            """SELECT s.*,r.id AS review_id,r.approved,r.reason AS review_reason
            FROM research_sources s JOIN LATERAL
            (SELECT * FROM source_reviews WHERE source_id=s.id ORDER BY review_sequence DESC LIMIT 1) r ON true
            WHERE s.keyword_id=%s AND s.valid_until>now() AND r.approved AND NOT EXISTS(SELECT 1 FROM research_sources newer WHERE newer.keyword_id=s.keyword_id AND newer.url=s.url AND newer.revision>s.revision) ORDER BY s.is_primary DESC,s.id""",
            (keyword_id,),
        ).fetchall()
    if not rows or (not any(r["is_primary"] for r in rows) and len(rows) < 2):
        raise EngineFailure("insufficient_reviewed_evidence")
    return rows


def enqueue(
    keyword_id: UUID, key: str, profile_ids: list[UUID] | None = None, evaluation_only: bool = False
) -> dict[str, Any]:
    with connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(781203)")
        keyword = conn.execute(
            "SELECT * FROM keyword_candidates WHERE id=%s", (keyword_id,)
        ).fetchone()
        if (
            not keyword
            or keyword["status"] != "selected"
            or keyword["expires_at"] <= datetime.now(UTC)
        ):
            raise EngineFailure("keyword_not_selected_or_expired")
        targets = conn.execute(
            """SELECT g.*,p.language_code,p.target_country,p.search_intent,p.generation_policy,
            p.localization_policy,p.seo_policy,t.instructions,t.version AS prompt_version
            FROM generation_settings g JOIN language_profiles p ON p.id=g.profile_id
            JOIN languages l ON l.code=p.language_code JOIN prompt_templates t ON t.id=g.prompt_id
            WHERE l.active AND g.enabled ORDER BY (p.id=%s) DESC,p.language_code,p.target_country""",
            (keyword["profile_id"],),
        ).fetchall()
        if profile_ids is not None:
            targets = [t for t in targets if t["profile_id"] in profile_ids]
            if {t["profile_id"] for t in targets} != set(profile_ids):
                raise EngineFailure("inactive_or_unknown_target")
        if not targets or targets[0]["profile_id"] != keyword["profile_id"]:
            raise EngineFailure("source_profile_required")
        if evaluation_only and any(t["provider"] != "local" for t in targets):
            raise EngineFailure("evaluation_requires_real_local_provider")
        fingerprint = hashlib.sha256(
            json.dumps(
                [str(keyword_id), sorted(str(t["profile_id"]) for t in targets), evaluation_only]
            ).encode()
        ).hexdigest()
        old = conn.execute(
            "SELECT r.*,g.request_fingerprint FROM job_runs r JOIN generation_jobs g ON g.run_id=r.id WHERE r.idempotency_key=%s",
            (key,),
        ).fetchone()
        if old:
            legacy = hashlib.sha256(
                json.dumps(
                    [str(keyword_id), sorted(str(t["profile_id"]) for t in targets)]
                ).encode()
            ).hexdigest()
            if old["request_fingerprint"] != fingerprint and (
                evaluation_only or old["request_fingerprint"] != legacy
            ):
                raise EngineFailure("idempotency_conflict")
            return old
        if conn.execute("SELECT 1 FROM job_runs WHERE idempotency_key=%s", (key,)).fetchone():
            raise EngineFailure("idempotency_conflict")
        for t in targets:
            count = conn.execute(
                """SELECT count(*) AS n FROM generation_targets t JOIN generation_jobs j ON j.run_id=t.run_id
                WHERE t.profile_id=%s AND j.created_at>=date_trunc('day',now())""",
                (t["profile_id"],),
            ).fetchone()
            assert count is not None
            if count["n"] >= t["daily_limit"]:
                raise EngineFailure("daily_generation_limit")
        run = conn.execute(
            "INSERT INTO job_runs(idempotency_key,task_kind) VALUES (%s,'content') RETURNING *",
            (key,),
        ).fetchone()
        assert run is not None
        conn.execute(
            "INSERT INTO generation_jobs(run_id,keyword_id,request_fingerprint,evaluation_only) VALUES (%s,%s,%s,%s)",
            (run["id"], keyword_id, fingerprint, evaluation_only),
        )
        for t in targets:
            snapshot = json.loads(json.dumps(t, default=str))
            snapshot["evaluation_only"] = evaluation_only
            conn.execute(
                "INSERT INTO generation_targets VALUES (%s,%s,%s)",
                (run["id"], t["profile_id"], Jsonb(snapshot)),
            )
        emit(conn, "queued", run["id"], keyword_id=str(keyword_id), targets=len(targets))
        return run


def quality(
    draft: Draft, sources: list[dict[str, Any]], keyword: str, is_mock: bool
) -> dict[str, Any]:
    text = draft.title + " " + draft.body
    ids = {str(s["id"]) for s in sources}
    checks = {
        "source_ids_valid": bool(draft.source_ids) and set(draft.source_ids).issubset(ids),
        "keyword_in_title_and_body": normalized(keyword) in normalized(draft.title)
        and normalized(keyword) in normalized(draft.body),
        "structure": "##" in draft.body,
        "as_of_date": datetime.now(UTC).date().isoformat() in draft.body,
        "no_obvious_hype_or_fake_experience": not any(
            term in normalized(text)
            for term in (
                "guaranteed profit",
                "100% return",
                "i visited",
                "?? ??",
                "?? ??",
                "??? ??",
            )
        ),
        "limited_repetition": len([line for line in draft.body.splitlines() if line.strip()])
        == len({line for line in draft.body.splitlines() if line.strip()}),
        "metadata": bool(draft.summary and draft.keywords),
    }
    # Structural checks cannot certify factual truth, translation quality or copyright.
    return {
        "checks": checks,
        "internal_score": round(100 * sum(checks.values()) / len(checks)),
        "structural_pass": all(checks.values()),
        "human_review_required": True,
        "model_quality_verified": False,
        "mock": is_mock,
        "publish_ready": False,
    }


def process(run: dict[str, Any]) -> None:
    run_id, attempt = run["id"], run["attempts"]
    with connection() as conn:
        job = conn.execute("SELECT * FROM generation_jobs WHERE run_id=%s", (run_id,)).fetchone()
        assert job is not None
        keyword = conn.execute(
            "SELECT * FROM keyword_candidates WHERE id=%s", (job["keyword_id"],)
        ).fetchone()
        assert keyword is not None
        targets = conn.execute(
            "SELECT * FROM generation_targets WHERE run_id=%s ORDER BY (profile_id=%s) DESC,profile_id",
            (run_id, keyword["profile_id"]),
        ).fetchall()
    if keyword["status"] != "selected" or keyword["expires_at"] <= datetime.now(UTC):
        raise EngineFailure("keyword_not_selected_or_expired")
    sources = evidence(keyword["id"])
    for target in targets:
        profile_id = target["profile_id"]
        with connection() as conn:
            if conn.execute(
                "SELECT 1 FROM generation_results WHERE run_id=%s AND profile_id=%s",
                (run_id, profile_id),
            ).fetchone():
                continue
            active = conn.execute(
                "SELECT l.active,g.enabled,g.language_verified,g.provider,g.model FROM language_profiles p JOIN languages l ON l.code=p.language_code JOIN generation_settings g ON g.profile_id=p.id WHERE p.id=%s",
                (profile_id,),
            ).fetchone()
            if not active or not active["active"]:
                raise EngineFailure("language_disabled")
            if not active["enabled"]:
                raise EngineFailure("profile_processing_disabled")
            snapshot = target["settings_snapshot"]
            if snapshot["provider"] == "local" and (
                (not active["language_verified"] and not snapshot.get("evaluation_only"))
                or active["provider"] != "local"
                or active["model"] != snapshot["model"]
            ):
                raise EngineFailure("language_support_unverified")
            lease = conn.execute(
                """UPDATE job_runs r SET lease_until=now()+interval '300 seconds'
                FROM generation_jobs j,pipeline_controls c WHERE r.id=%s AND r.id=j.run_id AND r.status='running'
                AND r.attempts=%s AND NOT j.paused AND NOT c.paused AND r.lease_until>now() RETURNING r.id""",
                (run_id, attempt),
            ).fetchone()
            if not lease:
                raise EngineFailure("lease_lost_or_paused")
            emit(conn, "generation.started", run_id, profile_id=str(profile_id), attempt=attempt)
        policy = target["settings_snapshot"]
        with connection() as conn:
            emit(
                conn,
                "facts.checked",
                run_id,
                profile_id=str(profile_id),
                source_count=len(sources),
                verification="recorded_source_attestation",
            )
        context = {
            k: policy[k]
            for k in (
                "language_code",
                "target_country",
                "search_intent",
                "generation_policy",
                "localization_policy",
                "seo_policy",
                "instructions",
            )
        }
        with connection() as conn:
            glossary = conn.execute(
                "SELECT source_term,localized_term,notes FROM glossary_entries WHERE profile_id=%s",
                (profile_id,),
            ).fetchall()
            category = required(
                conn.execute(
                    "SELECT slug FROM categories WHERE id=%s", (keyword["category_id"],)
                ).fetchone()
            )
        context.update(
            glossary=glossary,
            category=category["slug"],
            original_profile_id=str(keyword["profile_id"]),
        )
        context.update(
            keyword=keyword["keyword"],
            as_of=datetime.now(UTC).date().isoformat(),
            sources=json.loads(json.dumps(sources, default=str)),
        )
        context["plan"] = {
            "angle": keyword["search_intent"],
            "outline": ["Verified evidence", "Country-specific context", "Sources and as-of date"],
            "currency_rule": "No currency conversion without dated official exchange-rate evidence",
            "no_investment_advice": True,
            "no_invented_experience": True,
        }
        with connection() as conn:
            source_draft = conn.execute(
                "SELECT v.id,v.title,v.body FROM generation_results g JOIN content_versions v ON v.id=g.content_version_id WHERE g.run_id=%s AND g.profile_id=%s",
                (run_id, keyword["profile_id"]),
            ).fetchone()
            context["original_draft"] = (
                json.loads(json.dumps(source_draft, default=str)) if source_draft else None
            )
            emit(
                conn, "planning.completed", run_id, profile_id=str(profile_id), plan=context["plan"]
            )
        context["_run_id"] = str(run_id)
        started = time.monotonic()
        draft = provider(policy["provider"]).generate(context, policy)
        checks = quality(draft, sources, keyword["keyword"], policy["provider"] == "mock")
        if policy["provider"] == "local":
            checks["grounding"] = inspect(draft, sources, policy["language_code"], context["as_of"])
        if not checks["structural_pass"] and policy["provider"] == "mock":
            raise EngineFailure("quality_checks_failed")
        digest = hashlib.sha256(normalized(draft.body).encode()).hexdigest()
        with connection() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(781204)")
            current = conn.execute(
                """SELECT r.id FROM job_runs r JOIN generation_jobs j ON j.run_id=r.id
                CROSS JOIN pipeline_controls c WHERE r.id=%s AND r.status='running' AND r.attempts=%s
                AND r.lease_until>now() AND NOT j.paused AND NOT c.paused FOR UPDATE OF r,j""",
                (run_id, attempt),
            ).fetchone()
            if not current:
                raise EngineFailure("lease_lost_or_paused")
            # Recheck revoked/expired evidence immediately before persistence.
            if {str(s["review_id"]) for s in evidence(keyword["id"])} != {
                str(s["review_id"]) for s in sources
            }:
                raise EngineFailure("evidence_changed")
            previous = conn.execute(
                """SELECT v.body FROM generation_results g JOIN content_versions v ON v.id=g.content_version_id
                WHERE g.profile_id=%s""",
                (profile_id,),
            ).fetchall()
            if any(
                SequenceMatcher(None, normalized(p["body"]), normalized(draft.body)).ratio() >= 0.97
                for p in previous
            ):
                raise EngineFailure("duplicate_content")
            k = conn.execute(
                "SELECT group_id FROM keyword_candidates WHERE id=%s FOR UPDATE", (keyword["id"],)
            ).fetchone()
            assert k is not None
            group_id = k["group_id"]
            if not group_id:
                group_id = required(
                    conn.execute(
                        "INSERT INTO content_groups DEFAULT VALUES RETURNING id"
                    ).fetchone()
                )["id"]
                conn.execute(
                    "UPDATE keyword_candidates SET group_id=%s WHERE id=%s",
                    (group_id, keyword["id"]),
                )
            localization_row = conn.execute(
                """INSERT INTO content_localizations(group_id,language_code,target_country) VALUES (%s,%s,%s)
                ON CONFLICT(group_id,language_code,target_country) DO NOTHING RETURNING id""",
                (group_id, policy["language_code"], policy["target_country"]),
            ).fetchone()
            localization = required(
                localization_row
                or conn.execute(
                    "SELECT id FROM content_localizations WHERE group_id=%s AND language_code=%s AND target_country=%s",
                    (group_id, policy["language_code"], policy["target_country"]),
                ).fetchone()
            )["id"]
            source_version = None
            if profile_id != keyword["profile_id"]:
                source = conn.execute(
                    "SELECT content_version_id FROM generation_results WHERE run_id=%s AND profile_id=%s",
                    (run_id, keyword["profile_id"]),
                ).fetchone()
                if not source:
                    raise EngineFailure("source_version_missing")
                source_version = source["content_version_id"]
            number = required(
                conn.execute(
                    "SELECT coalesce(max(version),0)+1 AS n FROM content_versions WHERE localization_id=%s",
                    (localization,),
                ).fetchone()
            )["n"]
            version = required(
                conn.execute(
                    """INSERT INTO content_versions(group_id,language,localization_id,version,title,body,source_version_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                    (
                        group_id,
                        policy["language_code"],
                        localization,
                        number,
                        draft.title,
                        draft.body,
                        source_version,
                    ),
                ).fetchone()
            )["id"]
            conn.execute(
                "INSERT INTO localization_categories VALUES (%s,%s) ON CONFLICT DO NOTHING",
                (localization, keyword["category_id"]),
            )
            conn.execute(
                """INSERT INTO generation_results(run_id,profile_id,content_version_id,provider,model,prompt_id,prompt_snapshot,
                source_snapshot,result_metadata,content_hash,elapsed_ms,state) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    run_id,
                    profile_id,
                    version,
                    policy["provider"],
                    policy["model"],
                    policy["prompt_id"],
                    Jsonb({"settings": policy, "context": context}),
                    Jsonb(context["sources"]),
                    Jsonb(
                        {
                            "summary": draft.summary,
                            "keywords": draft.keywords,
                            "referenced_source_ids": draft.source_ids,
                            "quality": checks,
                            "metrics": draft._metrics,
                        }
                    ),
                    digest,
                    int((time.monotonic() - started) * 1000),
                    "mock_draft"
                    if policy["provider"] == "mock"
                    else (
                        "human_review_required"
                        if not policy.get("evaluation_only")
                        and checks["structural_pass"]
                        and checks["grounding"]["rule_pass"]
                        else "quality_held"
                    ),
                ),
            )
            conn.execute(
                "INSERT INTO seo_audits(content_version_id,profile_id,passed,validator_adapter,checks) VALUES (%s,%s,false,'internal-structural-v1',%s)",
                (version, profile_id, Jsonb(checks)),
            )
            emit(
                conn,
                "generation.saved",
                run_id,
                profile_id=str(profile_id),
                version_id=str(version),
                version=number,
                state="internal_draft",
            )
            emit(conn, "seo.checked", run_id, profile_id=str(profile_id), publish_ready=False)


def resources_ok(controls: dict[str, Any]) -> bool:
    ram = psutil.virtual_memory()
    return bool(
        psutil.cpu_percent(interval=0.1) < controls["cpu_percent"]
        and ram.percent < controls["ram_percent"]
        and ram.available >= 6 * 1024**3
    )


def tick() -> bool:
    with connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(781205)")
        recovered = conn.execute("""UPDATE job_runs SET status=CASE WHEN attempts>=3 THEN 'failed' ELSE 'queued' END,
            lease_until=NULL,error_type='LeaseExpired',error_message='Content lease expired',error_location='pipeline',error_at=now(),updated_at=now()
            WHERE task_kind='content' AND status='running' AND lease_until<now() RETURNING id,status,attempts""").fetchall()
        for r in recovered:
            emit(conn, "recovered", r["id"], status=r["status"], attempt=r["attempts"])
            conn.execute(
                "INSERT INTO generation_attempts(run_id,attempt,event,error_category) VALUES (%s,%s,'recovered','lease_expired')",
                (r["id"], r["attempts"]),
            )
        controls = conn.execute("SELECT * FROM pipeline_controls").fetchone()
        assert controls is not None
        if controls["paused"] or not resources_ok(controls):
            return False
        running = required(
            conn.execute(
                "SELECT count(*) AS n FROM job_runs WHERE task_kind='content' AND status='running'"
            ).fetchone()
        )["n"]
        if running >= controls["max_concurrency"]:
            return False
        run = conn.execute("""SELECT r.* FROM job_runs r JOIN generation_jobs j ON j.run_id=r.id
            WHERE r.task_kind='content' AND r.status='queued' AND NOT j.paused AND r.available_at<=now()
            ORDER BY r.created_at FOR UPDATE OF r SKIP LOCKED LIMIT 1""").fetchone()
        if not run:
            return False
        run = conn.execute(
            """UPDATE job_runs SET status='running',attempts=attempts+1,lease_until=now()+interval '300 seconds',
            updated_at=now() WHERE id=%s RETURNING *""",
            (run["id"],),
        ).fetchone()
        assert run is not None
        emit(conn, "started", run["id"], attempt=run["attempts"])
    try:
        process(run)
    except (EngineFailure, psycopg.Error, ValueError, KeyError, TypeError) as exc:
        category = exc.category if isinstance(exc, EngineFailure) else "internal_generation_error"
        retry = (
            isinstance(exc, EngineFailure) and exc.retryable and run["attempts"] < 3
        ) or category in ("lease_lost_or_paused", "generation_cancelled")
        with connection() as conn:
            changed = conn.execute(
                """UPDATE job_runs SET status=%s,lease_until=NULL,available_at=now()+interval '30 seconds',
                error_type=%s,error_message=%s,error_location='pipeline',error_at=now(),updated_at=now()
                WHERE id=%s AND status='running' AND attempts=%s RETURNING id""",
                ("queued" if retry else "failed", category, category, run["id"], run["attempts"]),
            ).fetchone()
            if changed:
                emit(
                    conn,
                    "retry" if retry else "failed",
                    run["id"],
                    category=category,
                    attempt=run["attempts"],
                )
                conn.execute(
                    "INSERT INTO generation_attempts(run_id,attempt,event,error_category) VALUES (%s,%s,%s,%s)",
                    (run["id"], run["attempts"], "retry" if retry else "failed", category),
                )
    else:
        with connection() as conn:
            changed = conn.execute(
                """UPDATE job_runs SET status='succeeded',lease_until=NULL,resolution='Internal drafts saved; publication blocked',updated_at=now()
                WHERE id=%s AND status='running' AND attempts=%s RETURNING id""",
                (run["id"], run["attempts"]),
            ).fetchone()
            if changed:
                emit(conn, "completed", run["id"], attempt=run["attempts"])
    return True


def schedule_tick() -> None:
    from zoneinfo import ZoneInfo

    with connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(781203)")
        if required(conn.execute("SELECT paused FROM pipeline_controls").fetchone())["paused"]:
            return
        schedules = conn.execute(
            "SELECT * FROM research_schedules WHERE active AND next_run_at<=now() FOR UPDATE SKIP LOCKED"
        ).fetchall()
        for s in schedules:
            candidates = conn.execute(
                """SELECT k.id FROM keyword_candidates k JOIN generation_settings g ON g.profile_id=k.profile_id
                JOIN language_profiles p ON p.id=k.profile_id JOIN languages l ON l.code=p.language_code
                WHERE k.category_id=%s AND k.profile_id=%s AND k.status='selected' AND k.expires_at>now() AND l.active AND g.enabled
                AND NOT EXISTS(SELECT 1 FROM generation_jobs j WHERE j.keyword_id=k.id)
                ORDER BY k.priority DESC,k.collected_at LIMIT %s""",
                (s["category_id"], s["profile_id"], s["quantity"]),
            ).fetchall()
            # Enqueue inside this transaction via shared helper connection is not safe: gather after commit.
            next_at = croniter(s["schedule_cron"], datetime.now(ZoneInfo(s["timezone"]))).get_next(
                datetime
            )
            conn.execute(
                "UPDATE research_schedules SET next_run_at=%s WHERE id=%s", (next_at, s["id"])
            )
            emit(conn, "schedule.due", schedule_id=str(s["id"]), candidates=len(candidates))
            for k in candidates:
                # Durable occurrence key; dispatch is reconciled by the scheduler outbox below.
                conn.execute(
                    "INSERT INTO research_dispatches(schedule_id,keyword_id,occurrence) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                    (s["id"], k["id"], s["next_run_at"]),
                )
    with connection() as conn:
        pending = conn.execute(
            "SELECT * FROM research_dispatches WHERE dispatched_at IS NULL ORDER BY occurrence LIMIT 10"
        ).fetchall()
    for d in pending:
        try:
            enqueue(d["keyword_id"], "schedule-" + str(d["id"]))
        except EngineFailure as exc:
            with connection() as conn:
                conn.execute(
                    "UPDATE research_dispatches SET error_category=%s WHERE id=%s",
                    (exc.category, d["id"]),
                )
            continue
        with connection() as conn:
            conn.execute(
                "UPDATE research_dispatches SET dispatched_at=now(),error_category=NULL WHERE id=%s",
                (d["id"],),
            )
