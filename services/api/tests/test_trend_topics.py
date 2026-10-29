from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from psycopg.types.json import Jsonb
from test_pipeline import lab as shared_lab
from woori import topics

lab = shared_lab


def test_normalize_query_uses_unicode_compatibility_and_punctuation() -> None:
    assert topics.normalize_query("  ＧＯＯＧＬ   Stock! ") == "googl stock"
    assert topics.normalize_query("以色列，大選") == topics.normalize_query("以色列 大選")


def test_research_domains_select_supported_topics_only() -> None:
    assert topics.research_domains("fed meeting") == ["finance"]
    assert "artificial-intelligence" in topics.research_domains("生成式人工智能")
    assert topics.research_domains("weather") == []


@pytest.mark.parametrize("limit", [-1, 11, True, 1.5])
def test_research_candidate_hourly_limit_fails_closed(limit: Any) -> None:
    with pytest.raises(ValueError, match="trend_research_hourly_limit"):
        topics.select_research_candidates(limit)


def test_build_candidates_keeps_cross_geo_event_identity_unconfirmed(
    lab: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn, api, headers = lab

    @contextmanager
    def shared_connection() -> Any:
        with conn.transaction():
            yield conn

    monkeypatch.setattr(topics, "connection", shared_connection)
    now = datetime.now(UTC)
    query = "Synthetic election event " + uuid4().hex[:8]
    rows = []
    for geo in ("KR", "US"):
        run_id = uuid4()
        digest = (uuid4().hex * 2)[:64]
        conn.execute(
            """INSERT INTO trend_collection_runs(id,provider,geo,status,response_sha256,item_count)
            VALUES (%s,'google_trends_rss',%s,'succeeded',%s,1)""",
            (run_id, geo, digest),
        )
        row_id = uuid4()
        conn.execute(
            """INSERT INTO trend_observations(id,run_id,geo,platform,query,source_rank,
            source_volume_label,collected_at,source_url,response_sha256)
            VALUES (%s,%s,%s,'google_trends',%s,NULL,'1,000+',%s,%s,%s)""",
            (row_id, run_id, geo, query, now, f"https://trends.google.com/trending/rss?geo={geo}", digest),
        )
        rows.append((geo, row_id))

    built = topics.build_candidates(lookback_hours=1)
    assert built["observation_count"] >= 2
    assert built["topic_count"] >= 2
    assert built["grouping_proposals_added"] >= 1
    proposal = conn.execute(
        "SELECT * FROM trend_grouping_proposals WHERE observation_a=%s OR observation_b=%s",
        (rows[0][1], rows[0][1]),
    ).fetchone()
    assert proposal["status"] == "human_review_required"
    assert "event identity is unverified" in proposal["rationale"]

    topic_row = conn.execute(
        """SELECT t.id FROM trend_topics t JOIN trend_topic_memberships m ON m.topic_id=t.id
        WHERE m.observation_id=%s""",
        (rows[0][1],),
    ).fetchone()
    category_url = f"/admin/research/topics/{topic_row['id']}/categories"
    category_review = {
        "category_slug": "finance", "decision": "selected", "reviewer": "test editor",
        "rationale": "This issue has direct financial implications for the selected readers.",
        "idempotency_key": "topic-category-finance-" + uuid4().hex,
    }
    category_result = api.post(category_url, headers=headers, json=category_review)
    assert category_result.status_code == 201, category_result.text
    assert category_result.json()["publish_ready"] is False
    assert [item["category_slug"] for item in category_result.json()["categories"]] == ["finance"]
    replay = api.post(category_url, headers=headers, json=category_review)
    assert replay.status_code == 201 and replay.json()["duplicate"] is True
    category_review.update({
        "category_slug": "stocks", "rationale": "This event also changes a specific publicly traded company.",
        "idempotency_key": "topic-category-stocks-" + uuid4().hex,
    })
    stock_result = api.post(category_url, headers=headers, json=category_review)
    assert stock_result.status_code == 201, stock_result.text
    assert {item["category_slug"] for item in stock_result.json()["categories"]} == {"finance", "stocks"}
    package = api.post(
        f"/admin/research/topics/{topic_row['id']}/package", headers=headers
    )
    assert package.status_code == 201, package.text
    assert package.json()["status"] == "insufficient_evidence"
    assert package.json()["verified_fact_count"] == 0
    assert package.json()["payload"]["publish_ready"] is False

    state = api.get("/admin/research/topics", headers=headers)
    assert state.status_code == 200
    assert len(state.json()["topics"]) >= 2
    assert state.json()["grouping_proposals"]
    assert {item["slug"] for item in state.json()["categories"]} >= {"economy", "finance", "stocks", "crypto", "technology", "semiconductors", "artificial-intelligence", "policy"}
    proposal_id = str(proposal["id"])
    review_url = f"/admin/research/grouping-proposals/{proposal_id}/reviews"
    assert api.post(
        review_url,
        headers=headers,
        json={"decision": "same_event", "reviewer": "test reviewer", "rationale": "Missing event group must be rejected.", "idempotency_key": "group-review-missing-" + uuid4().hex},
    ).status_code == 422
    event_group_id = uuid4()
    review = {
        "decision": "same_event",
        "event_group_id": str(event_group_id),
        "reviewer": "test reviewer",
        "rationale": "Controlled fixture confirms the same synthetic event.",
        "idempotency_key": "group-review-" + uuid4().hex,
    }
    recorded = api.post(review_url, headers=headers, json=review)
    assert recorded.status_code == 201, recorded.text
    assert recorded.json()["event_group_id"] == str(event_group_id)
    assert api.post(review_url, headers=headers, json=review).json()["id"] == recorded.json()["id"]
    package = api.post(f"/admin/research/topics/{topic_row['id']}/package", headers=headers)
    assert package.status_code == 201, package.text
    assert str(event_group_id) in package.json()["payload"]["human_reviewed_event_group_ids"]
    assert set(package.json()["payload"]["geographies"]) == {"KR", "US"}


def test_broad_candidate_is_held_and_never_auto_selected(
    lab: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn, _, _ = lab

    @contextmanager
    def shared_connection() -> Any:
        with conn.transaction():
            yield conn

    monkeypatch.setattr(topics, "connection", shared_connection)
    run_id, observation_id = uuid4(), uuid4()
    digest = (uuid4().hex * 2)[:64]
    conn.execute(
        """INSERT INTO trend_collection_runs(id,provider,geo,status,response_sha256,item_count)
        VALUES (%s,'google_trends_rss','KR','succeeded',%s,1)""",
        (run_id, digest),
    )
    conn.execute(
        """INSERT INTO trend_observations(id,run_id,geo,platform,query,source_rank,
        source_volume_label,collected_at,source_url,response_sha256)
        VALUES (%s,%s,'KR','google_trends','관광',NULL,'10,000+',now(),
          'https://trends.google.com/trending/rss?geo=KR',%s)""",
        (observation_id, run_id, digest),
    )
    built = topics.build_candidates(lookback_hours=1)
    topic_id = conn.execute(
        "SELECT topic_id FROM trend_topic_memberships WHERE observation_id=%s",
        (observation_id,),
    ).fetchone()["topic_id"]
    assessment = conn.execute(
        "SELECT decision,reasons,score FROM trend_topic_assessments WHERE topic_id=%s",
        (topic_id,),
    ).fetchone()
    assert assessment["decision"] == "held"
    assert "broad_query_requires_specific_event_or_official_data" in assessment["reasons"]
    assert conn.execute(
        "SELECT count(*) AS n FROM trend_topic_editorial_decisions WHERE topic_id=%s",
        (topic_id,),
    ).fetchone()["n"] == 0
    assert built["topic_count"] >= 1


def test_package_requires_existing_current_reviewed_facts_and_source_independence(
    lab: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn, api, headers = lab

    @contextmanager
    def shared_connection() -> Any:
        with conn.transaction():
            yield conn

    monkeypatch.setattr(topics, "connection", shared_connection)
    run_id, observation_id = uuid4(), uuid4()
    digest = (uuid4().hex * 2)[:64]
    conn.execute(
        """INSERT INTO trend_collection_runs(id,provider,geo,status,response_sha256,item_count)
        VALUES (%s,'google_trends_rss','US','succeeded',%s,1)""",
        (run_id, digest),
    )
    conn.execute(
        """INSERT INTO trend_observations(id,run_id,geo,platform,query,source_rank,
        source_volume_label,collected_at,source_url,response_sha256)
        VALUES (%s,%s,'US','google_trends','Synthetic specific company event',NULL,'1,000+',now(),
          'https://trends.google.com/trending/rss?geo=US',%s)""",
        (observation_id, run_id, digest),
    )
    topics.build_candidates(lookback_hours=1)
    topic_id = conn.execute(
        "SELECT topic_id FROM trend_topic_memberships WHERE observation_id=%s",
        (observation_id,),
    ).fetchone()["topic_id"]
    profiles = conn.execute("SELECT id FROM language_profiles ORDER BY language_code LIMIT 1").fetchone()
    category = conn.execute("SELECT id FROM categories ORDER BY slug LIMIT 1").fetchone()
    keyword = conn.execute(
        """INSERT INTO keyword_candidates(profile_id,category_id,keyword,normalized_keyword,
        search_intent,collection_source,rationale,expires_at,priority)
        VALUES (%s,%s,%s,%s,'test intent','test source','isolated test source only',now()+interval '1 day',50)
        RETURNING id""",
        (profiles["id"], category["id"], "topic package " + uuid4().hex, "topic-package-" + uuid4().hex),
    ).fetchone()["id"]
    source_id = conn.execute(
        """INSERT INTO research_sources(keyword_id,url,source_name,collected_at,evidence,
        reliability_reason,rights,access_policy,valid_until,is_primary,revision,source_language)
        VALUES (%s,%s,'Synthetic official source',now(),'Exact synthetic evidence excerpt with a verified value 42.',
        'Synthetic fixture only','Test-owned fixture text','No outbound access; isolated test DB',now()+interval '1 day',true,1,'en') RETURNING id""",
        (keyword, f"https://example.invalid/{uuid4().hex}"),
    ).fetchone()["id"]
    conn.execute(
        "INSERT INTO source_reviews(source_id,approved,reason,reviewer,source_language) VALUES (%s,true,'synthetic test fixture only','test reviewer','en')",
        (source_id,),
    )
    conn.execute(
        """INSERT INTO evidence_facts(fact_key,source_id,source_language,source_excerpt,entity_ids,
        numeric_values,date_values,citation_ids,verification_status,extractor_version)
        VALUES (%s,%s,'en','Exact synthetic evidence excerpt with a verified value 42.',ARRAY[]::text[],
        %s,%s,%s,'source_span_verified','test-fixture')""",
        ("test-fact-" + uuid4().hex, source_id, Jsonb({"42": "42"}), Jsonb({}), [source_id]),
    )
    linked = api.post(
        f"/admin/research/topics/{topic_id}/sources",
        headers=headers,
        json={"source_id": str(source_id), "link_reason": "Synthetic fixture association for a guarded test.", "linked_by": "test reviewer", "idempotency_key": "test-source-link-" + uuid4().hex},
    )
    assert linked.status_code == 201, linked.text
    package = api.post(f"/admin/research/topics/{topic_id}/package", headers=headers)
    assert package.status_code == 201, package.text
    assert package.json()["status"] == "insufficient_evidence"
    assert package.json()["verified_fact_count"] == 1
    assert package.json()["payload"]["human_review_required"] is True


def test_scoring_policy_is_versioned_and_thresholds_cannot_be_relaxed(lab: Any) -> None:
    _conn, api, headers = lab
    request = {
        "weights": {
            "source_interest_label": 15,
            "freshness": 15,
            "specificity": 20,
            "reviewed_source_coverage": 20,
            "independent_confirmation": 20,
            "deduplication_risk": 10,
        },
        "thresholds": {
            "minimum_score": 85,
            "minimum_sources": 2,
            "minimum_verified_facts": 3,
            "minimum_independent_sources": 2,
        },
        "rationale": "Controlled test config demonstrates versioned, stricter threshold handling.",
    }
    created = api.post("/admin/research/topics/scoring-configs", headers=headers, json=request)
    assert created.status_code == 201, created.text
    assert created.json()["version"] == 2
    assert api.get("/admin/research/topics", headers=headers).json()["scoring_config"]["version"] == 2
    request["thresholds"]["minimum_score"] = 69
    assert api.post("/admin/research/topics/scoring-configs", headers=headers, json=request).status_code == 422


def test_complete_machine_evidence_stays_pending_human_review(lab: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    conn, _api, _headers = lab

    @contextmanager
    def shared_connection() -> Any:
        with conn.transaction():
            yield conn

    monkeypatch.setattr(topics, "connection", shared_connection)
    run_id, observation_id = uuid4(), uuid4()
    digest = (uuid4().hex * 2)[:64]
    conn.execute("INSERT INTO trend_collection_runs(id,provider,geo,status,response_sha256,item_count) VALUES (%s,'google_trends_rss','TW','succeeded',%s,1)", (run_id, digest))
    conn.execute("""INSERT INTO trend_observations(id,run_id,geo,platform,query,source_rank,source_volume_label,collected_at,source_url,response_sha256)
        VALUES (%s,%s,'TW','google_trends','Synthetic narrow policy event',NULL,'1,000+',now(),'https://trends.google.com/trending/rss?geo=TW',%s)""", (observation_id, run_id, digest))
    topics.build_candidates(lookback_hours=1)
    topic_id = conn.execute("SELECT topic_id FROM trend_topic_memberships WHERE observation_id=%s", (observation_id,)).fetchone()["topic_id"]
    profile = conn.execute("SELECT id FROM language_profiles WHERE language_code='en' LIMIT 1").fetchone()
    category = conn.execute("SELECT id FROM categories WHERE slug='finance'").fetchone()
    keyword_id = conn.execute("""INSERT INTO keyword_candidates(profile_id,category_id,keyword,normalized_keyword,search_intent,collection_source,rationale,expires_at,priority)
        VALUES (%s,%s,%s,%s,'source evidence test','official source fixture','Isolated fixture; source independence remains unreviewed.',now()+interval '1 day',50) RETURNING id""", (profile["id"], category["id"], "machine evidence " + uuid4().hex, "machine-evidence-" + uuid4().hex)).fetchone()["id"]
    source_ids = []
    for index in range(2):
        source_id = conn.execute("""INSERT INTO research_sources(keyword_id,url,source_name,collected_at,evidence,reliability_reason,rights,access_policy,valid_until,is_primary,revision,source_language)
            VALUES (%s,%s,%s,now(),%s,'Allowlisted test fixture','Test rights pending human review','Isolated test fixture only',now()+interval '1 day',true,1,'en') RETURNING id""", (keyword_id, f"https://example.invalid/{uuid4().hex}", f"Source {index}", f"Fact span {index} has verified value {index + 1}.\n")).fetchone()["id"]
        source_ids.append(source_id)
        conn.execute("INSERT INTO source_reviews(source_id,approved,reason,reviewer,source_language) VALUES (%s,true,'Machine provenance fixture only; human review remains pending.','collector:test-fixture','en')", (source_id,))
        conn.execute("INSERT INTO trend_topic_sources(topic_id,research_source_id,link_reason,linked_by,idempotency_key) VALUES (%s,%s,'Test evidence link','collector:test-fixture',%s)", (topic_id, source_id, "machine-link-" + uuid4().hex))
        conn.execute("""INSERT INTO evidence_facts(fact_key,source_id,source_language,source_excerpt,entity_ids,numeric_values,date_values,citation_ids,verification_status,extractor_version)
            VALUES (%s,%s,'en',%s,'{}',%s,'[]',%s,'source_span_verified','test-span')""", ("machine-fact-" + uuid4().hex, source_id, f"Fact span {index} has verified value {index + 1}.", Jsonb({str(index + 1): str(index + 1)}), [source_id]))
    conn.execute("""INSERT INTO evidence_facts(fact_key,source_id,source_language,source_excerpt,entity_ids,numeric_values,date_values,citation_ids,verification_status,extractor_version)
        VALUES (%s,%s,'en','A third exact source span records a verified policy date.','{}','[]','[]',%s,'source_span_verified','test-span')""", ("machine-fact-" + uuid4().hex, source_ids[0], [source_ids[0]]))
    package = topics.build_package(topic_id)
    assert package["status"] == "evidence_collected_pending_human_review"
    assert package["verified_fact_count"] == 3
    assert package["independent_source_count"] == 0
    assert package["payload"]["human_review_required"] is True
    assert package["payload"]["generation_ready"] is False
    assert package["payload"]["publish_ready"] is False
