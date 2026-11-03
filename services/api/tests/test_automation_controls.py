from contextlib import contextmanager
from uuid import UUID, uuid4

import pytest
from test_content_imports import valid_item
from test_pipeline import lab as shared_lab
from woori import (
    automation_auto,
    blogger_writes,
    content_imports,
    editorial_intelligence,
    external_policy,
    keyword_jobs,
    publication_operation,
    publication_worker,
    publications,
    trend_editorial,
    trends,
)
from woori import automation_controls as controls

lab = shared_lab
BASE = "/admin/automation-controls"


@pytest.fixture
def center(lab, monkeypatch):
    conn, api, h = lab

    @contextmanager
    def shared():
        with conn.transaction():
            yield conn

    for module in (
        controls,
        automation_auto,
        publications,
        publication_operation,
        publication_worker,
        content_imports,
        trends,
        trend_editorial,
        editorial_intelligence,
        keyword_jobs,
        blogger_writes,
    ):
        monkeypatch.setattr(module, "connection", shared)
    return conn, api, h


def update(center, **kw):
    _, api, h = center
    revision = api.get(BASE, headers=h).json()["settings"]["revision"]
    return api.put(
        BASE,
        headers=h,
        json={
            "expected_revision": revision,
            "actor": "isolated admin",
            "reason": "Isolated explicit operator control change",
            **kw,
        },
    )


def test_snapshot_is_real_and_auth_required(center):
    _, api, h = center
    assert api.get(BASE).status_code == 401
    data = api.get(BASE, headers=h)
    assert data.status_code == 200, data.text
    assert data.json()["settings"]["auto_publishing_enabled"] is False
    assert data.json()["google_write_verified"] is False
    assert data.json()["effective"]["auto_publishing_enabled"] == "신규 실행 중지"


def test_independent_switches_persist_and_audit(center):
    conn, api, h = center
    assert update(center, trends_collection_enabled=False).status_code == 200
    assert controls.allowed("trends_collection_enabled") is False
    assert update(center, auto_manuscript_enabled=False).status_code == 200
    assert update(center, manual_publishing_enabled=False).status_code == 200
    current = api.get(BASE, headers=h).json()["settings"]
    assert not current["trends_collection_enabled"] and not current["auto_manuscript_enabled"]
    assert not current["manual_publishing_enabled"] and not current["auto_publishing_enabled"]
    event = conn.execute(
        "SELECT payload FROM audit_events WHERE event_type='automation.controls.changed' ORDER BY id DESC LIMIT 1"
    ).fetchone()["payload"]
    assert event["actor"] == "isolated admin" and event["changes"]
    assert update(center, trends_collection_enabled=True).status_code == 200
    assert controls.allowed("trends_collection_enabled") is True


def test_operator_auto_approval_is_separate_confirmed_audited_and_fail_closed(center):
    conn, api, h = center
    initial = api.get(BASE, headers=h).json()
    assert initial["settings"]["automatic_publication_operator_approved"] is False
    assert initial["effective"]["automatic_publication_operator_approved"] == "자동 발행 운영 승인 OFF — 자동 발행 중지"
    assert initial["settings"]["operations_auto_approved"] is False
    revision = initial["settings"]["revision"]
    assert update(center, automatic_publication_operator_approved=True).status_code == 422
    assert update(
        center,
        automatic_publication_operator_approved=True,
        confirm_operator_auto_approval=True,
        reason="          ",
    ).status_code == 422
    enabled = update(
        center,
        automatic_publication_operator_approved=True,
        confirm_operator_auto_approval=True,
    )
    assert enabled.status_code == 200, enabled.text
    current = api.get(BASE, headers=h).json()
    assert current["settings"]["automatic_publication_operator_approved"] is True
    assert current["settings"]["operations_auto_approved"] is False
    assert current["settings"]["configured_mode"] == "manual"
    assert current["automatic_publication_approval"]["effective"] is False
    assert current["automatic_publication_approval"]["scope"]["global_auto_publication_enabled"] is False
    assert current["settings"]["automatic_publication_approval_actor"] == "isolated admin"
    assert current["settings"]["automatic_publication_approval_reason"] == "Isolated explicit operator control change"
    assert current["settings"]["revision"] == revision + 1
    assert controls.allowed("automatic_publication_operator_approved") is True
    event = conn.execute(
        "SELECT payload FROM audit_events WHERE event_type='automation.operator_publication_approval.changed' ORDER BY id DESC LIMIT 1"
    ).fetchone()["payload"]
    assert event["previous_approval"] is False and event["new_approval"] is True
    assert event["policy_checks"]["external_write_authorized_by_this_change"] is False
    assert event["policy_checks"]["historical_jobs_reauthorized"] is False
    assert update(
        center,
        automatic_publication_operator_approved=False,
        confirm_operator_auto_approval=True,
    ).status_code == 200
    assert api.get(BASE, headers=h).json()["settings"]["automatic_publication_operator_approved"] is False


