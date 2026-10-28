"""Conservative trend grouping, rubric assessments, and source-linked research packages."""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from psycopg.types.json import Jsonb

from .ai import EngineFailure
from .db import connection

LOOKBACK_HOURS = 168
BROAD_QUERIES = {
    "tourism", "travel", "weather", "stock", "stocks", "관광", "여행", "날씨", "주식",
    "주가", "天气", "旅游", "旅行", "股票", "株価", "天気", "観光",
}
DEFAULT_WEIGHTS = {
    "source_interest_label": 15,
    "freshness": 15,
    "specificity": 20,
    "reviewed_source_coverage": 20,
    "independent_confirmation": 20,
    "deduplication_risk": 10,
}


def _current_scoring_config(conn: Any) -> dict[str, Any]:
    row = conn.execute(
        "SELECT version,weights,thresholds,rationale FROM trend_scoring_configs ORDER BY version DESC LIMIT 1"
    ).fetchone()
    if row is None:
        raise EngineFailure("trend_scoring_config_missing")
    weights = dict(row["weights"])
    thresholds = dict(row["thresholds"])
    if set(weights) != set(DEFAULT_WEIGHTS) or not math.isclose(sum(float(value) for value in weights.values()), 100):
        raise EngineFailure("trend_scoring_config_invalid")
    return {"version": row["version"], "weights": weights, "thresholds": thresholds, "rationale": row["rationale"]}


def normalize_query(value: str) -> str:
    folded = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.sub(r"[^\w]+", " ", folded, flags=re.UNICODE).split())


def _assert_schema(conn: Any) -> None:
    ready = conn.execute(
        "SELECT to_regclass('public.trend_topics') AS table_name"
    ).fetchone()
    if not ready or not ready["table_name"]:
        raise EngineFailure("trend_topic_schema_not_applied")


def _audit(conn: Any, event: str, **payload: Any) -> None:
    conn.execute(
        "INSERT INTO audit_events(event_type,payload) VALUES (%s,%s)",
        (event, Jsonb(payload)),
    )


def _propose_cross_geo_pairs(conn: Any, rows: list[dict[str, Any]]) -> int:
    proposals = 0
    by_geo: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_geo.setdefault(row["geo"], []).append(row)
    geos = sorted(by_geo)
    for index, left_geo in enumerate(geos):
        for right_geo in geos[index + 1 :]:
            for left in by_geo[left_geo]:
                lnorm = normalize_query(left["query"])
                for right in by_geo[right_geo]:
                    rnorm = normalize_query(right["query"])
                    ratio = SequenceMatcher(None, lnorm, rnorm).ratio()
                    ltokens, rtokens = set(lnorm.split()), set(rnorm.split())
                    shared = ltokens & rtokens
                    jaccard = len(shared) / max(1, len(ltokens | rtokens))
                    if lnorm == rnorm:
                        method, confidence = "same_query_cross_geo", 0.8
                        rationale = "Exact query text appears in different geographies; event identity is unverified."
                    elif shared and ratio >= 0.82 and jaccard >= 0.67:
                        method, confidence = "lexical_similarity", round(min(ratio, jaccard), 3)
                        rationale = "Lexical overlap proposes review only; it does not establish the same event."
                    else:
                        continue
                    a, b = sorted((left["id"], right["id"]))
                    inserted = conn.execute(
                        """INSERT INTO trend_grouping_proposals(observation_a,observation_b,method,
                        confidence,rationale) VALUES (%s,%s,%s,%s,%s)
                        ON CONFLICT(observation_a,observation_b,method) DO NOTHING RETURNING id""",
                        (a, b, method, confidence, rationale),
                    ).fetchone()
                    proposals += bool(inserted)
    return proposals


