from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from test_content_imports import valid_item
from test_pipeline import lab as shared_lab
from test_trend_editorial import observation
from woori import content_imports, keyword_jobs, trend_editorial, trends
from woori import editorial_intelligence as engine
from woori import editorial_quality as quality
from woori import editorial_scoring as scoring

lab = shared_lab
BASE = "/admin/research/editorial-intelligence"


@pytest.fixture
def editor(lab, monkeypatch):
    conn, api, h = lab

    @contextmanager
    def shared():
        with conn.transaction():
            yield conn

    for module in (content_imports, engine, keyword_jobs, trend_editorial, trends):
        monkeypatch.setattr(module, "connection", shared)
    return conn, api, h


def manuscript(editor, language="en"):
    _conn, api, h = editor
    sentence = "The agency described the scope of its proposed policy in the notice. "
    body = (
        "A reader guide separates the proposal from final decisions.\n\n## Background\n\n"
        + sentence * 3
        + "\n\n## Implications\n\n"
        + ("Readers should check which requirements apply to their circumstances. " * 3)
    )
    payload = valid_item(content_id=str(uuid4()), language_code=language, body_markdown=body)
    response = api.post(
        "/admin/research/content-imports",
        headers=h,
        json={"submitted_by": "isolated editorial test", "item": payload},
    )
    assert response.status_code == 201, response.text
    return response.json(), payload


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("  FED Meeting！ ", "fed meeting"),
        ("ＡＩ　モデル", "ai モデル"),
        ("ｶﾀｶﾅ", "カタカナ"),
        ("中国，政策", "中国 政策"),
        ("금리—정책", "금리 정책"),
    ],
)
def test_normalization_retains_original_semantics(a, b):
    assert scoring.normalize(a) == b


def test_homographs_dates_and_operator_scoped_aliases():
    aliases = [{"geo": "US", "alias": "Fed", "canonical": "Federal Reserve"}]
    assert (
        scoring.canonical_query("FED meeting 2026-11-01", "US", aliases)
        == "federal reserve meeting 2026 11 01"
    )
    assert scoring.canonical_query("FED meeting", "JP", aliases) == "fed meeting"
    assert scoring.normalize("銀行") != scoring.normalize("银行")
    assert scoring.normalize("2026-11-01") != scoring.normalize("2026-11-02")
    assert not scoring.overlap("Company earnings 2026 Q2", "Company earnings 2026 Q3")


@pytest.mark.parametrize(
    "weights",
    [
        {"news_value": 26},
        {"news_value": True},
        {"interest": -1},
        {"freshness": 101},
        {"unknown": 1},
    ],
)
def test_weight_validation(weights):
    with pytest.raises(ValueError):
        scoring.Weights.model_validate(weights)


def test_source_free_current_candidate_and_region_relative_interest():
    now = datetime.now(UTC)
    row = {
        "representative_query": "central bank interest rate decision",
        "trend_started_at": now,
        "source_volume_lower_bound": 500,
        "raw_payload": {},
    }
    original = deepcopy(row)
    result = scoring.score_candidate(row, [row], scoring.Weights(), now, [])
    assert result["decision"] == "selected" and result["components"]["interest"] == 100
    assert result["fact_verified"] is False and row == original
    assert (
        scoring.score_candidate(row, [row], scoring.Weights(), now, [{"type": "exact"}])["decision"]
        == "duplicate"
    )
    assert (
        scoring.score_candidate(
            {**row, "trend_started_at": now - timedelta(days=5)}, [row], scoring.Weights(), now, []
        )["decision"]
        == "low_value"
    )
    assert (
        scoring.score_candidate(
            {**row, "representative_query": "Unconfirmed death rumor"},
            [row],
            scoring.Weights(),
            now,
            [],
        )["decision"]
        == "high_risk"
    )