def test_operator_approval_off_blocks_automatic_admission_but_not_manual_lane(center):
    conn, _, _ = center
    before = conn.execute("SELECT count(*) n FROM publishing_jobs").fetchone()["n"]
    assert automation_auto.enqueue(conn, controls.read(conn)) == 0
    assert conn.execute("SELECT count(*) n FROM publishing_jobs").fetchone()["n"] == before
    auto_job, blog, version = make_job(center, "scheduled_auto", "publish")
    state = controls.read(conn)
    link_trends(conn, version, blog)
    origin_grant(conn, auto_job, version, state, blog, "publish")
    assert controls.job_permitted(conn, auto_job) is False
    update(center, google_account_available=True, emergency_stop=False, confirm_emergency_release=True)
    assert publication_operation.manual_requests_allowed() is True


def test_off_blocks_real_collection_and_topic_scoring_without_remote_call(center, monkeypatch):
    update(center, trends_collection_enabled=False, auto_manuscript_enabled=False)
    monkeypatch.setattr(trends, "_collect_geo", lambda *a: pytest.fail("collection must not start"))
    assert trends.collect_geo("KR")["status"] == "disabled"
    assert trends.schedule_tick()["status"] == "disabled"
    assert editorial_intelligence.assess_current() == {}
    assert trend_editorial.dispatch()["created"] == 0


def test_emergency_and_account_release_are_independent_and_confirmed(center):
    _, api, h = center
    assert update(center, emergency_stop=False).status_code == 422
    assert update(center, google_account_available=True).status_code == 200
    state = api.get(BASE, headers=h).json()["settings"]
    assert state["emergency_stop"] and not state["blogger_api_restricted"]
    assert update(center, emergency_stop=False, confirm_emergency_release=True).status_code == 200
    assert publication_operation.manual_requests_allowed() is True
    assert update(center, manual_publishing_enabled=False).status_code == 200
    assert publication_operation.manual_requests_allowed() is False
    assert api.get(BASE, headers=h).json()["settings"]["auto_publishing_enabled"] is False


def test_auto_enable_requires_scope_live_confirmation_and_preserves_stop(center):
    conn, api, h = center
    conn.execute(
        "INSERT INTO blogger_blogs(language_code,url,blog_id,display_name,active) VALUES('en','https://control-fixture.blogspot.com','1234567890123456','Control fixture',true)"
    )
    blog = str(
        conn.execute(
            "SELECT id FROM blogger_blogs WHERE url='https://control-fixture.blogspot.com'"
        ).fetchone()["id"]
    )
    assert update(center, auto_publishing_enabled=True).status_code == 422
    assert (
        update(
            center,
            auto_publishing_enabled=True,
            trends_auto_publishing_enabled=True,
            auto_blog_ids=[blog],
            auto_mode="publish",
            confirm_auto=True,
        ).status_code
        == 422
    )
    assert (
        update(
            center,
            auto_publishing_enabled=True,
            trends_auto_publishing_enabled=True,
            auto_blog_ids=[blog],
            auto_mode="publish",
            confirm_auto=True,
            confirm_live=True,
        ).status_code
        == 200
    )
    data = api.get(BASE, headers=h).json()
    assert data["settings"]["emergency_stop"] is True
    assert data["effective"]["auto_publishing_enabled"] == "긴급 정지로 차단"
    assert publication_worker.tick(allow_manual_confirmed_publications=True) is None