def _assess_topic(conn: Any, topic_id: UUID, run_id: UUID | None = None) -> dict[str, Any]:
    config = _current_scoring_config(conn)
    weights = config["weights"]
    thresholds = config["thresholds"]
    topic = conn.execute("SELECT * FROM trend_topics WHERE id=%s", (topic_id,)).fetchone()
    observations = conn.execute(
        """SELECT o.* FROM trend_topic_memberships m JOIN trend_observations o
        ON o.id=m.observation_id WHERE m.topic_id=%s ORDER BY o.collected_at DESC""",
        (topic_id,),
    ).fetchall()
    if not topic or not observations:
        raise EngineFailure("trend_topic_not_found")
    newest = observations[0]
    source_rows = conn.execute(
        """SELECT s.id,s.url,s.source_name,s.valid_until,sr.approved,
        (SELECT count(*) FROM evidence_facts f WHERE f.source_id=s.id
          AND f.verification_status='source_span_verified') AS verified_fact_count,
            (SELECT decision FROM trend_source_independence_reviews ir
          WHERE ir.topic_source_id=ts.id ORDER BY ir.created_at DESC LIMIT 1) AS independence_decision,
        (SELECT comparison_group FROM trend_source_independence_reviews ir
          WHERE ir.topic_source_id=ts.id ORDER BY ir.created_at DESC LIMIT 1) AS comparison_group
        FROM trend_topic_sources ts JOIN research_sources s ON s.id=ts.research_source_id
        JOIN LATERAL (SELECT approved FROM source_reviews r WHERE r.source_id=s.id
          ORDER BY review_sequence DESC LIMIT 1) sr ON true
        WHERE ts.topic_id=%s AND sr.approved AND s.valid_until>now()
        AND NOT EXISTS(SELECT 1 FROM research_sources n WHERE n.keyword_id=s.keyword_id
          AND n.url=s.url AND n.revision>s.revision)""",
        (topic_id,),
    ).fetchall()
    source_count = len(source_rows)
    fact_count = sum(int(row["verified_fact_count"]) for row in source_rows)
    independent_groups = {
        row["comparison_group"]
        for row in source_rows
        if row["independence_decision"] == "independent" and row["comparison_group"]
    }
    independent_count = len(independent_groups)
    age_hours = None
    if newest["trend_started_at"]:
        age_hours = max(
            0.0,
            (newest["collected_at"] - newest["trend_started_at"]).total_seconds() / 3600,
        )
    freshness = max(0.0, 1.0 - (age_hours / 24)) if age_hours is not None else 0.0
    key = normalize_query(topic["representative_query"])
    broad = key in BROAD_QUERIES
    token_count = len(key.split())
    specificity = 0.0 if broad else (0.55 if token_count <= 1 else 0.8 if token_count == 2 else 1.0)
    source_coverage = min(1.0, source_count / 2)
    independent_confirmation = min(1.0, independent_count / 2)
    proposals = conn.execute(
        """SELECT count(DISTINCT p.id) AS n FROM trend_grouping_proposals p
        JOIN trend_topic_memberships m ON m.observation_id IN(p.observation_a,p.observation_b)
        WHERE m.topic_id=%s AND p.status='human_review_required'
        AND NOT EXISTS(SELECT 1 FROM trend_grouping_reviews r WHERE r.proposal_id=p.id)""",
        (topic_id,),
    ).fetchone()["n"]
    dedup_safety = max(0.0, 1.0 - min(1.0, float(proposals) / 3))
    has_interest_label = any(item["source_volume_label"] for item in observations)
    interest_score = 1.0 if has_interest_label else 0.0
    signals = {
        "source_interest_label": {"value": has_interest_label, "raw": newest["source_volume_label"], "score": interest_score},
        "freshness": {"age_hours": age_hours, "score": freshness},
        "specificity": {"token_count": token_count, "broad_exact_match": broad, "score": specificity},
        "reviewed_source_coverage": {"current_approved_sources": source_count, "verified_facts": fact_count, "score": source_coverage},
        "independent_confirmation": {"human_reviewed_independent_groups": independent_count, "score": independent_confirmation},
        "deduplication_risk": {"open_grouping_proposals": int(proposals), "safety_score": dedup_safety},
        "reader_value": "human_review_required",
        "analysis_fit": "human_review_required",
        "rights_risk": "requires_source_specific_review",
    }
    components = {
        "source_interest_label": interest_score,
        "freshness": freshness,
        "specificity": specificity,
        "reviewed_source_coverage": source_coverage,
        "independent_confirmation": independent_confirmation,
        "deduplication_risk": dedup_safety,
    }
    score = round(sum(float(weights[name]) * components[name] for name in weights), 2)
    reasons: list[str] = []
    if broad:
        reasons.append("broad_query_requires_specific_event_or_official_data")
    if source_count == 0:
        reasons.append("no_current_reviewed_fact_source_linked")
    if fact_count < 3:
        reasons.append("fewer_than_three_source_span_verified_facts")
    if independent_count < 2:
        reasons.append("two_independent_sources_not_human_verified")
    if proposals:
        reasons.append("cross_geography_grouping_requires_human_review")
    if score < float(thresholds.get("minimum_score", 70)):
        reasons.append("below_configured_minimum_score")
    reasons.append("reader_value_and_analysis_fit_require_human_review")
    decision = "held" if (
        broad
        or source_count < int(thresholds.get("minimum_sources", 2))
        or fact_count < int(thresholds.get("minimum_verified_facts", 3))
        or independent_count < int(thresholds.get("minimum_independent_sources", 2))
        or score < float(thresholds.get("minimum_score", 70))
        or proposals > 0
    ) else "review_required"
    snapshot = {
        "topic_id": str(topic_id),
        "observation_ids": sorted(str(row["id"]) for row in observations),
        "source_ids": sorted(str(row["id"]) for row in source_rows),
        "verified_fact_count": fact_count,
        "independent_groups": sorted(independent_groups),
        "config_version": config["version"],
    }
    snapshot_sha = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
    row = conn.execute(
        """INSERT INTO trend_topic_assessments(topic_id,config_version,snapshot_sha256,score,
        decision,signals,reasons) VALUES (%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT(topic_id,config_version,snapshot_sha256) DO NOTHING RETURNING *""",
        (topic_id, config["version"], snapshot_sha, score, decision, Jsonb(signals), reasons),
    ).fetchone()
    inserted = row is not None
    if row is None:
        row = conn.execute(
            """SELECT * FROM trend_topic_assessments WHERE topic_id=%s AND config_version=%s
            AND snapshot_sha256=%s""",
            (topic_id, config["version"], snapshot_sha),
        ).fetchone()
    if inserted:
        _audit(
            conn,
            "trend.topic.assessed",
            topic_id=str(topic_id),
            run_id=str(run_id) if run_id else None,
            assessment_id=str(row["id"]),
            decision=decision,
            score=score,
            snapshot_sha256=snapshot_sha,
            config_version=config["version"],
        )
    return dict(row)


