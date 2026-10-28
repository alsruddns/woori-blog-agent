"""Compact, read-only operational dashboard projection."""
from typing import Any


def _grouped_counts(conn: Any, query: str) -> dict[str, int]:
    return {str(row["key"]): int(row["count"]) for row in conn.execute(query).fetchall()}

def dashboard_snapshot(conn: Any) -> dict[str, Any]:
    """Return observed state only; configured schedules are not execution proof."""
    schema = conn.execute("SELECT max(version)::int AS version FROM schema_migrations").fetchone()
    job_counts = _grouped_counts(conn, """SELECT task_kind || ':' || status AS key,count(*)::int AS count FROM job_runs GROUP BY task_kind,status""")
    generation_counts = _grouped_counts(conn, "SELECT state AS key,count(*)::int AS count FROM generation_results GROUP BY state")
    quality_counts = _grouped_counts(conn, "SELECT status AS key,count(*)::int AS count FROM article_quality_evaluations GROUP BY status")
    publication_counts = _grouped_counts(conn, """SELECT status || ':' || publication_state AS key,count(*)::int AS count FROM publishing_jobs GROUP BY status,publication_state""")
    record_count = conn.execute("SELECT count(*)::int AS count FROM publishing_records").fetchone()["count"]
    latest_published = conn.execute("SELECT max(published_at) AS at FROM publishing_records").fetchone()["at"]
    mock_job_state = {str(row["blog_id"]):dict(row) for row in conn.execute(
        """SELECT blog_id,max(updated_at) FILTER (WHERE status='succeeded') AS last_success,
        max(updated_at) FILTER (WHERE status='failed') AS last_failure,
        (array_agg(last_error_category ORDER BY updated_at DESC) FILTER (WHERE status='failed'))[1] AS failure_reason
        FROM publishing_jobs WHERE simulation_only AND adapter_type='fake' GROUP BY blog_id"""
    ).fetchall()}
    trend_available = bool(conn.execute("SELECT to_regclass('public.trend_collection_runs') IS NOT NULL AS available").fetchone()["available"])
    trends: dict[str, Any] = {"configured":trend_available,"periodic_worker":"inactive","last_collected_at":None,
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
    collection_sources = [dict(row) for row in conn.execute("""SELECT adapter,name,active,scheduled,interval_minutes,last_successful_at,
        (last_error IS NOT NULL) AS has_error,next_run_at
        FROM collection_sources ORDER BY name""").fetchall()]
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
    return {"schema_version":int(schema["version"] or 0),"trends":trends,"collection_sources":collection_sources,"jobs":job_counts,
        "generation":{"provider_connected":False,"provider_status":"not_configured","counts":generation_counts,
            "queue_waiting":job_counts.get("content:queued",0),"reason":"운영 원고 생성 Provider가 연결되어 있지 않습니다."},
        "quality":{"machine_passed":quality_counts.get("machine_passed_review_required",0),"held":quality_counts.get("quality_held",0),
            "failed":quality_counts.get("failed",0),"human_review_required":quality_counts.get("machine_passed_review_required",0)},
        "publishing":{"jobs":publication_counts,"recorded_posts":int(record_count or 0),"last_recorded_at":latest_published,"recent_public_url":None,
            "url_note":"게시 기록에 공개 URL 필드가 없어 링크를 추정하지 않습니다.",
            "queued_mock_jobs":sum(v for k,v in publication_counts.items() if k.startswith("queued:")),
            "live_writes_enabled":False,"auto_enabled":False,"emergency_stopped":bool(global_config.get("emergency_stopped",False)),
            "configured_global_mode":global_config.get("configured_mode","manual")},
        "blogs":blogs,
        "schedules":[
            {"key":"google_trends","name":"Google Trends 정기 수집","status":"inactive","detail":"수집 API는 있지만 주기 실행 Worker가 확인되지 않았습니다."},
            {"key":"market_close","name":"국가별 장마감 리포트","status":"not_configured","detail":"시장 데이터·거래일·장마감 원고 생성 경로가 구성되지 않았습니다."},
            {"key":"weekly_finance","name":"금요일 금융자료 분석","status":"not_configured","detail":"후보 자료 수집과 주간 실행 경로가 연결되지 않았습니다."},
            {"key":"gpt_scheduled_import","name":"GPT 예약 작업 원고 수신","status":"external_status_unknown","detail":"외부 예약 작업의 실행 상태를 이 로컬 서비스에서 확인할 수 없습니다."}],
        "publication_policy":{"configured_global_mode":global_config.get("configured_mode","manual"),"live_auto_enabled":False,"live_writes_enabled":False,
            "hourly_limit":None,"hourly_limit_status":"not_configured","daily_limit":global_config.get("daily_auto_limit",1),
            "emergency_stopped":bool(global_config.get("emergency_stopped",False))},
        "recent_public_url":None,"search_console_connected":False,"search_performance":"미연결: 검색 실적을 표시하지 않습니다.",
        "limitations":["실제 Blogger 게시와 Auto 게시는 비활성화되어 있습니다.","설정 값만으로 실제 Worker 실행을 증명하지 않습니다.",
            "운영 원고 생성 Provider가 연결되지 않았습니다."]}