def test_revision_conflict_and_strict_boolean(center):
    _, api, h = center
    payload = {
        "expected_revision": 1,
        "actor": "isolated",
        "reason": "valid operator reason",
        "auto_manuscript_enabled": "false",
    }
    assert api.put(BASE, headers=h, json=payload).status_code == 422
    update(center, auto_manuscript_enabled=False)
    payload["auto_manuscript_enabled"] = True
    assert api.put(BASE, headers=h, json=payload).status_code == 409


def test_global_publish_interval_change_is_persisted_and_audited(center):
    conn, api, h = center
    before = api.get(BASE, headers=h).json()["settings"]
    assert update(center, global_publish_min_interval_minutes=14).status_code == 422
    minimum = update(center, global_publish_min_interval_minutes=15)
    assert minimum.status_code == 200, minimum.text
    before = api.get(BASE, headers=h).json()["settings"]
    response = update(center, global_publish_min_interval_minutes=60)
    assert response.status_code == 200, response.text
    after = api.get(BASE, headers=h).json()["settings"]
    assert after["global_publish_min_interval_minutes"] == 60
    assert after["revision"] == before["revision"] + 1
    event = conn.execute(
        "SELECT payload FROM audit_events WHERE event_type='automation.controls.changed' ORDER BY id DESC LIMIT 1"
    ).fetchone()["payload"]
    change = next(item for item in event["changes"] if item["key"] == "global_publish_min_interval_minutes")
    assert (change["before"], change["after"]) == (before["global_publish_min_interval_minutes"], 60)
    assert event["reason"] == "Isolated explicit operator control change"
    assert update(center, global_publish_min_interval_minutes=14).status_code == 422


def test_live_mode_and_scope_save_while_master_is_off(center):
    conn, api, h = center
    blog = conn.execute(
        "INSERT INTO blogger_blogs(language_code,url,blog_id,display_name,active) "
        "VALUES('en',%s,'1234567890123456','Policy fixture',true) RETURNING id",
        (f"https://policy-{uuid4().hex}.blogspot.com",),
    ).fetchone()["id"]
    assert update(center, auto_mode="publish", auto_blog_ids=[str(blog)]).status_code == 422
    saved = update(center, auto_mode="publish", auto_blog_ids=[str(blog)], confirm_live=True)
    assert saved.status_code == 200, saved.text
    state = api.get(BASE, headers=h).json()["settings"]
    assert state["auto_mode"] == "publish"
    assert state["auto_blog_ids"] == [str(blog)]
    assert state["auto_publishing_enabled"] is False
    assert update(center, scheduled_auto_publishing_enabled=True, confirm_auto=True).status_code == 422
    assert update(center, scheduled_auto_publishing_enabled=True, confirm_auto=True, confirm_live=True).status_code == 200
    state = api.get(BASE, headers=h).json()["settings"]
    assert state["scheduled_auto_publishing_enabled"] is True
    assert state["auto_publishing_enabled"] is False
    assert api.get(BASE, headers=h).json()["effective"]["scheduled_auto_publishing_enabled"] == "전체 자동 발행 OFF로 차단 중"


def test_scheduled_readiness_uses_existing_scheduled_evidence_gate(center, monkeypatch):
    from woori import publication_origin

    _, blog, version = make_job(center)
    with controls.connection() as conn:
        link = conn.execute(
            "SELECT import_id FROM external_content_import_content_links WHERE content_version_id=%s",
            (version,),
        ).fetchone()
    monkeypatch.setattr(publication_origin, "classify", lambda *_: {
        "kind": "scheduled", "import_id": str(link["import_id"])
    })
    monkeypatch.setattr(external_policy, "_scheduled_publication_approval", lambda *_: {"scope": ["scheduled_publication"]})
    monkeypatch.setattr(publication_worker, "_scheduled_eligibility", lambda *_: {"reasons": [], "evidence": {}})
    monkeypatch.setattr(publications, "_assess", lambda *_args, **_kw: pytest.fail("manual assessment applied to scheduled original"))
    with controls.connection() as conn:
        row, snapshot, reasons = automation_auto.readiness(conn, version, blog)
    assert row is not None and snapshot["import_id"] == str(link["import_id"])
    assert "human_review_pending" not in reasons
    monkeypatch.setattr(external_policy, "_scheduled_publication_approval", lambda *_: None)
    with controls.connection() as conn:
        _, _, reasons = automation_auto.readiness(conn, version, blog)
    assert "scheduled_import_or_policy_unavailable" in reasons