def build_candidates(lookback_hours: int = LOOKBACK_HOURS) -> dict[str, Any]:
    with connection() as conn:
        _assert_schema(conn)
        observations = conn.execute(
            """SELECT * FROM trend_observations WHERE collected_at>=now()-(%s*interval '1 hour')
            ORDER BY geo,lower(query),collected_at,id""",
            (lookback_hours,),
        ).fetchall()
        groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in observations:
            groups.setdefault((row["geo"], normalize_query(row["query"])), []).append(row)
        created = 0
        changed_topic_ids: list[UUID] = []
        for (geo, key), rows in groups.items():
            if not key:
                continue
            topic_id = uuid5(NAMESPACE_URL, f"woori-blog-trend-topic:{geo}:{key}")
            title = rows[-1]["query"]
            conn.execute(
                """INSERT INTO trend_topics(id,normalized_key,representative_geo,
                representative_query,source_language,grouping_method,grouping_confidence,grouping_status)
                VALUES (%s,%s,%s,%s,'und','same_query_same_geo',0.900,
                'exact_query_cluster_not_event_confirmed') ON CONFLICT(id) DO NOTHING""",
                (topic_id, key, geo, title),
            )
            changed_topic_ids.append(topic_id)
            for row in rows:
                inserted = conn.execute(
                    """INSERT INTO trend_topic_memberships(topic_id,observation_id,grouping_rationale)
                    VALUES (%s,%s,%s) ON CONFLICT(topic_id,observation_id) DO NOTHING RETURNING id""",
                    (topic_id, row["id"], "Exact normalized query and same source geography; event identity remains unconfirmed."),
                ).fetchone()
                created += bool(inserted)
        proposals = _propose_cross_geo_pairs(conn, [dict(row) for row in observations])
        unique_ids = sorted(set(changed_topic_ids), key=str)
        assessments = [_assess_topic(conn, topic_id) for topic_id in unique_ids]
        if created or proposals or assessments:
            _audit(
                conn,
                "trend.topics.built",
                observation_count=len(observations),
                topic_count=len(unique_ids),
                memberships_added=created,
                cross_geo_proposals_added=proposals,
                assessment_count=len(assessments),
                lookback_hours=lookback_hours,
                grouping_policy="exact_same_geo_only; cross_geo_never_auto_merged",
            )
        return {
            "observation_count": len(observations),
            "topic_count": len(unique_ids),
            "memberships_added": created,
            "grouping_proposals_added": proposals,
            "assessments": assessments,
        }