@pytest.mark.parametrize("language", ["ko", "en", "ja", "zh-CN", "fr"])
def test_static_never_invents_semantic_scores_or_source_verification(language):
    row = {
        "title": "A precise title",
        "body_markdown": "## Background\n\n" + "A paragraph. " * 80,
        "seo_metadata": {"search_description": "x" * 151},
        "blogger_labels": [],
    }
    result = quality.evaluate(
        row,
        {"language_code": language, "sources": [], "claims": [{"verification_status": "verified"}]},
    )
    assert result["scores"]["analysis"] is None and result["scores"]["localization"] is None
    assert result["overall_score"] is None and result["evidence"]["verified_claims"] is None
    assert not result["checks"]["meta_description"] and not result["checks"]["summary_deck"]
    assert result["human_review_required"] and result["evidence"]["source_count"] == 0


def test_static_detects_internal_notes_html_and_repetition():
    result = quality.evaluate(
        {
            "title": "短い",
            "body_markdown": "TODO publish_ready\n\n<script>bad</script>\n\n"
            + ("This sentence is repeated. " * 3),
            "seo_metadata": {},
            "blogger_labels": [],
        },
        {"language_code": "en"},
    )
    assert not result["checks"]["safe_html"] and not result["checks"]["internal_notes"]
    assert not result["checks"]["duplicate_sentences"]
    assert not quality.evaluate(
        {"title": "An HTML title", "body_markdown": "<h2>Unclosed heading", "seo_metadata": {}},
        {"language_code": "en"},
    )["checks"]["safe_html"]


def test_import_cache_partial_apply_comparison_and_stale_guard(editor):
    conn, api, h = editor
    before = conn.execute("SELECT count(*) n FROM publishing_jobs").fetchone()["n"]
    saved, payload = manuscript(editor)
    import_id = saved["import_id"]
    snapshot = conn.execute(
        "SELECT claims,sources FROM external_content_imports WHERE id=%s", (import_id,)
    ).fetchone()
    first = api.post(f"{BASE}/imports/{import_id}/evaluate", headers=h).json()
    assert first["cached"] is True
    second = api.post(f"{BASE}/imports/{import_id}/evaluate", headers=h).json()
    assert first["id"] == second["id"]
    suggestion = next(
        s for s in first["result"]["suggestions"] if s["field"] == "duplicate_sentence"
    )
    path = f"{BASE}/reports/{first['id']}/suggestions"
    request = {"suggestion_ids": [suggestion["id"]], "action": "apply"}
    assert api.post(path, headers=h, json=request).status_code == 409
    response = api.post(path, headers=h, json={**request, "explicit_confirmation": True})
    assert response.status_code == 200, response.text
    next_id = response.json()["new_version"]["version_id"]
    original = conn.execute(
        "SELECT body_markdown FROM external_content_import_versions WHERE id=%s",
        (first["import_version_id"],),
    ).fetchone()
    assert original["body_markdown"] == payload["body_markdown"].strip()
    diff = api.get(
        f"{BASE}/imports/{import_id}/compare",
        headers=h,
        params={"before": first["import_version_id"], "after": next_id},
    ).json()
    assert any(l.startswith("-") for l in diff["fields"]["body_markdown"]["diff"])
    assert (
        api.post(path, headers=h, json={**request, "explicit_confirmation": True}).status_code
        == 409
    )
    assert (
        conn.execute(
            "SELECT claims,sources FROM external_content_imports WHERE id=%s", (import_id,)
        ).fetchone()
        == snapshot
    )
    assert conn.execute("SELECT count(*) n FROM publishing_jobs").fetchone()["n"] == before
    # Machine results and human approval remain independent.
    assert response.json()["new_version"]["publish_ready"] is False


def test_ignore_review_and_unknown_suggestion(editor):
    _conn, api, h = editor
    saved, _ = manuscript(editor)
    report = api.post(f"{BASE}/imports/{saved['import_id']}/evaluate", headers=h).json()
    sid = report["result"]["suggestions"][0]["id"]
    for action in ("ignore", "review"):
        r = api.post(
            f"{BASE}/reports/{report['id']}/suggestions",
            headers=h,
            json={"suggestion_ids": [sid], "action": action},
        )
        assert r.status_code == 200 and r.json()["new_version"] is None
    assert (
        api.post(
            f"{BASE}/reports/{report['id']}/suggestions",
            headers=h,
            json={"suggestion_ids": ["missing"], "action": "apply"},
        ).status_code
        == 422
    )