def test_manual_worker_does_not_requeue_legacy_scheduled_imports(center, monkeypatch):
    update(center, google_account_available=True, emergency_stop=False,
           confirm_emergency_release=True)
    monkeypatch.setattr(automation_auto, "tick", lambda **_kw: None)
    monkeypatch.setattr(publication_worker, "enqueue_scheduled_auto_jobs",
                        lambda: pytest.fail("legacy historical enqueue must not run"))
    assert publication_worker.tick(allow_manual_confirmed_publications=True) is None


def test_new_scheduled_lane_preserves_existing_kst_daily_ceiling(center):
    from psycopg.types.json import Jsonb

    conn, _, _ = center
    job, blog, _ = make_job(center, lane="scheduled_auto")
    conn.execute(
        """INSERT INTO scheduled_publication_policy_events
        (action,approved_blog_ids,daily_limit,actor_label,reason,idempotency_key)
        VALUES('enabled',%s,1,'isolated admin','Isolated scheduled daily ceiling check',%s)""",
        (Jsonb([str(blog)]), uuid4().hex),
    )
    assert not automation_auto.scheduled_daily_available(conn, blog)
    conn.execute("UPDATE publishing_jobs SET status='blocked' WHERE id=%s", (job,))
    assert automation_auto.scheduled_daily_available(conn, blog)


def make_job(center, lane="manual", mode="publish", method=None):
    conn, api, h = center
    from woori.editorial_taxonomy import suggested_labels

    method = method or (
        "codex_trends_export" if lane == "scheduled_auto" else "manual_codex_import"
    )
    item = valid_item(
        content_id=str(uuid4()),
        generation_method=method,
        google_trends_based=method == "codex_trends_export",
        blogger_labels=suggested_labels(
            "policy", "en", google_trends_based=method == "codex_trends_export"
        ),
    )
    result = api.post(
        "/admin/research/content-imports",
        headers=h,
        json={"submitted_by": "isolated control", "item": item},
    ).json()
    version = UUID(result["content_version_id"])
    blog = conn.execute(
        "INSERT INTO blogger_blogs(language_code,url,blog_id,display_name,active) VALUES('en',%s,'1234567890123456','Isolated control',true) RETURNING id",
        (f"https://control-{uuid4().hex}.blogspot.com",),
    ).fetchone()["id"]
    profile = conn.execute(
        "INSERT INTO language_profiles(language_code,target_country) VALUES('en','US') ON CONFLICT(language_code,target_country) DO UPDATE SET search_intent=language_profiles.search_intent RETURNING id"
    ).fetchone()["id"]
    policy = conn.execute(
        "INSERT INTO publishing_policies(language_code,blog_id,profile_id,active) VALUES('en',%s,%s,true) RETURNING id",
        (blog, profile),
    ).fetchone()["id"]
    oauth = conn.execute(
        "INSERT INTO google_connections(label,status,scopes) VALUES('isolated grant','connected',ARRAY['https://www.googleapis.com/auth/blogger']) RETURNING id"
    ).fetchone()["id"]
    conn.execute("UPDATE blogger_blogs SET oauth_connection_id=%s WHERE id=%s", (oauth, blog))
    job = conn.execute(
        """INSERT INTO publishing_jobs(policy_id,blog_id,content_version_id,idempotency_key,scheduled_at,status,publication_state,adapter_type,simulation_only,publication_lane,oauth_connection_id,live_stage,publication_mode)
        VALUES(%s,%s,%s,%s,now(),'running','publishing','blogger_live',false,%s,%s,'draft_needed',%s) RETURNING id""",
        (policy, blog, version, uuid4().hex, lane, oauth, mode),
    ).fetchone()["id"]
    return job, blog, version