def state() -> dict[str, Any]:
    with connection() as conn:
        _assert_schema(conn)
        topics = conn.execute(
            """SELECT t.*,
            (SELECT row_to_json(a) FROM trend_topic_assessments a WHERE a.topic_id=t.id
              ORDER BY a.created_at DESC LIMIT 1) AS latest_assessment,
            (SELECT row_to_json(d) FROM trend_topic_editorial_decisions d WHERE d.topic_id=t.id
              ORDER BY d.created_at DESC LIMIT 1) AS latest_editorial_decision,
            (SELECT row_to_json(p) FROM trend_research_packages p WHERE p.topic_id=t.id
              ORDER BY p.package_version DESC LIMIT 1) AS latest_package,
            (SELECT array_agg(row_to_json(o) ORDER BY o.collected_at DESC)
              FROM trend_topic_memberships m JOIN trend_observations o ON o.id=m.observation_id
              WHERE m.topic_id=t.id) AS observations,
            (SELECT count(DISTINCT p.id) FROM trend_grouping_proposals p
              JOIN trend_topic_memberships m ON m.observation_id IN(p.observation_a,p.observation_b)
              WHERE m.topic_id=t.id) AS grouping_proposal_count
            FROM trend_topics t ORDER BY t.created_at DESC LIMIT 200"""
        ).fetchall()
        proposals = conn.execute(
            """SELECT p.*,
            (SELECT row_to_json(r) FROM trend_grouping_reviews r WHERE r.proposal_id=p.id
              ORDER BY r.created_at DESC LIMIT 1) AS latest_review,
            (SELECT row_to_json(a) FROM trend_observations a WHERE a.id=p.observation_a) AS left_observation,
            (SELECT row_to_json(b) FROM trend_observations b WHERE b.id=p.observation_b) AS right_observation
            FROM trend_grouping_proposals p ORDER BY p.created_at DESC LIMIT 200"""
        ).fetchall()
        packages = conn.execute(
            "SELECT id,topic_id,package_version,status,payload,verified_fact_count,independent_source_count,created_at FROM trend_research_packages ORDER BY created_at DESC LIMIT 100"
        ).fetchall()
        topic_sources = conn.execute(
            """SELECT ts.*,s.url,s.source_name,s.published_at,s.collected_at,s.is_primary,
            s.rights,s.access_policy,
            (SELECT approved FROM source_reviews r WHERE r.source_id=s.id ORDER BY r.review_sequence DESC LIMIT 1) AS latest_approved,
            (SELECT count(*) FROM evidence_facts f WHERE f.source_id=s.id AND f.verification_status='source_span_verified') AS verified_fact_count,
            (SELECT decision FROM trend_source_independence_reviews i WHERE i.topic_source_id=ts.id ORDER BY i.created_at DESC LIMIT 1) AS independence_decision,
            (SELECT comparison_group FROM trend_source_independence_reviews i WHERE i.topic_source_id=ts.id ORDER BY i.created_at DESC LIMIT 1) AS comparison_group
            FROM trend_topic_sources ts JOIN research_sources s ON s.id=ts.research_source_id
            ORDER BY ts.created_at DESC LIMIT 500"""
        ).fetchall()
        scoring_config = _current_scoring_config(conn)
    return {"topics": topics, "grouping_proposals": proposals, "research_packages": packages, "topic_sources": topic_sources, "scoring_config": scoring_config, "human_review_required": True}


def record_scoring_config(weights: dict[str, float], thresholds: dict[str, int | float], rationale: str) -> dict[str, Any]:
    if set(weights) != set(DEFAULT_WEIGHTS) or not math.isclose(sum(float(value) for value in weights.values()), 100):
        raise ValueError("trend_scoring_weights_must_sum_to_100")
    minimums = {"minimum_score": 70, "minimum_sources": 2, "minimum_verified_facts": 3, "minimum_independent_sources": 2}
    if set(thresholds) != set(minimums) or any(float(thresholds[key]) < minimum for key, minimum in minimums.items()):
        raise ValueError("trend_scoring_thresholds_cannot_relax_safety_gates")
    with connection() as conn:
        _assert_schema(conn)
        conn.execute("SELECT pg_advisory_xact_lock(771904)")
        version_row = conn.execute("SELECT coalesce(max(version),0)+1 AS n FROM trend_scoring_configs").fetchone()
        if version_row is None:
            raise EngineFailure("trend_scoring_config_version_unavailable")
        version = int(version_row["n"])
        row = conn.execute(
            """INSERT INTO trend_scoring_configs(version,weights,thresholds,rationale)
            VALUES (%s,%s,%s,%s) RETURNING *""",
            (version, Jsonb(weights), Jsonb(thresholds), rationale),
        ).fetchone()
        if row is None:
            raise EngineFailure("trend_scoring_config_insert_failed")
        _audit(conn, "trend.scoring_config.created", version=version, weights=weights, thresholds=thresholds, rationale=rationale)
        return dict(row)