def test_deep_failure_recovery_cache_and_one_shared_runner(editor, monkeypatch):
    conn, api, h = editor
    saved, payload = manuscript(editor)
    conn.execute(
        "UPDATE codex_authoring_jobs SET state='cancelled' WHERE state IN ('queued','researching','writing','validating')"
    )
    from woori import codex_runner

    calls = []

    def failed(*args, **kwargs):
        calls.append(1)
        raise codex_runner.CodexFailure("codex_timeout")

    monkeypatch.setattr(codex_runner, "execute", failed)
    endpoint = f"{BASE}/imports/{saved['import_id']}/deep-review"
    first = api.post(endpoint, headers=h)
    assert first.status_code == 200 and first.json()["status"] == "failed"

    def succeeded(*args, **kwargs):
        calls.append(1)
        assert kwargs["require_web_research"] is False
        return {
            "scores": {k: 75 for k in quality.WEIGHTS},
            "suggestions": [
                {
                    "category": "seo",
                    "original": payload["title"],
                    "proposal": "A clearer policy guide for readers",
                    "reason": "Clarifies the reader question without asserting new facts.",
                }
            ],
            "rationale": "Editorial opinions requiring human confirmation.",
        }, {"execution_id": "isolated-test"}

    monkeypatch.setattr(codex_runner, "execute", succeeded)
    second = api.post(endpoint, headers=h)
    assert second.status_code == 200 and second.json()["status"] == "completed", second.text
    assert api.post(endpoint, headers=h).json()["cached"] is True and len(calls) == 2
    report = second.json()
    path = f"{BASE}/reports/{report['id']}/suggestions"
    body = {"suggestion_ids": ["d1"], "action": "apply", "explicit_confirmation": True}
    assert api.post(path, headers=h, json=body).status_code == 409
    assert (
        api.post(path, headers=h, json={**body, "manual_review_confirmed": True}).status_code == 200
    )


def test_selection_history_weights_and_non_destructive_filtering(editor, monkeypatch):
    conn, api, h = editor
    blog = conn.execute("SELECT id FROM blogger_blogs WHERE active ORDER BY id LIMIT 1").fetchone()[
        "id"
    ]
    name = "central bank interest rate " + uuid4().hex
    obs = observation(conn, name, "US")
    trend_editorial.reconcile()
    topic = conn.execute(
        "SELECT topic_id FROM trend_topic_memberships WHERE observation_id=%s", (obs,)
    ).fetchone()["topic_id"]
    row = conn.execute(
        "SELECT t.*,o.id observation_id,o.geo,o.raw_payload,o.trend_started_at,o.source_volume_lower_bound,o.source_volume_label FROM trend_topics t JOIN trend_topic_memberships m ON m.topic_id=t.id JOIN trend_observations o ON o.id=m.observation_id WHERE t.id=%s",
        (topic,),
    ).fetchone()
    result = engine.rank_candidates(conn, [dict(row)], blog, trend_editorial.current_slot())
    assert result[0]["selection"]["decision"] == "selected"
    count = conn.execute("SELECT count(*) n FROM editorial_topic_scores").fetchone()["n"]
    assert (
        engine.rank_candidates(conn, [dict(row)], blog, trend_editorial.current_slot())[0][
            "selection"
        ]["score"]
        == result[0]["selection"]["score"]
    )
    assert conn.execute("SELECT count(*) n FROM editorial_topic_scores").fetchone()["n"] == count
    r = api.put(
        BASE + "/settings",
        headers=h,
        json={**scoring.Weights().model_dump(), "news_value": 30, "interest": 10},
    )
    assert r.status_code == 200 and datetime.fromisoformat(
        r.json()["effective_slot"]
    ) > datetime.now(UTC)
    assert (
        api.get(
            BASE + "/topics", headers=h, params={"q": name, "geo": "US", "decision": "selected"}
        ).json()["total"]
        == 1
    )
    assert (
        api.get(BASE + "/topics", headers=h, params={"q": name, "geo": "JP"}).json()["total"] == 0
    )
    assert api.get(BASE + "/monitor", headers=h).status_code == 200
    assert (
        conn.execute("SELECT query FROM trend_observations WHERE id=%s", (obs,)).fetchone()["query"]
        == name
    )