def test_only_new_grants_execute_and_toggle_invalidates_old_manual_job(center):
    conn, _, _ = center
    job, _, _ = make_job(center)
    update(
        center, google_account_available=True, emergency_stop=False, confirm_emergency_release=True
    )
    assert controls.job_permitted(conn, job) is False
    controls.grant_manual(conn, job, "publish")
    assert controls.job_permitted(conn, job, running=True) is True
    update(center, manual_publishing_enabled=False)
    assert controls.job_permitted(conn, job) is False
    update(center, manual_publishing_enabled=True)
    assert controls.job_permitted(conn, job) is False


def test_discarded_manuscript_blocks_granted_job_at_wire(center):
    conn, _, _ = center
    job, blog, version = make_job(center)
    update(center, google_account_available=True, emergency_stop=False, confirm_emergency_release=True)
    controls.grant_manual(conn, job, "publish")
    assert controls.job_permitted(conn, job, running=True) is True
    conn.execute(
        """INSERT INTO manuscript_discards(group_id,blog_id,content_version_id,status,previous_view,reason,actor)
        SELECT group_id,%s,id,'discarded','queue','Isolated wire safety test','test operator'
        FROM content_versions WHERE id=%s""",
        (blog, version),
    )
    assert controls.job_permitted(conn, job, running=True) is False


def test_publication_display_origin_uses_import_lineage(center):
    conn, _, _ = center
    _, blog, version = make_job(center)
    from woori.publication_origin import classify_display_many

    missing = str(uuid4())
    result = classify_display_many(conn, [(str(version), str(blog)), (missing, str(blog))])
    assert result[(str(version), str(blog))]["kind"] == "manual"
    assert result[(missing, str(blog))]["kind"] == "unknown"


def test_db_unavailable_fails_closed_without_affecting_imports(center, monkeypatch):
    import psycopg

    @contextmanager
    def unavailable():
        raise psycopg.OperationalError("isolated failure")
        yield

    monkeypatch.setattr(controls, "connection", unavailable)
    assert controls.allowed("auto_manuscript_enabled") is False
    from woori.google_http import GoogleFailure

    with pytest.raises(GoogleFailure, match="policy_unavailable"), controls.write_guard():
        pytest.fail("no HTTP admission")


def test_worker_ack_is_revision_and_pid_bound(center):
    conn, api, h = center
    conn.execute(
        "INSERT INTO worker_heartbeats(service_name,process_id,status,last_seen_at) VALUES('research_worker',123,'running',now()) ON CONFLICT(service_name) DO UPDATE SET process_id=123,status='running',last_seen_at=now()"
    )
    controls.acknowledge(conn, "research_worker", 123)
    assert api.get(BASE, headers=h).json()["effective"]["trends_collection_enabled"] == "정상"
    update(center, auto_manuscript_enabled=False)
    assert api.get(BASE, headers=h).json()["effective"]["trends_collection_enabled"] != "정상"