def record_grouping_review(
    proposal_id: UUID,
    decision: str,
    event_group_id: UUID | None,
    reviewer: str,
    rationale: str,
    key: str,
) -> dict[str, Any]:
    if decision not in {"same_event", "different_event", "insufficient_information"}:
        raise ValueError("trend_group_review_decision_invalid")
    if (decision == "same_event") != (event_group_id is not None):
        raise ValueError("event_group_id_required_only_for_same_event")
    with connection() as conn:
        _assert_schema(conn)
        if not conn.execute(
            "SELECT 1 FROM trend_grouping_proposals WHERE id=%s", (proposal_id,)
        ).fetchone():
            raise EngineFailure("trend_grouping_proposal_not_found")
        row = conn.execute(
            """INSERT INTO trend_grouping_reviews(proposal_id,decision,event_group_id,reviewer,
            rationale,idempotency_key) VALUES (%s,%s,%s,%s,%s,%s)
            ON CONFLICT(idempotency_key) DO NOTHING RETURNING *""",
            (proposal_id, decision, event_group_id, reviewer, rationale, key),
        ).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT * FROM trend_grouping_reviews WHERE idempotency_key=%s", (key,)
            ).fetchone()
            if row is None:
                raise EngineFailure("trend_grouping_review_missing_after_conflict")
            actual = (row["proposal_id"], row["decision"], row["event_group_id"], row["reviewer"], row["rationale"])
            expected = (proposal_id, decision, event_group_id, reviewer, rationale)
            if actual != expected:
                raise EngineFailure("trend_grouping_review_idempotency_conflict")
        else:
            assert row is not None
            _audit(
                conn,
                "trend.topic.group_reviewed",
                proposal_id=str(proposal_id),
                decision=decision,
                event_group_id=str(event_group_id) if event_group_id else None,
                reviewer=reviewer,
                rationale=rationale,
            )
        return dict(row)


def record_editorial_decision(topic_id: UUID, decision: str, reviewer: str, reason: str, key: str) -> dict[str, Any]:
    if decision not in {"selected", "excluded", "hold"}:
        raise ValueError("trend_editorial_decision_invalid")
    with connection() as conn:
        _assert_schema(conn)
        if not conn.execute("SELECT 1 FROM trend_topics WHERE id=%s", (topic_id,)).fetchone():
            raise EngineFailure("trend_topic_not_found")
        row = conn.execute(
            """INSERT INTO trend_topic_editorial_decisions(topic_id,decision,reviewer,reason,idempotency_key)
            VALUES (%s,%s,%s,%s,%s) ON CONFLICT(idempotency_key) DO NOTHING RETURNING *""",
            (topic_id, decision, reviewer, reason, key),
        ).fetchone()
        if row is None:
            row = conn.execute("SELECT * FROM trend_topic_editorial_decisions WHERE idempotency_key=%s", (key,)).fetchone()
            if row is None:
                raise EngineFailure("trend_decision_missing_after_conflict")
            if row["topic_id"] != topic_id or row["decision"] != decision or row["reviewer"] != reviewer or row["reason"] != reason:
                raise EngineFailure("trend_decision_idempotency_conflict")
        else:
            assert row is not None
            _audit(conn, "trend.topic.editorial_decision", topic_id=str(topic_id), decision=decision, reviewer=reviewer, reason=reason)
        assert row is not None
        return dict(row)


