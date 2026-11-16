"""P104: isolated lineage, policy matrix and last-moment publication admission."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from psycopg.types.json import Jsonb
from test_automation_controls import BASE, link_trends, make_job, origin_grant, update
from test_automation_controls import center as shared_center
from test_automation_controls import lab as shared_lab
from woori import automation_auto, trends_publication
from woori import automation_controls as controls
from woori import publication_origin as origin
from woori import scheduled_execution_receipts as receipts

center = shared_center
lab = shared_lab


def policy(kind="google_trends"):
    now = datetime.now(UTC)
    settings = {
        "auto_publishing_enabled": True,
        "trends_auto_publishing_enabled": True,
        "scheduled_auto_publishing_enabled": True,
        "emergency_stop": False,
        "blogger_api_restricted": False,
        "auto_epoch": "global",
        "trends_auto_epoch": "trends",
        "scheduled_auto_epoch": "scheduled",
        "auto_enabled_at": now - timedelta(minutes=1),
        "trends_auto_enabled_at": now - timedelta(minutes=1),
        "scheduled_auto_enabled_at": now - timedelta(minutes=1),
        "auto_blog_ids": ["blog"],
        "auto_mode": "draft",
    }
    source = {
        "kind": kind,
        "content_version_id": "version",
        "target_blog_id": "blog",
        "import_id": "import",
        "completed_at": now,
    }
    grant = {
        "epoch": "global",
        "source_epoch": origin.ROUTES.get(kind),
        "publication_mode": "draft",
        "manuscript_origin": kind,
        "origin_import_id": "import",
        "origin_content_version_id": "version",
    }
    return settings, source, grant


@pytest.mark.parametrize(
    "master,trends,scheduled,kind,expected",
    [
        (False, True, False, "google_trends", False),
        (False, False, True, "scheduled", False),
        (True, True, False, "google_trends", True),
        (True, True, False, "scheduled", False),
        (True, False, True, "scheduled", True),
        (True, False, True, "google_trends", False),
        (True, True, True, "google_trends", True),
        (True, True, True, "scheduled", True),
        (True, False, False, "google_trends", False),
        (True, False, False, "scheduled", False),
        (True, True, True, "unknown", False),
        (True, True, True, "manual", False),
    ],
)
def test_route_matrix(master, trends, scheduled, kind, expected):
    settings, source, grant = policy(kind)
    settings.update(
        auto_publishing_enabled=master,
        trends_auto_publishing_enabled=trends,
        scheduled_auto_publishing_enabled=scheduled,
    )
    assert origin.decide(settings, source, "blog", grant, "version")["allowed"] is expected


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("emergency_stop", "emergency_stop_enabled"),
        ("blogger_api_restricted", "blogger_api_restricted"),
        ("source_epoch", "origin_grant_expired"),
        ("epoch", "automatic_grant_expired"),
        ("origin_import_id", "origin_grant_binding_mismatch"),
        ("origin_content_version_id", "origin_grant_binding_mismatch"),
        ("content_version", "origin_content_version_or_target_mismatch"),
        ("target", "automatic_target_not_approved"),
        ("old", "origin_predates_activation"),
        ("missing_cutoff", "origin_predates_activation"),
        ("quality", "quality_review_required"),
        ("duplicate", "duplicate_publication"),
    ],
)
def test_safety_conditions(mutation, reason):
    settings, source, grant = policy()
    version = "version"
    target = "blog"
    if mutation in {"emergency_stop", "blogger_api_restricted"}:
        settings[mutation] = True
    elif mutation in {"epoch", "source_epoch", "origin_import_id", "origin_content_version_id"}:
        grant[mutation] = None
    elif mutation == "content_version":
        version = "another"
    elif mutation == "target":
        target = "another"
    elif mutation == "old":
        source["completed_at"] = datetime.now(UTC) - timedelta(days=1)
    elif mutation == "missing_cutoff":
        settings["trends_auto_enabled_at"] = None
    elif mutation == "quality":
        grant["quality_ready"] = False
    elif mutation == "duplicate":
        grant["duplicate"] = True
    result = origin.decide(settings, source, target, grant, version)
    assert not result["allowed"] and reason in result["reasons"]


def enable(center, blog):
    response = update(
        center,
        automatic_publication_operator_approved=True,
        auto_publishing_enabled=True,
        trends_auto_publishing_enabled=True,
        scheduled_auto_publishing_enabled=True,
        auto_blog_ids=[str(blog)],
        confirm_operator_auto_approval=True,
        confirm_auto=True,
        emergency_stop=False,
        confirm_emergency_release=True,
        google_account_available=True,
    )
    assert response.status_code == 200, response.text


def test_route_revision_epochs_confirmation_and_persistence(center):
    conn, api, h = center
    before = controls.read(conn)
    assert (
        not before["trends_auto_publishing_enabled"]
        and not before["scheduled_auto_publishing_enabled"]
    )
    assert update(center, trends_auto_publishing_enabled=True).status_code == 422
    assert update(center, trends_auto_publishing_enabled=True, confirm_auto=True).status_code == 200
    state = controls.read(conn)
    assert state["revision"] == before["revision"] + 1
    assert (
        state["auto_epoch"] == before["auto_epoch"]
        and state["scheduled_auto_epoch"] == before["scheduled_auto_epoch"]
    )
    assert state["trends_auto_epoch"] != before["trends_auto_epoch"]
    snapshot = api.get(BASE, headers=h).json()
    assert snapshot["effective"]["trends_auto_publishing_enabled"] == "전체 자동 발행 OFF로 차단 중"
    assert snapshot["settings"]["trends_auto_publishing_enabled"] is True
    assert (
        conn.execute(
            "SELECT payload FROM audit_events WHERE event_type='automation.controls.changed' ORDER BY id DESC LIMIT 1"
        ).fetchone()["payload"]["old_jobs_reauthorized"]
        is False
    )
    assert update(center, trends_auto_publishing_enabled="true").status_code == 422


def test_real_trends_lineage_and_missing_or_manual_identity(center):
    conn, _, _ = center
    _, blog, version = make_job(center, "scheduled_auto", "draft")
    assert origin.classify(conn, version, blog)["kind"] == "unknown"
    author = link_trends(conn, version, blog)
    assert origin.classify(conn, version, blog)["kind"] == "google_trends"
    other = uuid4()
    assert origin.classify(conn, version, other)["kind"] == "unknown"
    conn.execute("UPDATE codex_authoring_jobs SET state='import_pending' WHERE id=%s", (author,))
    assert origin.classify(conn, version, blog)["kind"] == "unknown"


def test_manual_import_is_never_auto_origin(center):
    conn, _, _ = center
    _, manual_blog, manual_version = make_job(center)
    assert origin.classify(conn, manual_version, manual_blog)["kind"] == "manual"
    assert origin.classify(conn, uuid4(), manual_blog)["kind"] == "unknown"


def test_route_off_at_wire_blocks_without_http_and_other_route_survives(center, monkeypatch):
    conn, _, _ = center
    job, blog, version = make_job(center, "scheduled_auto", "draft")
    enable(center, blog)
    link_trends(conn, version, blog)
    origin_grant(conn, job, version, controls.read(conn), blog)
    # Mock only the Trends content decision, not lineage/policy.
    monkeypatch.setattr(
        trends_publication,
        "validate_trends_job",
        lambda *_args: {"row": {"id": "linked"}, "assessment": {"followups": []}, "reasons": []},
    )
    assert controls.job_permitted(conn, job, running=True)
    # Unrelated path setting changes do not revoke this route's immutable grant.
    assert update(center, scheduled_auto_publishing_enabled=False).status_code == 200
    assert controls.job_permitted(conn, job, running=True)
    assert update(center, trends_auto_publishing_enabled=False).status_code == 200
    from woori.google_http import GoogleFailure

    with (
        automation_auto.job_context(job),
        pytest.raises(GoogleFailure),
        controls.write_guard("/blogs/1234567890123456/posts"),
    ):
        pytest.fail("OFF must prevent any HTTP admission")
    assert update(center, trends_auto_publishing_enabled=True, confirm_auto=True).status_code == 200
    assert not controls.job_permitted(conn, job)  # Re-enabling does not resurrect the old grant.
    assert (
        conn.execute("SELECT status FROM publishing_jobs WHERE id=%s", (job,)).fetchone()["status"]
        == "running"
    )
    event = conn.execute(
        "SELECT payload FROM audit_events WHERE event_type='automation.origin_publication.blocked' ORDER BY id DESC LIMIT 1"
    ).fetchone()["payload"]
    assert event["blogger_write_performed"] is False


def test_old_global_grant_has_no_origin_authority(center):
    conn, _, _ = center
    job, blog, version = make_job(center, "scheduled_auto", "draft")
    enable(center, blog)
    link_trends(conn, version, blog)
    state = controls.read(conn)
    conn.execute(
        "INSERT INTO automation_publication_grants(job_id,epoch,lane,publication_mode) VALUES(%s,%s,'auto','draft')",
        (job, state["auto_epoch"]),
    )
    assert not controls.job_permitted(conn, job)
    conn.execute("UPDATE publishing_jobs SET status='queued' WHERE id=%s", (job,))
    assert automation_auto.tick(publisher=object()) is None
    assert (
        conn.execute("SELECT status FROM publishing_jobs WHERE id=%s", (job,)).fetchone()["status"]
        == "queued"
    )


def scheduled_identity(tmp_path, monkeypatch):
    from test_automation_invocation import _session, _write_automation
    from woori.automation_invocation import resolve_current_invocation

    project = tmp_path / "project"
    project.mkdir()
    automations = tmp_path / ".codex/automations"
    _write_automation(automations, project)
    sessions = tmp_path / ".codex/sessions"
    sessions.mkdir(parents=True)
    session = str(uuid4())
    _session(
        sessions / f"rollout-{session}.jsonl",
        session_id=session,
        project=project,
        started_at=datetime(2026, 10, 30, 10, 58, 25, tzinfo=UTC),
        trigger="automation_cron_scheduled",
    )

    def resolve(automation_id, *, project_root, environ):
        return resolve_current_invocation(
            automation_id,
            project_root=project_root,
            automations_root=automations,
            sessions_root=sessions,
            environ=environ,
        )

    monkeypatch.setattr(receipts, "ROOT", project)
    monkeypatch.setattr(receipts, "resolve_current_invocation", resolve)
    actual = resolve("automation-8", project_root=project, environ={"CODEX_THREAD_ID": session})
    return actual


def test_scheduled_receipt_checks_real_trigger_and_rejects_tampering(tmp_path, monkeypatch):
    actual = scheduled_identity(tmp_path, monkeypatch)
    assert not receipts.verify(actual)
    receipts.record(actual)
    receipts.record(actual)
    assert receipts.verify(actual)
    altered = actual | {"scheduled_slot": "2026-11-01T20:00:00+09:00"}
    assert not receipts.verify(altered)
    assert not receipts.verify(actual | {"scheduler_occurrence_id": actual["occurrence_id"]})
    with pytest.raises(ValueError, match="identity_conflict"):
        receipts.record(actual | {"session_id": str(uuid4())})
    # Local receipt alone cannot turn a manual Desktop trigger into a schedule.
    path = receipts._path(actual["occurrence_id"])
    import json

    value = json.loads(path.read_text())
    value["execution_mode"] = "manual"
    path.write_text(json.dumps(value))
    assert not receipts.verify(actual)


def test_scheduled_import_requires_exact_blog_occurrence_and_verified_receipt(
    center, tmp_path, monkeypatch
):
    conn, _, _ = center
    job, blog, version = make_job(center, mode="draft", method="chatgpt_scheduled_export")
    enable(center, blog)
    actual = scheduled_identity(tmp_path, monkeypatch)
    metadata = {
        **actual,
        "import_id": str(
            conn.execute(
                "SELECT import_id FROM external_content_import_content_links WHERE content_version_id=%s",
                (version,),
            ).fetchone()["import_id"]
        ),
        "target_blog_id": "1234567890123456",
    }
    conn.execute(
        "INSERT INTO audit_events(event_type,payload,created_at) VALUES('content.import.scheduled_origin_recorded',%s,clock_timestamp())",
        (Jsonb(metadata),),
    )
    assert origin.classify(conn, version, blog)["kind"] == "unknown"
    receipts.record(actual)
    result = origin.classify(conn, version, blog)
    assert result["kind"] == "scheduled", result
    assert (
        result["occurrence_id_source"] == "project_derived_kst_slot"
        and result["scheduler_occurrence_id"] is None
    )
    state = controls.read(conn)
    conn.execute(
        """INSERT INTO automation_publication_grants(job_id,epoch,lane,publication_mode,manuscript_origin,source_epoch,origin_import_id,origin_content_version_id)
        VALUES(%s,%s,'auto','draft','scheduled',%s,%s,%s)""",
        (job, state["auto_epoch"], state["scheduled_auto_epoch"], metadata["import_id"], version),
    )
    assert controls.job_permitted(conn, job)
    monkeypatch.setattr(automation_auto, "readiness", lambda *a: ({}, {}, []))
    assert controls.job_permitted(conn, job, running=True)
    update(center, scheduled_auto_publishing_enabled=False)
    assert not controls.job_permitted(conn, job, running=True)
    # Conflicting lineage is never guessed; preserve both audit events.
    conn.execute(
        "INSERT INTO audit_events(event_type,payload) VALUES('content.import.scheduled_origin_recorded',%s)",
        (Jsonb(metadata | {"target_blog_id": "different"}),),
    )
    assert origin.classify(conn, version, blog)["kind"] == "unknown"


def test_wire_rechecks_real_quality_without_promoting_import(center):
    conn, _, _ = center
    job, blog, version = make_job(center, "scheduled_auto", "draft")
    enable(center, blog)
    link_trends(conn, version, blog)
    origin_grant(conn, job, version, controls.read(conn), blog)
    assert controls.job_permitted(conn, job)
    assert not controls.job_permitted(conn, job, running=True)
    reasons = conn.execute(
        "SELECT payload->'reasons' reasons FROM audit_events WHERE event_type='automation.origin_publication.blocked' ORDER BY id DESC LIMIT 1"
    ).fetchone()["reasons"]
    assert "quality_review_required" in reasons


def test_trends_wire_uses_trends_blockers_and_keeps_review_gaps_as_followups(center, monkeypatch):
    conn, _, _ = center
    job, blog, version = make_job(
        center, "scheduled_auto", "draft", method="codex_trends_export"
    )
    enable(center, blog)
    link_trends(conn, version, blog)
    origin_grant(conn, job, version, controls.read(conn), blog)
    monkeypatch.setattr(
        trends_publication,
        "validate_trends_job",
        lambda *_args: {"row": {"id": "linked"}, "assessment": {"followups": ["review gap"]}, "reasons": []},
    )
    monkeypatch.setattr(
        automation_auto,
        "readiness",
        lambda *_args: pytest.fail("Trends wire must use its Trends-specific policy"),
    )
    assert controls.job_permitted(conn, job, running=True)


def test_local_record_of_same_import_blocks_another_version_before_http(center):
    conn, _, _ = center
    job, blog, version = make_job(center, "scheduled_auto", "draft")
    enable(center, blog)
    link_trends(conn, version, blog)
    origin_grant(conn, job, version, controls.read(conn), blog)
    assert controls.job_permitted(conn, job)
    # A distinct historical job for the same imported article already has a remote record.
    previous = conn.execute(
        """INSERT INTO publishing_jobs(policy_id,blog_id,content_version_id,idempotency_key,scheduled_at,status,publication_state,adapter_type,simulation_only,oauth_connection_id,live_stage,remote_post_id)
        SELECT policy_id,blog_id,content_version_id,%s,now(),'succeeded','published','blogger_live',false,oauth_connection_id,'published','12345' FROM publishing_jobs WHERE id=%s RETURNING id""",
        (uuid4().hex, job),
    ).fetchone()["id"]
    conn.execute(
        """INSERT INTO publishing_records(job_id,blog_id,content_version_id,remote_post_id,remote_url,remote_status,remote_verified_at,published_at)
        VALUES(%s,%s,%s,'12345','https://example.blogspot.com/existing','LIVE',now(),now())""",
        (previous, blog, version),
    )
    assert not controls.job_permitted(conn, job)


def test_worker_ack_requires_new_publishing_engine(center):
    conn, api, h = center
    conn.execute(
        "INSERT INTO worker_heartbeats(service_name,process_id,status,last_seen_at) VALUES('publication_worker',104,'running',now()) ON CONFLICT(service_name) DO UPDATE SET process_id=104,status='running',last_seen_at=now()"
    )
    controls.acknowledge(conn, "publication_worker", 104)
    assert next(
        w
        for w in api.get(BASE, headers=h).json()["workers"]
        if w["service_name"] == "publication_worker"
    )["policy_applied"]
    conn.execute(
        "UPDATE automation_runtime_ack SET engine_version='automation-controls/1' WHERE service_name='publication_worker'"
    )
    assert not next(
        w
        for w in api.get(BASE, headers=h).json()["workers"]
        if w["service_name"] == "publication_worker"
    )["policy_applied"]