@pytest.mark.parametrize("mode", ["draft", "publish"])
def test_mock_auto_dispatch_modes_and_off_invalidate_grants(center, monkeypatch, mode):
    from datetime import UTC, datetime

    conn, _, _ = center
    job, blog, _version = make_job(center, "scheduled_auto", mode)
    assert (
        update(
            center,
            auto_publishing_enabled=True,
            trends_auto_publishing_enabled=True,
            automatic_publication_operator_approved=True,
            auto_blog_ids=[str(blog)],
            auto_mode=mode,
            confirm_auto=True,
            confirm_operator_auto_approval=True,
            confirm_live=mode == "publish",
            google_account_available=True,
            emergency_stop=False,
            confirm_emergency_release=True,
        ).status_code
        == 200
    )
    link_trends(conn, _version, blog)
    origin_grant(conn, job, _version, controls.read(conn), blog, mode)
    conn.execute(
        "UPDATE publishing_jobs SET status='queued',publication_state='publication_queued' WHERE id=%s",
        (job,),
    )
    snapshot = {
        "title": "Approved synthetic article",
        "safe_html": "<p>Approved test only</p>",
        "blogger_labels": [],
        "blockers": [],
    }
    monkeypatch.setattr(automation_auto, "readiness", lambda *args: ({}, snapshot, []))
    monkeypatch.setattr(automation_auto, "enqueue", lambda *args, **kwargs: 0)
    monkeypatch.setattr(
        "woori.scheduled_duplicates.find_remote_duplicate", lambda *args, **kw: {"status": "clear"}
    )
    calls = []

    class Publisher:
        def create_draft(self, *args, **kw):
            assert automation_auto.context_allowed()
            calls.append("DRAFT")
            return {
                "post_id": "12345",
                "status": "DRAFT",
                "post_verified": True,
                "http_status": 200,
            }

        def create_live(self, *args, **kw):
            assert automation_auto.context_allowed("blogger_public_publish")
            calls.append("LIVE")
            return {
                "post_id": "12345",
                "status": "LIVE",
                "readback_verified": True,
                "published_at": datetime.now(UTC),
                "url": "https://control.blogspot.com/test",
            }

        def publish_draft(self, *args, **kw):
            assert automation_auto.context_allowed("blogger_public_publish")
            calls.append("LIVE")
            return {
                "post_id": "12345",
                "status": "LIVE",
                "readback_verified": True,
                "published_at": datetime.now(UTC),
                "url": "https://control.blogspot.com/test",
            }

    first = automation_auto.tick(publisher=Publisher())
    assert first["status"] == ("draft_saved" if mode == "draft" else "published"), first
    assert calls == (["DRAFT"] if mode == "draft" else ["LIVE"])
    assert update(center, auto_publishing_enabled=False).status_code == 200
    assert controls.job_permitted(conn, job) is False


def test_unknown_remote_duplicate_never_writes_and_never_retries(center, monkeypatch):
    conn, _, _ = center
    job, blog, _ = make_job(center, "scheduled_auto", "draft")
    update(
        center,
        auto_publishing_enabled=True,
        trends_auto_publishing_enabled=True,
        automatic_publication_operator_approved=True,
        auto_blog_ids=[str(blog)],
        confirm_auto=True,
        confirm_operator_auto_approval=True,
        google_account_available=True,
        emergency_stop=False,
        confirm_emergency_release=True,
    )
    state = controls.read(conn)
    version = conn.execute(
        "SELECT content_version_id FROM publishing_jobs WHERE id=%s", (job,)
    ).fetchone()["content_version_id"]
    link_trends(conn, version, blog)
    origin_grant(conn, job, version, state, blog, "draft")
    conn.execute("UPDATE publishing_jobs SET status='queued' WHERE id=%s", (job,))
    monkeypatch.setattr(automation_auto, "enqueue", lambda *a, **kw: 0)
    monkeypatch.setattr(automation_auto, "readiness", lambda *a: ({}, {"title": "Test"}, []))
    monkeypatch.setattr(
        "woori.scheduled_duplicates.find_remote_duplicate", lambda *a, **kw: {"status": "unknown"}
    )
    assert automation_auto.tick(publisher=object())["status"] == "uncertain"
    assert automation_auto.tick(publisher=object()) is None


def test_wire_guard_serializes_with_other_policy_writers(monkeypatch):
    from woori.db import connection

    monkeypatch.setattr(publication_operation, "blogger_writes_allowed", lambda: True)
    with controls.write_guard(), connection() as other:
        assert (
            other.execute("SELECT pg_try_advisory_xact_lock(20261102,103) acquired").fetchone()[
                "acquired"
            ]
            is False
        )
    with connection() as other:
        assert (
            other.execute("SELECT pg_try_advisory_xact_lock(20261102,103) acquired").fetchone()[
                "acquired"
            ]
            is True
        )