def link_reviewed_source(topic_id: UUID, source_id: UUID, link_reason: str, linked_by: str, key: str) -> dict[str, Any]:
    with connection() as conn:
        _assert_schema(conn)
        source = conn.execute(
            """SELECT s.id,s.url,s.valid_until,s.rights,s.access_policy,s.is_primary,
            (SELECT approved FROM source_reviews r WHERE r.source_id=s.id ORDER BY r.review_sequence DESC LIMIT 1) approved,
            (SELECT count(*) FROM evidence_facts f WHERE f.source_id=s.id AND f.verification_status='source_span_verified') facts,
            NOT EXISTS(SELECT 1 FROM research_sources n WHERE n.keyword_id=s.keyword_id AND n.url=s.url AND n.revision>s.revision) current
            FROM research_sources s WHERE s.id=%s""",
            (source_id,),
        ).fetchone()
        now_row = conn.execute("SELECT now() AS now").fetchone()
        if now_row is None or source is None or not source["approved"] or not source["current"] or source["valid_until"] <= now_row["now"] or not source["facts"] or not source["rights"] or not source["access_policy"]:
            raise EngineFailure("current_reviewed_source_with_verified_facts_required")
        inserted = conn.execute(
            """INSERT INTO trend_topic_sources(topic_id,research_source_id,link_reason,linked_by,idempotency_key)
            VALUES (%s,%s,%s,%s,%s) ON CONFLICT(topic_id,research_source_id) DO NOTHING RETURNING *""",
            (topic_id, source_id, link_reason, linked_by, key),
        ).fetchone()
        if inserted:
            assert inserted is not None
            _audit(conn, "trend.topic.source_linked", topic_id=str(topic_id), source_id=str(source_id), linked_by=linked_by)
            return dict(inserted)
        existing = conn.execute("SELECT * FROM trend_topic_sources WHERE topic_id=%s AND research_source_id=%s", (topic_id, source_id)).fetchone()
        if existing is None:
            raise EngineFailure("trend_topic_source_missing_after_conflict")
        return dict(existing)


def record_independence_review(topic_source_id: UUID, decision: str, reviewer: str, reason: str, comparison_group: str | None, key: str) -> dict[str, Any]:
    with connection() as conn:
        _assert_schema(conn)
        if not conn.execute("SELECT 1 FROM trend_topic_sources WHERE id=%s", (topic_source_id,)).fetchone():
            raise EngineFailure("trend_topic_source_link_not_found")
        row = conn.execute(
            """INSERT INTO trend_source_independence_reviews(topic_source_id,decision,reviewer,reason,
            comparison_group,idempotency_key) VALUES (%s,%s,%s,%s,%s,%s)
            ON CONFLICT(idempotency_key) DO NOTHING RETURNING *""",
            (topic_source_id, decision, reviewer, reason, comparison_group, key),
        ).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT * FROM trend_source_independence_reviews WHERE idempotency_key=%s",
                (key,),
            ).fetchone()
            if row is None:
                raise EngineFailure("trend_independence_review_missing_after_conflict")
            if (row["topic_source_id"], row["decision"], row["reviewer"], row["reason"], row["comparison_group"]) != (topic_source_id, decision, reviewer, reason, comparison_group):
                raise EngineFailure("trend_independence_idempotency_conflict")
        else:
            assert row is not None
            _audit(conn, "trend.source.independence_reviewed", topic_source_id=str(topic_source_id), decision=decision, reviewer=reviewer, comparison_group=comparison_group)
        assert row is not None
        return dict(row)