def test_new_tables_are_append_only(editor):
    conn, _api, _h = editor
    import psycopg

    with pytest.raises(psycopg.Error), conn.transaction():
        conn.execute("UPDATE editorial_selection_settings SET weights=weights")


def test_manual_proposal_requires_unique_exact_span():
    original = {
        "title": "Current title",
        "body_markdown": "Repeated text. Repeated text.",
        "seo_metadata": {},
    }
    suggestion = {
        "id": "d1",
        "field": "body_markdown",
        "original": "Repeated text.",
        "proposal": "Clearer wording.",
        "automatic": False,
    }
    with pytest.raises(ValueError, match="no_longer_matches"):
        quality.apply_suggestions(original, [suggestion], ["d1"], True)
    assert original["body_markdown"] == "Repeated text. Repeated text."


def test_deck_heading_and_embedded_title_are_recognized():
    body = "# Original title\n\n## Summary Deck\n\nA concise reader summary with sufficient context.\n\n## Background\n\nBackground details.\n\n## Implications\n\nReader impacts."
    r = quality.evaluate(
        {
            "title": "Original title",
            "body_markdown": body,
            "seo_metadata": {},
            "blogger_labels": [],
        },
        {"language_code": "en"},
    )
    assert r["checks"]["summary_deck"]
    bullets = body.replace(
        "A concise reader summary with sufficient context.",
        "- First concise summary for readers.\n- Second concise summary for readers.",
    )
    assert quality.evaluate(
        {"title": "Original title", "body_markdown": bullets, "seo_metadata": {}},
        {"language_code": "en"},
    )["checks"]["summary_deck"]


def test_semantic_proposal_numbers_are_bound_to_the_whole_manuscript():
    from woori.codex_runner import CodexFailure

    version = {
        "title": "A 2027 policy guide",
        "body_markdown": "Reader context.",
        "seo_metadata": {"search_description": "Policy guide."},
    }
    raw = {
        "scores": {k: 70 for k in quality.WEIGHTS},
        "rationale": "Editorial review.",
        "suggestions": [
            {
                "category": "seo",
                "original": "Policy guide.",
                "proposal": "Guide to 2027 policy.",
                "reason": "Preserves existing year.",
            }
        ],
    }
    assert engine.validate_review(raw, version).scores.seo == 70
    raw["suggestions"][0]["proposal"] = "Guide to 2030 policy."
    with pytest.raises(CodexFailure, match="unverified_number"):
        engine.validate_review(raw, version)


def test_retained_failed_response_can_be_rechecked_without_another_call(
    editor, monkeypatch, tmp_path
):
    import json

    from woori import codex_runner

    conn, api, h = editor
    saved, _payload = manuscript(editor)
    monkeypatch.setattr(keyword_jobs, "ROOT", tmp_path / "project")
    conn.execute(
        "UPDATE codex_authoring_jobs SET state='cancelled' WHERE state IN ('queued','researching','writing','validating')"
    )
    calls = []

    def interrupted(work, prompt, schema, callback, cancelled, **kwargs):
        calls.append(1)
        work.mkdir(parents=True)
        (work / "article.json").write_text(
            json.dumps(
                {
                    "scores": {k: 70 for k in quality.WEIGHTS},
                    "suggestions": [],
                    "rationale": "A retained editorial opinion.",
                }
            ),
            encoding="utf-8",
        )
        callback("researching", {"process_id": 123})
        raise codex_runner.CodexFailure("codex_timeout")

    monkeypatch.setattr(codex_runner, "execute", interrupted)
    failed = api.post(f"{BASE}/imports/{saved['import_id']}/deep-review", headers=h).json()
    assert failed["status"] == "failed" and failed["ai_calls"] == 1
    replay = api.post(f"{BASE}/reports/{failed['id']}/recheck", headers=h)
    assert replay.status_code == 200, replay.text
    assert replay.json()["status"] == "completed" and replay.json()["ai_calls"] == 0
    assert replay.json()["result"]["parent_report_id"] == failed["id"] and len(calls) == 1
    assert (
        conn.execute(
            "SELECT status FROM editorial_quality_reports WHERE id=%s", (failed["id"],)
        ).fetchone()["status"]
        == "failed"
    )