def test_auto_enqueue_only_new_versions_and_never_reauthorize_backlog(center, monkeypatch):
    conn, _, _ = center
    job, blog, version = make_job(center, method="codex_trends_export")
    update(
        center,
        auto_publishing_enabled=True,
        trends_auto_publishing_enabled=True,
        automatic_publication_operator_approved=True,
        auto_blog_ids=[str(blog)],
        confirm_auto=True,
        confirm_operator_auto_approval=True,
        google_account_available=True,
        emergency_stop=False,
        confirm_emergency_release=True,
    )
    monkeypatch.setattr(external_policy, "_blogger_policy_approval", lambda: {"approved": True})
    selected = conn.execute(
        "SELECT policy_id,oauth_connection_id FROM publishing_jobs WHERE id=%s", (job,)
    ).fetchone()
    monkeypatch.setattr(automation_auto, "readiness", lambda *args: (dict(selected), {}, []))
    assert automation_auto.enqueue(conn, controls.read(conn)) == 0

    newer = conn.execute(
        """INSERT INTO content_versions(group_id,language,localization_id,version,title,body,created_at)
        SELECT group_id,language,localization_id,version+1,title,body,clock_timestamp() FROM content_versions WHERE id=%s RETURNING id""",
        (version,),
    ).fetchone()["id"]
    original_link = conn.execute(
        "SELECT * FROM external_content_import_content_links WHERE content_version_id=%s",
        (version,),
    ).fetchone()
    import_version = conn.execute(
        """INSERT INTO external_content_import_versions(import_id,version_number,parent_version_id,title,body_markdown,seo_metadata,blogger_labels,content_sha256,author_label,change_reason)
        SELECT import_id,version_number+1,id,title||' revised',body_markdown,seo_metadata,blogger_labels,%s,author_label,'Isolated new version'
        FROM external_content_import_versions WHERE id=%s RETURNING id""",
        (uuid4().hex + uuid4().hex, original_link["import_version_id"]),
    ).fetchone()["id"]
    conn.execute(
        "INSERT INTO external_content_import_content_links(import_id,import_version_id,content_version_id) VALUES(%s,%s,%s)",
        (original_link["import_id"], import_version, newer),
    )
    link_trends(conn, version, blog)
    assert automation_auto.enqueue(conn, controls.read(conn)) == 1
    newjob = conn.execute(
        "SELECT id FROM publishing_jobs WHERE content_version_id=%s", (newer,)
    ).fetchone()["id"]
    assert controls.job_permitted(conn, newjob) is True
    update(center, auto_publishing_enabled=False)
    update(center, auto_publishing_enabled=True, auto_blog_ids=[str(blog)], confirm_auto=True)
    assert controls.job_permitted(conn, newjob) is False
    assert automation_auto.enqueue(conn, controls.read(conn)) == 0


def test_authoring_policy_does_not_depend_on_dashboard_and_fails_closed(center, monkeypatch):
    import httpx
    import psycopg

    def refused(request):
        raise httpx.ConnectError("isolated API refusal")

    assert controls.authoring_permission(transport=httpx.MockTransport(refused))["allowed"] is True
    update(center, auto_manuscript_enabled=False)
    result = controls.authoring_permission(transport=httpx.MockTransport(refused))
    assert result["allowed"] is False and result["source"] == "repository"

    @contextmanager
    def unavailable():
        raise psycopg.OperationalError("isolated policy unavailable")
        yield

    monkeypatch.setattr(controls, "connection", unavailable)
    result = controls.authoring_permission(transport=httpx.MockTransport(refused))
    assert result["allowed"] is False and result["source"] == "unavailable"
    assert (
        controls.authoring_permission(transport=httpx.MockTransport(lambda r: httpx.Response(401)))[
            "reason"
        ]
        == "automation_policy_access_denied"
    )


def test_derived_maintenance_checkpoint_leaves_history_unchanged(center):
    from woori import topics

    conn, _, _ = center
    before = conn.execute("SELECT count(*) n FROM trend_grouping_proposals").fetchone()["n"]
    rows = [
        {
            "id": uuid4(),
            "query": f"{geo} unique {i}" if geo == "US" else f"different article {i}",
            "geo": geo,
        }
        for geo in ("US", "KR")
        for i in range(40)
    ]
    with pytest.raises(topics.TopicMaintenancePaused), conn.transaction(force_rollback=True):
        topics._propose_cross_geo_pairs(conn, rows, lambda: True)
    assert conn.execute("SELECT count(*) n FROM trend_grouping_proposals").fetchone()["n"] == before