def build_package(topic_id: UUID, run_id: UUID | None = None) -> dict[str, Any]:
    with connection() as conn:
        _assert_schema(conn)
        topic = conn.execute("SELECT * FROM trend_topics WHERE id=%s", (topic_id,)).fetchone()
        if topic is None:
            raise EngineFailure("trend_topic_not_found")
        assessment = _assess_topic(conn, topic_id, run_id)
        scoring_config = _current_scoring_config(conn)
        observations = conn.execute(
            """SELECT o.* FROM trend_topic_memberships m JOIN trend_observations o ON o.id=m.observation_id
            WHERE m.topic_id=%s ORDER BY o.collected_at""",
            (topic_id,),
        ).fetchall()
        confirmed_groups = conn.execute(
            """SELECT DISTINCT r.event_group_id FROM trend_grouping_reviews r
            JOIN trend_grouping_proposals p ON p.id=r.proposal_id
            WHERE r.decision='same_event' AND r.event_group_id IS NOT NULL
            AND (p.observation_a=ANY(%s) OR p.observation_b=ANY(%s))""",
            ([row["id"] for row in observations] or [UUID(int=0)], [row["id"] for row in observations] or [UUID(int=0)]),
        ).fetchall()
        event_group_ids = [row["event_group_id"] for row in confirmed_groups]
        if event_group_ids:
            linked_observation_ids = conn.execute(
                """SELECT DISTINCT unnest(ARRAY[p.observation_a,p.observation_b]) AS observation_id
                FROM trend_grouping_reviews r JOIN trend_grouping_proposals p ON p.id=r.proposal_id
                WHERE r.decision='same_event' AND r.event_group_id=ANY(%s)""",
                (event_group_ids,),
            ).fetchall()
            existing_observation_ids = {row["id"] for row in observations}
            extra_ids = [row["observation_id"] for row in linked_observation_ids if row["observation_id"] not in existing_observation_ids]
            if extra_ids:
                extras = conn.execute(
                    "SELECT * FROM trend_observations WHERE id=ANY(%s)", (extra_ids,)
                ).fetchall()
                observations = sorted([*observations, *extras], key=lambda row: (row["collected_at"], str(row["id"])))
        sources = conn.execute(
            """SELECT s.*,r.approved AS latest_approved,
            coalesce(nullif(r.source_language,'und'),s.source_language) AS reviewed_language,
            ts.id AS topic_source_link_id,
            (SELECT decision FROM trend_source_independence_reviews ir WHERE ir.topic_source_id=ts.id ORDER BY ir.created_at DESC LIMIT 1) AS independence_decision,
            (SELECT comparison_group FROM trend_source_independence_reviews ir WHERE ir.topic_source_id=ts.id ORDER BY ir.created_at DESC LIMIT 1) AS comparison_group
            FROM trend_topic_sources ts JOIN research_sources s ON s.id=ts.research_source_id
            LEFT JOIN LATERAL (SELECT approved,source_language FROM source_reviews sr WHERE sr.source_id=s.id ORDER BY review_sequence DESC LIMIT 1) r ON true
            WHERE ts.topic_id=%s ORDER BY s.collected_at,s.id""",
            (topic_id,),
        ).fetchall()
        source_ids = [row["id"] for row in sources]
        facts = conn.execute(
            """SELECT f.*,s.source_name,s.url,s.published_at,s.collected_at,s.rights,s.access_policy
            FROM evidence_facts f JOIN research_sources s ON s.id=f.source_id
            WHERE f.source_id=ANY(%s) AND f.verification_status='source_span_verified'
            ORDER BY s.published_at NULLS LAST,f.fact_key,f.id""",
            (source_ids or [UUID(int=0)],),
        ).fetchall()
        current_source_ids = {
            row["id"]
            for row in conn.execute(
                """SELECT s.id FROM research_sources s WHERE s.id=ANY(%s)
                AND s.valid_until>now() AND NOT EXISTS(SELECT 1 FROM research_sources n
                  WHERE n.keyword_id=s.keyword_id AND n.url=s.url AND n.revision>s.revision)""",
                (source_ids or [UUID(int=0)],),
            ).fetchall()
        }
        eligible_sources = [row for row in sources if row["latest_approved"] and row["id"] in current_source_ids and row["rights"] and row["access_policy"]]
        independent_groups = {row["comparison_group"] for row in eligible_sources if row["independence_decision"] == "independent" and row["comparison_group"]}
        verified_facts = [row for row in facts if any(s["id"] == row["source_id"] for s in eligible_sources)]
        key = normalize_query(topic["representative_query"])
        thresholds = scoring_config["thresholds"]
        sufficient = (
            assessment["decision"] == "review_required"
            and key not in BROAD_QUERIES
            and len(eligible_sources) >= int(thresholds.get("minimum_sources", 2))
            and len(independent_groups) >= int(thresholds.get("minimum_independent_sources", 2))
            and len(verified_facts) >= int(thresholds.get("minimum_verified_facts", 3))
        )
        evidence_collected = (
            key not in BROAD_QUERIES
            and len(eligible_sources) >= 1
            and len(verified_facts) >= int(thresholds.get("minimum_verified_facts", 3))
        )
        payload = {
            "topic_id": str(topic_id),
            "research_run_id": str(run_id) if run_id else None,
            "title": topic["representative_query"],
            "selection": {"decision": assessment["decision"], "score": float(assessment["score"]), "reason_codes": assessment["reasons"], "signals": assessment["signals"], "score_thresholds_unchanged": True, "human_editorial_approval": False},
            "source_language": topic["source_language"],
            "language_status": "not_supplied_by_trends_source",
            "geographies": sorted({row["geo"] for row in observations}),
            "human_reviewed_event_group_ids": [str(row["event_group_id"]) for row in confirmed_groups],
            "observations": [
                {"observation_id": str(row["id"]), "query": row["query"], "geo": row["geo"], "platform": row["platform"], "source_rank": row["source_rank"], "source_interest_label": row["source_volume_label"], "source_url": row["source_url"], "started_at": row["trend_started_at"].isoformat() if row["trend_started_at"] else None, "collected_at": row["collected_at"].isoformat()}
                for row in observations
            ],
            "core_facts": [
                {"fact_id": str(row["id"]), "source_id": str(row["source_id"]), "source_name": row["source_name"], "source_url": row["url"], "source_excerpt": row["source_excerpt"], "entity_ids": row["entity_ids"], "numeric_values": row["numeric_values"], "date_values": row["date_values"], "verification_status": row["verification_status"], "published_at": row["published_at"].isoformat() if row["published_at"] else None, "collected_at": row["collected_at"].isoformat()}
                for row in verified_facts
            ],
            "sources": [
                {"source_id": str(row["id"]), "source_name": row["source_name"], "url": row["url"], "publisher": row["source_name"], "source_language": row["reviewed_language"], "published_at": row["published_at"].isoformat() if row["published_at"] else None, "collected_at": row["collected_at"].isoformat(), "is_primary": row["is_primary"], "rights": row["rights"], "access_policy": row["access_policy"], "current_review_approved": bool(row["latest_approved"]), "independence_review": row["independence_decision"] or "unreviewed", "comparison_group": row["comparison_group"]}
                for row in sources
            ],
            "background": [{"fact_id": str(row["id"]), "source_id": str(row["source_id"]), "source_excerpt": row["source_excerpt"]} for row in verified_facts],
            "timeline": [{"date": row["date_values"], "source_id": str(row["source_id"]), "fact_id": str(row["id"])} for row in verified_facts if row["date_values"]],
            "source_conflicts": {"status": "human_review_required", "items": []},
            "analytical_angles": ["Explain only implications directly supported by the linked facts; label analysis separately from facts."],
            "unknowns": ["Trend ranking was not supplied.", "Trend RSS does not state query language.", "Cross-geography event identity is unconfirmed.", "Open topic-grouping proposals require human resolution.", "Source independence, rights exceptions, policy interpretation, and semantic support require human review."] + (["No current reviewed evidence source is linked."] if not eligible_sources else []),
            "prohibited_claims": ["Do not infer rank or numeric search volume from RSS order/labels.", "Do not add unsupported statistics, quotations, interviews, causes, forecasts, or first-hand experience.", "Do not claim independent corroboration until distinct-source independence has been reviewed.", "Do not generalize public-service salary examples to military pay unless the source explicitly supports it.", "Do not describe a proposed or budgeted adjustment as fully enacted or paid without current implementation evidence."],
            "recommended_outline": ["What the observed search signal says (with geography and collection time)", "Verified facts and source-linked context", "What the available evidence does not establish", "Cautious analysis questions for human editorial review", "References"],
            "verified_fact_count": len(verified_facts),
            "eligible_source_count": len(eligible_sources),
            "human_verified_independent_source_groups": len(independent_groups),
            "evidence_stage": "complete_source_spans_pending_human_review" if evidence_collected else "evidence_collection_incomplete",
            "generation_ready": False,
            "human_review_items": ["source independence", "cross-geography topic grouping", "source-specific rights exceptions", "interpretation and factual context", "reader value and analysis suitability"],
            "human_review_required": True,
            "publish_ready": False,
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        existing = conn.execute("SELECT * FROM trend_research_packages WHERE topic_id=%s AND payload_sha256=%s", (topic_id, digest)).fetchone()
        if existing is not None:
            return {**dict(existing), "payload": existing["payload"], "idempotent_replay": True}
        version_row = conn.execute("SELECT coalesce(max(package_version),0)+1 AS n FROM trend_research_packages WHERE topic_id=%s", (topic_id,)).fetchone()
        if version_row is None:
            raise EngineFailure("trend_research_package_version_unavailable")
        next_version = version_row["n"]
        status = "evidence_ready_for_human_review" if sufficient else "evidence_collected_pending_human_review" if evidence_collected else "insufficient_evidence"
        row = conn.execute(
            """INSERT INTO trend_research_packages(topic_id,package_version,status,payload,payload_sha256,
            source_ids,fact_ids,verified_fact_count,independent_source_count)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
            (topic_id, next_version, status, Jsonb(payload), digest, source_ids, [fact["id"] for fact in verified_facts], len(verified_facts), len(independent_groups)),
        ).fetchone()
        if row is None:
            raise EngineFailure("trend_research_package_insert_failed")
        _audit(conn, "trend.research_package.created", topic_id=str(topic_id), run_id=str(run_id) if run_id else None, package_id=str(row["id"]), package_version=next_version, status=status, source_count=len(eligible_sources), verified_fact_count=len(verified_facts), independence_reviewed_count=len(independent_groups), payload_sha256=digest)
        return {**dict(row), "idempotent_replay": False}