def test_same_name_new_event_requires_explicit_review_and_preserves_old_request(
    editor, monkeypatch
):
    conn, api, h = editor
    current = trend_editorial.current_slot()
    monkeypatch.setattr(trend_editorial, "current_slot", lambda: current - timedelta(minutes=10))
    name = "software launch " + uuid4().hex
    observed = observation(conn, name, "KR")
    trend_editorial.reconcile()
    topic = conn.execute(
        "SELECT topic_id FROM trend_topic_memberships WHERE observation_id=%s", (observed,)
    ).fetchone()["topic_id"]
    blog = conn.execute(
        "INSERT INTO blogger_blogs(language_code,url,display_name,blog_id) VALUES('ko',%s,'New event fixture','1234567928') RETURNING id",
        ("https://new-event-" + uuid4().hex[:8] + ".blogspot.com",),
    ).fetchone()["id"]
    conn.execute("UPDATE trend_blog_geo_authoring SET enabled=false WHERE geo='KR'")
    conn.execute(
        "INSERT INTO trend_blog_geo_authoring(blog_id,geo,enabled,processing_order) VALUES(%s,'KR',true,1)",
        (blog,),
    )
    monkeypatch.setattr(
        keyword_jobs,
        "targets",
        lambda _: [{"id": blog, "target_country": "KR", "language_code": "ko"}],
    )
    first = trend_editorial.queue_topic(conn, topic, blog)
    conn.execute("UPDATE trend_generation_requests SET state='failed' WHERE id=%s", (first["id"],))
    trend_editorial.transition(
        conn,
        topic,
        "failed",
        "insufficient_evidence",
        "Prior context did not support a draft.",
        "isolated_fixture",
    )
    monkeypatch.setattr(trend_editorial, "current_slot", lambda: current)
    observation(
        conn,
        name,
        "KR",
        payload={"news_items": [{"title": name + " announces a distinct product"}]},
    )
    trend_editorial.reconcile()
    trend_editorial.transition(
        conn,
        topic,
        "selected",
        "operator_select",
        "A new event needs a distinct review.",
        "authenticated_operator",
        category="technology",
    )
    endpoint = f"/admin/research/trend-editorial/topics/{topic}/decision"
    body = {
        "request_key": str(uuid4()),
        "action": "queue",
        "reason": "A distinct newly announced product is confirmed by the operator.",
        "blog_id": str(blog),
    }
    assert api.post(endpoint, headers=h, json=body).status_code == 409
    request = {**body, "new_event_confirmed": True}
    response = api.post(endpoint, headers=h, json=request)
    assert response.status_code == 200, response.text
    assert response.json()["contract"]["previous_request_ids"] == [str(first["id"])]
    assert api.post(endpoint, headers=h, json=request).json()["id"] == response.json()["id"]
    assert (
        conn.execute(
            "SELECT state FROM trend_generation_requests WHERE id=%s", (first["id"],)
        ).fetchone()["state"]
        == "failed"
    )
    assert (
        conn.execute(
            "SELECT count(*) n FROM trend_generation_requests WHERE topic_id=%s", (topic,)
        ).fetchone()["n"]
        == 2
    )