def test_auto_off_does_not_starve_explicit_manual_authoring(center, monkeypatch):
    conn, _, _ = center
    _, blog, _ = make_job(center)
    created = []
    for index, kind in enumerate(("google_trends", "user_keyword")):
        row = conn.execute(
            """INSERT INTO codex_authoring_jobs(request_key,request_sha256,job_type,blog_id,language_code,target_country,category,keyword,options,model,created_at)
            VALUES(%s,%s,%s,%s,'en','US','finance','isolated keyword','{}','isolated-model',now()+(%s*interval '1 second')) RETURNING id""",
            (uuid4(), "a" * 64, kind, blog, index),
        ).fetchone()
        created.append(row["id"])
    update(center, auto_manuscript_enabled=False)
    selected = []
    monkeypatch.setattr(keyword_jobs, "authoring_backoff", lambda _: None)
    monkeypatch.setattr(keyword_jobs, "generate", lambda job: selected.append(job["id"]))
    keyword_jobs.run_one()
    assert selected == [created[1]]
    assert (
        conn.execute(
            "SELECT state FROM codex_authoring_jobs WHERE id=%s", (created[0],)
        ).fetchone()["state"]
        == "queued"
    )


def link_trends(conn, version, blog):
    """Actual isolated Import -> Codex Job -> topic -> observation lineage."""
    from psycopg.types.json import Jsonb
    from test_trend_editorial import observation

    imported = conn.execute(
        "SELECT import_id FROM external_content_import_content_links WHERE content_version_id=%s",
        (version,),
    ).fetchone()["import_id"]
    topic = uuid4()
    conn.execute(
        "INSERT INTO trend_topics(id,normalized_key,representative_geo,representative_query,grouping_method,grouping_confidence,grouping_status) VALUES(%s,%s,'US','synthetic','single_observation',1,'exact_query_cluster_not_event_confirmed')",
        (topic, uuid4().hex),
    )
    obs = observation(conn, "synthetic publication origin", geo="US")
    conn.execute(
        "INSERT INTO trend_topic_memberships(topic_id,observation_id,grouping_rationale) VALUES(%s,%s,'Isolated linked source')",
        (topic, obs),
    )
    job = conn.execute(
        """INSERT INTO codex_authoring_jobs(request_key,request_sha256,job_type,blog_id,language_code,target_country,category,keyword,options,state,model,import_id,content_version_id,completed_at)
     VALUES(%s,%s,'google_trends',%s,'en','US','technology','synthetic','{}','imported_review','isolated',%s,%s,clock_timestamp()) RETURNING id""",
        (uuid4(), "a" * 64, blog, imported, version),
    ).fetchone()["id"]
    request = conn.execute(
        "INSERT INTO trend_generation_requests(topic_id,duplicate_key,contract,state,authoring_job_id) VALUES(%s,%s,%s,'imported',%s) RETURNING id",
        (topic, uuid4().hex, Jsonb({"target_blog_id": str(blog)}), job),
    ).fetchone()["id"]
    conn.execute("UPDATE codex_authoring_jobs SET trend_request_id=%s WHERE id=%s", (request, job))
    return job


def origin_grant(conn, job, version, state, blog, mode="draft"):
    from woori import publication_origin

    origin = publication_origin.classify(conn, version, blog)
    assert origin["kind"] == "google_trends", origin
    conn.execute(
        """INSERT INTO automation_publication_grants(job_id,epoch,lane,publication_mode,manuscript_origin,source_epoch,origin_import_id,origin_content_version_id)
     VALUES(%s,%s,'auto',%s,'google_trends',%s,%s,%s)""",
        (job, state["auto_epoch"], mode, state["trends_auto_epoch"], origin["import_id"], version),
    )
