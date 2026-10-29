"""Compact, read-only operational dashboard projection."""
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .operations import health as operations_health
from .publication_daily import (
    GLOBAL_DAILY_PUBLISH_LIMIT,
    LANGUAGE_DAILY_LIMITS,
    LANGUAGE_HOURLY_LIMITS,
    kst_day_bounds,
    summarize_daily_usage,
)


def _grouped_counts(conn: Any, query: str) -> dict[str, int]:
    return {str(row["key"]): int(row["count"]) for row in conn.execute(query).fetchall()}

def dashboard_snapshot(conn: Any) -> dict[str, Any]:
    """Return observed state only; configured schedules are not execution proof."""
    # The application role intentionally cannot read schema_migrations. Migration
    # markers are also append-only in audit_events, which is visible to the app.
    schema = conn.execute(
        """SELECT max(CASE WHEN payload->>'version' ~ '^[0-9]{1,3}$'
                    THEN (payload->>'version')::int END)::int AS version
        FROM audit_events WHERE event_type LIKE 'schema.%.migrated'"""
    ).fetchone()
    job_counts = _grouped_counts(conn, """SELECT task_kind || ':' || status AS key,count(*)::int AS count FROM job_runs GROUP BY task_kind,status""")
    generation_counts = _grouped_counts(conn, "SELECT state AS key,count(*)::int AS count FROM generation_results GROUP BY state")
    quality_counts = _grouped_counts(conn, "SELECT status AS key,count(*)::int AS count FROM article_quality_evaluations GROUP BY status")
    publication_counts = _grouped_counts(conn, """SELECT status || ':' || publication_state AS key,count(*)::int AS count FROM publishing_jobs GROUP BY status,publication_state""")
    record_count = conn.execute("SELECT count(*)::int AS count FROM publishing_records").fetchone()["count"]
    latest_published = conn.execute("SELECT max(published_at) AS at FROM publishing_records").fetchone()["at"]
    # Use an explicit KST date; never rely on the host or PostgreSQL session timezone.
    today_kst = datetime.now(UTC).astimezone(ZoneInfo("Asia/Seoul")).date()
    day_start, day_end = kst_day_bounds(today_kst)
    daily_rows = conn.execute(
        """SELECT b.language_code,count(*)::int AS count FROM publishing_records r
        JOIN blogger_blogs b ON b.id=r.blog_id
        WHERE r.published_at >= %s AND r.published_at < %s GROUP BY b.language_code""",
        (day_start, day_end),
    ).fetchall()
    daily_published = {str(row["language_code"]): int(row["count"]) for row in daily_rows}
    reservation_rows = conn.execute(
        """SELECT b.language_code,count(*)::int AS count FROM publishing_jobs j
        JOIN blogger_blogs b ON b.id=j.blog_id
        WHERE j.status IN ('queued','running') AND j.scheduled_at >= %s AND j.scheduled_at < %s
          AND NOT EXISTS (SELECT 1 FROM publishing_records r WHERE r.job_id=j.id)
        GROUP BY b.language_code""",
        (day_start, day_end),
    ).fetchall()
    daily_reserved = {str(row["language_code"]): int(row["count"]) for row in reservation_rows}
    daily_publication = summarize_daily_usage(daily_published, daily_reserved)
    daily_publication["date_kst"] = today_kst.isoformat()
    daily_publication["items"] = [dict(row) for row in conn.execute(
        """SELECT r.published_at,b.language_code,b.display_name AS blog_name,b.url AS blog_url,
        r.remote_post_id,r.content_version_id,r.job_id,v.title,j.adapter_type,j.simulation_only,
        j.status AS job_status,CASE WHEN j.simulation_only THEN 'simulation' ELSE 'agent' END AS origin
        FROM publishing_records r JOIN blogger_blogs b ON b.id=r.blog_id
        JOIN content_versions v ON v.id=r.content_version_id
        JOIN publishing_jobs j ON j.id=r.job_id
        WHERE r.published_at >= %s AND r.published_at < %s
        ORDER BY r.published_at DESC,r.id DESC LIMIT 100""",
        (day_start, day_end),
    ).fetchall()]
    daily_publication["remote_posts_synchronized"] = False
    daily_publication["remote_sync_note"] = "Blogger 원격 수동 게시물은 아직 동기화되지 않아 이 집계에 포함되지 않습니다."
    mock_job_state = {str(row["blog_id"]):dict(row) for row in conn.execute(
        """SELECT blog_id,max(updated_at) FILTER (WHERE status='succeeded') AS last_success,
        max(updated_at) FILTER (WHERE status='failed') AS last_failure,
        (array_agg(last_error_category ORDER BY updated_at DESC) FILTER (WHERE status='failed'))[1] AS failure_reason
        FROM publishing_jobs WHERE simulation_only AND adapter_type='fake' GROUP BY blog_id"""
    ).fetchall()}
    trend_available = bool(conn.execute("SELECT to_regclass('public.trend_collection_runs') IS NOT NULL AS available").fetchone()["available"])
    research_worker = conn.execute(
        "SELECT process_id,status,last_seen_at,last_error_category FROM worker_heartbeats WHERE service_name='research_worker'"
    ).fetchone()
    publication_worker = conn.execute(
        "SELECT process_id,status,last_seen_at,last_error_category FROM worker_heartbeats WHERE service_name='publication_worker'"
    ).fetchone()
    worker_fresh = bool(
        research_worker
        and research_worker.get("status") == "running"
        and research_worker.get("last_seen_at")
        and datetime.now(UTC) - research_worker["last_seen_at"] <= timedelta(seconds=45)
    )
    trends: dict[str, Any] = {"configured":trend_available,"periodic_worker":"running" if worker_fresh else "inactive","last_collected_at":None,
        "worker_heartbeat_at":research_worker.get("last_seen_at") if research_worker else None,
        "worker_error_category":research_worker.get("last_error_category") if research_worker else None,
        "successful_runs":0,"failed_runs":0,"observations_last_24h":0,"regions":[]}
    if trend_available:
        run_totals = conn.execute("""SELECT count(*) FILTER (WHERE status='succeeded')::int AS succeeded,
            count(*) FILTER (WHERE status='failed')::int AS failed,max(finished_at) FILTER (WHERE status='succeeded') AS last_success
            FROM trend_collection_runs""").fetchone()
        trends.update({"successful_runs":int(run_totals["succeeded"] or 0),"failed_runs":int(run_totals["failed"] or 0),
            "last_collected_at":run_totals["last_success"],
            "observations_last_24h":conn.execute("SELECT count(*)::int AS count FROM trend_observations WHERE collected_at >= now()-interval '24 hours'").fetchone()["count"],
            "regions":[dict(row) for row in conn.execute("""SELECT geo,count(*)::int AS observations,max(collected_at) AS last_collected_at
                FROM trend_observations WHERE collected_at >= now()-interval '24 hours' GROUP BY geo ORDER BY geo""").fetchall()]})
    trend_pipeline: dict[str, Any] = {
        "search_terms_24h": int(trends["observations_last_24h"]),
        "unique_issue_groups_24h": 0,
        "article_candidates": 0,
        "held_issue_groups_24h": 0,
        "research_packages_24h": 0,
        "research_triage": None,
        "awaiting_official_research_issues_24h": 0,
        "ai_articles_written_24h": 0,
        "actual_posts_24h": 0,
        "article_lineage_available": False,
        "generation_block_reason": "ai_generation_provider_not_connected",
        "publication_block_reason": "research_package_and_quality_approval_required",
        "hold_reasons": [],
    }
    topic_schema = conn.execute(
        "SELECT to_regclass('public.trend_topics') IS NOT NULL AS available"
    ).fetchone()
    if topic_schema and topic_schema["available"]:
        assessed = conn.execute(
            """WITH latest AS (
              SELECT DISTINCT ON (a.topic_id) a.topic_id,a.decision
              FROM trend_topic_assessments a ORDER BY a.topic_id,a.created_at DESC
            ), recent AS (
              SELECT DISTINCT m.topic_id FROM trend_topic_memberships m
              JOIN trend_observations o ON o.id=m.observation_id
              WHERE o.collected_at>=now()-interval '24 hours'
            )
            SELECT count(*) FILTER (WHERE latest.decision='review_required')::int AS candidates,
                   count(*) FILTER (WHERE latest.decision='held')::int AS held
            FROM latest JOIN recent USING(topic_id)"""
        ).fetchone()
        trend_pipeline.update({
            "unique_issue_groups_24h": conn.execute(
                """SELECT count(DISTINCT t.id)::int AS count FROM trend_topics t
                JOIN trend_topic_memberships m ON m.topic_id=t.id
                JOIN trend_observations o ON o.id=m.observation_id
                WHERE o.collected_at>=now()-interval '24 hours'"""
            ).fetchone()["count"],
            "article_candidates": assessed["candidates"],
            "held_issue_groups_24h": assessed["held"],
        })
        packages_ready = conn.execute(
            "SELECT to_regclass('public.trend_research_packages') IS NOT NULL AS available"
        ).fetchone()
        if packages_ready and packages_ready["available"]:
            trend_pipeline["research_packages_24h"] = conn.execute(
                """SELECT count(*)::int AS count FROM trend_research_packages
                WHERE created_at>=now()-interval '24 hours'"""
            ).fetchone()["count"]
        trend_pipeline["hold_reasons"] = [dict(row) for row in conn.execute(
            """WITH latest AS (
              SELECT DISTINCT ON (topic_id) topic_id,reasons
              FROM trend_topic_assessments ORDER BY topic_id,created_at DESC,id DESC
            ), recent AS (
              SELECT DISTINCT m.topic_id FROM trend_topic_memberships m
              JOIN trend_observations o ON o.id=m.observation_id
              WHERE o.collected_at>=now()-interval '24 hours'
            ) SELECT unnest(latest.reasons) AS reason,count(*)::int AS count
              FROM latest JOIN recent USING(topic_id)
              GROUP BY reason ORDER BY count DESC,reason LIMIT 10"""
        ).fetchall()]
        triage = conn.execute(
            """SELECT payload,created_at FROM audit_events
            WHERE event_type='trend.research_candidates.selected'
              AND created_at>=now()-interval '24 hours'
            ORDER BY created_at DESC LIMIT 1"""
        ).fetchone()
        if triage:
            trend_pipeline["research_triage"] = {
                **dict(triage["payload"]), "created_at": triage["created_at"]
            }
        trend_pipeline["awaiting_official_research_issues_24h"] = conn.execute(
            """WITH latest AS (
              SELECT DISTINCT ON (topic_id) topic_id,reasons
              FROM trend_topic_assessments ORDER BY topic_id,created_at DESC,id DESC
            ), recent AS (
              SELECT DISTINCT m.topic_id FROM trend_topic_memberships m
              JOIN trend_observations o ON o.id=m.observation_id
              WHERE o.collected_at>=now()-interval '24 hours'
            ) SELECT count(*)::int AS count FROM latest JOIN recent USING(topic_id)
              WHERE 'awaiting_official_research'=ANY(latest.reasons)"""
        ).fetchone()["count"]
    collection_sources = [dict(row) for row in conn.execute("""SELECT adapter,name,active,scheduled,interval_minutes,last_successful_at,
        (last_error IS NOT NULL) AS has_error,next_run_at
        FROM collection_sources ORDER BY name""").fetchall()]
    scheduled_import: dict[str, Any] = {
        "available": False, "scheduled_claims": 0, "verified_gpt_runs": 0,
        "received_total": 0, "received_last_24h": 0, "last_received_at": None,
        "languages": {}, "machine_passed": 0, "quality_held": 0,
        "source_review_held": 0, "duplicate_file_outcomes": 0,
        "outcomes": {}, "recent": [], "worker_poll_seconds": 60,
        "worker_status": "running" if worker_fresh else "inactive",
    }
    import_relation = conn.execute(
        "SELECT to_regclass('public.external_content_imports') IS NOT NULL AS available"
    ).fetchone()
    if import_relation and import_relation["available"]:
        scheduled_import["available"] = True
        totals = conn.execute(
            """SELECT count(*)::int AS total,
            count(*) FILTER (WHERE received_at >= now()-interval '24 hours')::int AS recent,
            max(received_at) AS last_received
            FROM external_content_imports WHERE generation_method='chatgpt_scheduled_export'"""
        ).fetchone()
        scheduled_import.update({
            "received_total": int(totals["total"] or 0),
            "received_last_24h": int(totals["recent"] or 0),
            "last_received_at": totals["last_received"],
        })
        scheduled_import["languages"] = {
            str(row["language_code"]): int(row["count"])
            for row in conn.execute(
                """SELECT language_code,count(*)::int AS count FROM external_content_imports
                WHERE generation_method='chatgpt_scheduled_export' GROUP BY language_code"""
            ).fetchall()
        }
        if conn.execute(
            "SELECT to_regclass('public.external_content_import_assessments') IS NOT NULL AS available"
        ).fetchone()["available"]:
            assessment_counts = conn.execute(
                """WITH latest AS (SELECT DISTINCT ON (import_id) import_id,machine_passed,independent_source_verification
                FROM external_content_import_assessments ORDER BY import_id,assessed_at DESC,id DESC)
                SELECT count(*) FILTER (WHERE latest.machine_passed)::int AS passed,
                count(*) FILTER (WHERE NOT latest.machine_passed)::int AS held,
                count(*) FILTER (WHERE NOT latest.independent_source_verification)::int AS source_held
                FROM latest JOIN external_content_imports i ON i.id=latest.import_id
                WHERE i.generation_method='chatgpt_scheduled_export'"""
            ).fetchone()
            scheduled_import.update({
                "machine_passed": int(assessment_counts["passed"] or 0),
                "quality_held": int(assessment_counts["held"] or 0),
                "source_review_held": int(assessment_counts["source_held"] or 0),
            })
        scheduled_import["outcomes"] = _grouped_counts(
            conn,
            """SELECT payload->>'status' AS key,count(*)::int AS count FROM audit_events
            WHERE event_type='scheduled_import.file_outcome' AND payload ? 'status'
            GROUP BY payload->>'status'""",
        )
        scheduled_import["scheduled_claims"] = conn.execute(
            """SELECT count(*)::int AS count FROM audit_events
            WHERE event_type='content.import.scheduled_origin_recorded'"""
        ).fetchone()["count"]
        scheduled_import["duplicate_file_outcomes"] = conn.execute(
            """SELECT count(*)::int AS count FROM audit_events
            WHERE event_type='scheduled_import.file_outcome' AND payload->>'duplicate'='true'"""
        ).fetchone()["count"]
        scheduled_import["recent"] = [dict(row) for row in conn.execute(
            """SELECT i.id AS import_id,i.language_code,i.title,i.state,i.received_at,
            i.research_package_id,i.generation_method,v.id AS import_version_id,
            l.content_version_id,origin.payload->>'inbox_file_name' AS inbox_file_name,
            origin.payload->>'inbox_file_sha256' AS inbox_file_sha256,
            origin.id AS audit_event_id,a.machine_passed,a.independent_source_verification
            FROM external_content_imports i
            LEFT JOIN LATERAL (SELECT id FROM external_content_import_versions
              WHERE import_id=i.id ORDER BY version_number DESC LIMIT 1) v ON true
            LEFT JOIN external_content_import_content_links l ON l.import_id=i.id AND l.import_version_id=v.id
            LEFT JOIN LATERAL (SELECT id,payload FROM audit_events
              WHERE event_type='content.import.scheduled_origin_recorded'
                AND payload->>'import_id'=i.id::text ORDER BY id DESC LIMIT 1) origin ON true
            LEFT JOIN LATERAL (SELECT machine_passed,independent_source_verification
              FROM external_content_import_assessments WHERE import_id=i.id AND version_id=v.id
              ORDER BY assessed_at DESC,id DESC LIMIT 1) a ON true
            WHERE i.generation_method='chatgpt_scheduled_export'
            ORDER BY i.received_at DESC,i.id DESC LIMIT 20"""
        ).fetchall()]
    config_rows = [dict(row) for row in conn.execute("""SELECT scope_type,scope_key,configured_mode,daily_auto_limit,minimum_interval_minutes,emergency_stopped
        FROM publication_mode_settings""").fetchall()]
    global_config = next((row for row in config_rows if row["scope_type"]=="global"),
        {"configured_mode":"manual","emergency_stopped":False,"daily_auto_limit":1})
    languages = {str(row["code"]):str(row["display_name"]) for row in conn.execute("SELECT code,display_name FROM languages ORDER BY code").fetchall()}
    blog_rows = conn.execute("""SELECT b.id,b.language_code,b.display_name,b.url,b.active,b.blog_id,b.connection_verified_at,b.last_checked_at,
        (b.connection_error IS NOT NULL) AS has_connection_error,
        g.status AS oauth_status,g.scopes FROM blogger_blogs b LEFT JOIN google_connections g ON g.id=b.oauth_connection_id
        ORDER BY b.language_code,b.display_name""").fetchall()
    blogs = []
    for blog in blog_rows:
        blog_id,language = str(blog["id"]),str(blog["language_code"])
        selected = next((row for row in config_rows if row["scope_type"]=="blog" and row["scope_key"]==blog_id),
            next((row for row in config_rows if row["scope_type"]=="language" and row["scope_key"]==language),global_config))
        scopes = set(blog["scopes"] or [])
        mock_state = mock_job_state.get(blog_id,{})
        blogs.append({"id":blog_id,"language_code":language,"language_name":languages.get(language,language),"display_name":blog["display_name"],
            "url":blog["url"],"active":bool(blog["active"]),"blog_id_registered":bool(blog["blog_id"]),
            "oauth_status":blog["oauth_status"] or "not_connected",
            "read_scope":"https://www.googleapis.com/auth/blogger.readonly" in scopes or "https://www.googleapis.com/auth/blogger" in scopes,
            "write_scope":"https://www.googleapis.com/auth/blogger" in scopes,
            "last_access_verification_at":blog["last_checked_at"] or blog["connection_verified_at"],"has_connection_error":bool(blog["has_connection_error"]),
            "configured_mode":selected.get("configured_mode","manual"),"daily_limit":selected.get("daily_auto_limit",1),"hourly_limit":None,
            "minimum_interval_minutes":selected.get("minimum_interval_minutes",1440),"live_auto_enabled":False,"live_writes_enabled":False,
            "recent_success_at":None,"recent_failure_reason":None,"last_mock_success_at":mock_state.get("last_success"),
            "last_mock_failure_at":mock_state.get("last_failure"),"last_mock_failure_reason":mock_state.get("failure_reason"),
            "recent_public_url":None,"public_url_note":"게시 URL이 실제 게시 기록에 저장되지 않아 표시할 수 없습니다."})
    backup = operations_health()
    publication_worker_fresh = bool(
        publication_worker
        and publication_worker.get("status") == "running"
        and publication_worker.get("last_seen_at")
        and datetime.now(UTC) - publication_worker["last_seen_at"] <= timedelta(seconds=45)
    )
    worker_health = [
        {
            "service": "research_worker",
            "status": "running" if worker_fresh else "stale" if research_worker else "not_started",
            "process_id": research_worker.get("process_id") if research_worker else None,
            "last_seen_at": research_worker.get("last_seen_at") if research_worker else None,
            "last_error_category": research_worker.get("last_error_category") if research_worker else None,
        },
        {
            "service": "publication_worker",
            "status": "running" if publication_worker_fresh else "stale" if publication_worker else "not_started",
            "process_id": publication_worker.get("process_id") if publication_worker else None,
            "last_seen_at": publication_worker.get("last_seen_at") if publication_worker else None,
            "last_error_category": publication_worker.get("last_error_category") if publication_worker else None,
        },
    ]
    live_ready_count = conn.execute(
        "SELECT count(*)::int AS count FROM article_quality_evaluations WHERE publish_ready=true"
    ).fetchone()["count"]
    blocked_live_jobs = sum(
        count for key, count in publication_counts.items()
        if key.startswith(("blocked:", "uncertain:", "failed:"))
    )
    alerts: list[dict[str, Any]] = []
    if not worker_fresh:
        alerts.append({"key": "research_worker_heartbeat", "severity": "critical", "count": 1,
                       "message": "Research Worker heartbeat가 없거나 45초보다 오래됐습니다."})
    if backup.get("warning"):
        alerts.append({"key": "backup_or_disk_warning", "severity": "warning", "count": 1,
                       "message": "백업이 오래됐거나 백업 상태 또는 여유 디스크 공간을 확인해야 합니다."})
    if not scheduled_import.get("verified_gpt_runs"):
        alerts.append({"key": "gpt_schedule_unverified", "severity": "warning", "count": 1,
                       "message": "GPT 예약 원고의 무인 실행·로컬 전달이 확인되지 않았습니다."})
    if blocked_live_jobs:
        alerts.append({"key": "blocked_or_uncertain_publication_jobs", "severity": "warning",
                       "count": blocked_live_jobs, "message": "차단·불확실·실패 게시 작업을 확인해야 합니다."})
    if trend_pipeline["article_candidates"] == 0:
        alerts.append({"key": "no_publish_candidate", "severity": "notice", "count": 1,
                       "message": "현재 검증 단계를 통과한 게시 후보가 없습니다."})
    alerts.sort(key=lambda item: ("critical", "warning", "notice").index(item["severity"]))
    checks = [
        {"key": "trends_11_regions", "status": "partial", "detail": "최근 지역별 관측은 표시하지만 실행 Worker의 코드 버전은 확인되지 않았습니다."},
        {"key": "candidate_deduplication", "status": "partial", "detail": f"최근 24시간 이슈 그룹 {trend_pipeline['unique_issue_groups_24h']}개, 기사 후보 {trend_pipeline['article_candidates']}개."},
        {"key": "official_research", "status": "blocked" if not trend_pipeline["research_packages_24h"] else "partial", "detail": f"Research Package {trend_pipeline['research_packages_24h']}건; 사람 검토·독립 근거 승인과 자동 조사 실행을 구분합니다."},
        {"key": "gpt_unattended_delivery", "status": "blocked", "detail": "공식 예약 실행의 로컬 자동 전달은 검증되지 않았습니다."},
        {"key": "content_import", "status": "partial", "detail": f"Import receiver worker 상태 {scheduled_import['worker_status']}; 예약 원고 수신 {scheduled_import['received_total']}건."},
        {"key": "quality_seo_rights", "status": "partial", "detail": f"기계 통과 기록 {quality_counts.get('machine_passed_review_required',0)}건, 사람·권리·독립 출처 승인은 별도입니다."},
        {"key": "version_audit", "status": "ready", "detail": "기존 버전과 감사 이력을 유지하는 저장 경로가 연결되어 있습니다."},
        {"key": "publish_eligibility", "status": "blocked" if not live_ready_count else "partial", "detail": f"게시 적격 평가 {live_ready_count}건; 사람 검토와 별도 게시 승인은 계속 필요합니다."},
        {"key": "blogger_live_publisher", "status": "blocked", "detail": "실제 Blogger 쓰기와 공개 게시는 현재 비활성화되어 있습니다."},
        {"key": "kst_daily_limits", "status": "partial", "detail": "KST 내부 안전 상한은 코드에 구성됐으나 원격 수동 게시 동기화는 미확인입니다."},
        {"key": "rate_limit_and_serialization", "status": "partial", "detail": "내부 큐·정책을 유지하며 실 Blogger 요청에 대한 제한/복구 검증은 수행하지 않았습니다."},
        {"key": "remote_post_revalidation", "status": "not_tested", "detail": "실제 게시 레코드가 없어 Blogger 원격 GET 재검증 이력이 없습니다."},
        {"key": "emergency_stop", "status": "partial", "detail": "긴급 중지 UI/API는 있으나 운영 상태 변경 없이 이번 리허설을 생략했습니다."},
        {"key": "windows_recovery", "status": "partial", "detail": "정상 종료·상태 스크립트와 Worker 단일 실행 보호를 사용하지만 실제 재부팅은 시험하지 않았습니다."},
    ]
    modes = [
        {"key": "observation", "label": "Mode A · Observation", "status": "partial", "detail": "읽기·수집 현황을 관찰할 수 있지만 정기 코드 적용과 원고 공급은 미확인입니다."},
        {"key": "draft", "label": "Mode B · Draft", "status": "blocked", "detail": "이번 리허설에서 실 Blogger 초안 생성/GET 재검증을 하지 않았습니다."},
        {"key": "controlled_publish", "label": "Mode C · Controlled Publish", "status": "blocked", "detail": "특정 원고 공개 승인과 게시 적격 원고가 없습니다."},
        {"key": "auto", "label": "Mode D · Auto", "status": "blocked", "detail": "자동 생성 공급·운영 승인·실 게시 경로가 모두 준비되지 않았으며 Auto는 OFF입니다."},
    ]
    readiness = {
        "decision": "READY FOR OBSERVATION ONLY",
        "current_mode": "observation",
        "modes": modes,
        "checks": checks,
        "limits": {
            "timezone": "Asia/Seoul",
            "global_daily": GLOBAL_DAILY_PUBLISH_LIMIT,
            "language_daily": {**LANGUAGE_DAILY_LIMITS, "en": None},
            "language_hourly": LANGUAGE_HOURLY_LIMITS,
            "english_daily_policy": "remaining_global_capacity",
            "configured_auto_daily": int(global_config.get("daily_auto_limit", 1)),
            "configured_auto_minimum_interval_minutes": int(global_config.get("minimum_interval_minutes", 1440)),
        },
    }
    monitoring = {
        "overall": "warning" if alerts else "normal",
        "workers": worker_health,
        "api_database_request": "healthy",
        "backup": backup,
        "alerts": alerts,
        "alert_delivery_configured": False,
        "alert_policy": "grouped_by_condition; dashboard_only",
        "emergency_stopped": bool(global_config.get("emergency_stopped", False)),
    }
    schema_version = int(schema["version"] or 0) if schema else 0
    return {"schema_version":schema_version,"trends":trends,"trend_pipeline":trend_pipeline,"collection_sources":collection_sources,"scheduled_import":scheduled_import,"jobs":job_counts,
        "readiness":readiness,"monitoring":monitoring,
        "generation":{"provider_connected":False,"provider_status":"not_configured","counts":generation_counts,
            "queue_waiting":job_counts.get("content:queued",0),"reason":"운영 원고 생성 Provider가 연결되어 있지 않습니다."},
        "quality":{"machine_passed":quality_counts.get("machine_passed_review_required",0),"held":quality_counts.get("quality_held",0),
            "failed":quality_counts.get("failed",0),"human_review_required":quality_counts.get("machine_passed_review_required",0)},
        "publishing":{"jobs":publication_counts,"recorded_posts":int(record_count or 0),"last_recorded_at":latest_published,"recent_public_url":None,
            "url_note":"게시 기록에 공개 URL 필드가 없어 링크를 추정하지 않습니다.",
            "queued_mock_jobs":sum(v for k,v in publication_counts.items() if k.startswith("queued:")),
            "live_writes_enabled":False,"auto_enabled":False,"emergency_stopped":bool(global_config.get("emergency_stopped",False)),
            "configured_global_mode":global_config.get("configured_mode","manual"),"daily":daily_publication},
        "blogs":blogs,
        "schedules":[
            {"key":"google_trends","name":"Google Trends 정기 수집","status":"partial" if worker_fresh else "inactive","detail":"Research Worker heartbeat는 확인되지만 실행 코드 버전과 11개 지역 무인 주기 적용 여부는 확인되지 않았습니다." if worker_fresh else "최근 Research Worker heartbeat가 없습니다."},
            {"key":"market_close","name":"국가별 장마감 리포트","status":"not_configured","detail":"시장 데이터·거래일·장마감 원고 생성 경로가 구성되지 않았습니다."},
            {"key":"weekly_finance","name":"금요일 금융자료 분석","status":"not_configured","detail":"후보 자료 수집과 주간 실행 경로가 연결되지 않았습니다."},
            {"key":"gpt_scheduled_import","name":"GPT 예약 작업 원고 수신","status":"external_status_unknown","detail":"외부 예약 작업의 실행 상태를 이 로컬 서비스에서 확인할 수 없습니다."}],
        "publication_policy":{"configured_global_mode":global_config.get("configured_mode","manual"),"live_auto_enabled":False,"live_writes_enabled":False,
            "hourly_limit":LANGUAGE_HOURLY_LIMITS,"hourly_limit_status":"configured_internal_cap","daily_limit":GLOBAL_DAILY_PUBLISH_LIMIT,
            "emergency_stopped":bool(global_config.get("emergency_stopped",False))},
        "recent_public_url":None,"search_console_connected":False,"search_performance":"미연결: 검색 실적을 표시하지 않습니다.",
        "limitations":["실제 Blogger 게시와 Auto 게시는 비활성화되어 있습니다.","설정 값만으로 실제 Worker 실행을 증명하지 않습니다.",
            "운영 원고 생성 Provider가 연결되지 않았습니다."]}
