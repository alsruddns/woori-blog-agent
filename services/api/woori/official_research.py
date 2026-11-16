"""Bounded, allowlisted discovery and capture of Taiwan government documents."""

from __future__ import annotations

import hashlib
import re
import time
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from typing import Any
from urllib.robotparser import RobotFileParser
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from . import topics
from .ai import EngineFailure
from .db import connection
from .external_policy import client as external_client
from .external_policy import external_run
from .localization import fact_ledger

USER_AGENT = "WooriBlogAgent/0.3.5 (bounded official-source research)"
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_DOCUMENTS_PER_RUN = 3


class _VisibleText(HTMLParser):
    """Extract readable text blocks and ignore executable/navigation markup."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.block_depth = 0
        self.buffer: list[str] = []
        self.blocks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg", "nav", "header", "footer", "aside"}:
            self.skip_depth += 1
        elif not self.skip_depth and tag in {"h1", "h2", "h3", "p", "li", "tr"}:
            self.block_depth += 1
            self.buffer.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg", "nav", "header", "footer", "aside"}:
            self.skip_depth = max(0, self.skip_depth - 1)
        elif not self.skip_depth and tag in {"h1", "h2", "h3", "p", "li", "tr"}:
            self.buffer.append("\n")
            self.block_depth = max(0, self.block_depth - 1)

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.buffer.append(data)

    def text(self) -> str:
        return "\n".join(
            " ".join(part.split()) for part in "".join(self.buffer).splitlines() if part.strip()
        )


# This is a reviewable local source catalog, not a search-engine result list.
# Candidate URLs are exact official records verified for the observed TW query.
CATALOG: tuple[dict[str, Any], ...] = (
    {
        "key": "ey-pay-plan-2026-07-02",
        "host": "www.ey.gov.tw",
        "url": "https://www.ey.gov.tw/Page/448DE008087A1971/5020ed44-2196-4da0-9dbe-fe6ae7f44afc",
        "source_name": "Executive Yuan — 116年度軍公教員工待遇提升方案",
        "published_at": datetime(2026, 7, 2, tzinfo=UTC),
        "markers": (
            ("2,000元", "4％"),
            ("追加預算", "115年7月1日"),
            ("9.98％", "5.88％"),
        ),
        "comparison_group": "taiwan-government-pay-proposal",
    },
    {
        "key": "ey-supplementary-budget-2026-09-03",
        "host": "www.ey.gov.tw",
        "url": "https://www.ey.gov.tw/Page/9277F759E41CCD91/e6b90fcf-0d42-40e3-b001-1c790c076657",
        "source_name": "Executive Yuan — 115年度中央政府總預算追加預算案",
        "published_at": datetime(2026, 9, 3, tzinfo=UTC),
        "markers": (
            ("6,076億元", "立法院審議"),
            ("軍公教人員專業加給", "107億元"),
        ),
        "comparison_group": "taiwan-government-pay-proposal",
    },
    {
        "key": "ly-supplementary-budget-review-2026-09",
        "host": "www.ly.gov.tw",
        "url": "https://www.ly.gov.tw/Pages/List.aspx?nodeid=56728",
        "source_name": "Legislative Yuan Budget Center — 115年度中央政府總預算追加預算案評估報告",
        "published_at": None,
        "markers": (
            ("軍公教人員待遇調整", "明確法制", "客觀量化基準"),
            ("追加預算案係於9月提出",),
            ("尚無法定預算數",),
        ),
        "comparison_group": "taiwan-legislative-budget-review",
    },
)
RIGHTS_URLS = {
    "www.ey.gov.tw": "https://www.ey.gov.tw/Page/2EADDBFEDDB6357E",
    "www.ly.gov.tw": "https://www.ly.gov.tw/Pages/List.aspx?nodeid=10772",
}


class OfficialResearchBlocked(EngineFailure):
    pass


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def _typed_fact(fact: dict[str, Any]) -> dict[str, Any]:
    """Add deterministic ROC-calendar conversion while preserving source text."""
    dates = set(fact["date_values"])
    for match in re.finditer(r"(?<!\d)(\d{2,3})年(\d{1,2})月(\d{1,2})日", fact["source_excerpt"]):
        year, month, day = (int(value) for value in match.groups())
        try:
            dates.add(f"DATE:{datetime(year + 1911, month, day, tzinfo=UTC):%Y-%m-%d}")
        except ValueError:
            continue
    return {**fact, "date_values": sorted(dates)}


def _fetch(url: str, *, expect_html: bool = True) -> tuple[bytes, int]:
    with external_client(
        "taiwan_official_documents",
        "source_collection",
        timeout=15,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
    ) as client:
        started = time.monotonic()
        with client.stream("GET", url) as response:
            if response.status_code == 429:
                raise OfficialResearchBlocked("official_source_quota_stopped")
            if response.status_code != 200:
                raise OfficialResearchBlocked("official_source_http_error")
            content_type = response.headers.get("content-type", "").casefold()
            if expect_html and "html" not in content_type:
                raise OfficialResearchBlocked("official_source_not_html")
            content = bytearray()
            for chunk in response.iter_bytes(65536):
                content.extend(chunk)
                if len(content) > MAX_RESPONSE_BYTES or time.monotonic() - started > 20:
                    raise OfficialResearchBlocked("official_source_response_limit")
            return bytes(content), response.status_code


def _check_robots(host: str, document_url: str) -> str:
    robots_url = f"https://{host}/robots.txt"
    content, status = _fetch(robots_url, expect_html=False)
    if status != 200:
        raise OfficialResearchBlocked("robots_policy_unavailable")
    parser = RobotFileParser(robots_url)
    parser.parse(content.decode("utf-8", errors="replace").splitlines())
    if not parser.can_fetch(USER_AGENT, document_url):
        raise OfficialResearchBlocked("robots_disallows_document")
    return hashlib.sha256(content).hexdigest()


def _read_rights(host: str) -> tuple[str, str, str]:
    url = RIGHTS_URLS[host]
    robots_sha256 = _check_robots(host, url)
    body, _ = _fetch(url)
    parser = _VisibleText()
    parser.feed(body.decode("utf-8", errors="replace"))
    text = parser.text()
    compact = _compact(text)
    required = ("無償", "重製", "公開傳輸")
    if not all(_compact(item) in compact for item in required):
        raise OfficialResearchBlocked("official_reuse_terms_not_verified")
    if "註明出處" not in text and "應註明出處" not in text:
        raise OfficialResearchBlocked("attribution_term_not_verified")
    return url, hashlib.sha256(body).hexdigest(), robots_sha256


def _sentence_spans(text: str, markers: tuple[tuple[str, ...], ...]) -> list[str]:
    sentences = [part.strip() for part in re.split(r"(?<=[。！？；])\s*|\n+", text) if part.strip()]
    spans: list[str] = []
    for group in markers:
        match = next(
            (
                sentence
                for sentence in sentences
                if all(_compact(marker) in _compact(sentence) for marker in group)
            ),
            None,
        )
        if match is None:
            raise OfficialResearchBlocked("required_source_fact_span_not_found")
        if len(match) > 900:
            raise OfficialResearchBlocked("source_fact_span_too_long_for_review")
        if match not in spans:
            spans.append(match)
    return spans


def _capture_document(
    entry: dict[str, Any], rights_evidence: str, robots_sha256: str
) -> dict[str, Any]:
    body, status = _fetch(entry["url"])
    visible = _VisibleText()
    visible.feed(body.decode("utf-8", errors="replace"))
    page_text = visible.text()
    spans = _sentence_spans(page_text, entry["markers"])
    normalized_page = _compact(page_text)
    if any(_compact(span) not in normalized_page for span in spans):
        raise OfficialResearchBlocked("source_span_not_present_in_document")
    if len("\n".join(spans)) > 1000:
        raise OfficialResearchBlocked("source_evidence_size_limit")
    digest = hashlib.sha256(body).hexdigest()
    return {
        **entry,
        "http_status": status,
        "body_sha256": digest,
        "robots_sha256": robots_sha256,
        "spans": spans,
        "evidence": "\n".join(spans),
        "rights_url": rights_evidence,
        "rights": "Official website reuse notice allows no-charge reuse, reproduction, modification and public transmission with attribution; third-party and specially restricted works are excluded. Human source-rights confirmation remains required.",
        "access_policy": "Fixed allowlisted HTTPS page; robots.txt checked; one bounded 1 MiB GET; redirects, authentication and retries disabled; cite the official page.",
    }


def _source_anchor(conn: Any, topic_id: UUID) -> tuple[UUID, UUID]:
    profile = conn.execute(
        "SELECT id FROM language_profiles WHERE language_code='en' AND target_country='' LIMIT 1"
    ).fetchone()
    category = conn.execute("SELECT id FROM categories WHERE slug='finance'").fetchone()
    if not profile or not category:
        raise OfficialResearchBlocked("research_source_anchor_unavailable")
    keyword = "Taiwan military and civil-servant compensation proposal"
    normalized = re.sub(r"\s+", " ", keyword.casefold()).strip()
    row = conn.execute(
        """INSERT INTO keyword_candidates(profile_id,category_id,keyword,normalized_keyword,
        search_intent,collection_source,rationale,expires_at,priority,status)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,65,'candidate')
        ON CONFLICT(profile_id,normalized_keyword) DO NOTHING RETURNING id""",
        (
            profile["id"],
            category["id"],
            keyword,
            normalized,
            "Research anchor only; original Google Trends query language was not supplied.",
            "google_trends_rss → taiwan_official_documents",
            f"Anchor for TW trend topic {topic_id}; does not assert source query language or rank.",
            datetime.now(UTC) + timedelta(days=30),
        ),
    ).fetchone()
    if row:
        keyword_id = row["id"]
    else:
        keyword_id = conn.execute(
            "SELECT id FROM keyword_candidates WHERE profile_id=%s AND normalized_keyword=%s",
            (profile["id"], normalized),
        ).fetchone()["id"]
    return keyword_id, profile["id"]


def _persist_source(conn: Any, topic_id: UUID, keyword_id: UUID, document: dict[str, Any], run_id: UUID) -> UUID:
    existing = conn.execute(
        "SELECT * FROM research_sources WHERE keyword_id=%s AND url=%s ORDER BY revision DESC LIMIT 1",
        (keyword_id, document["url"]),
    ).fetchone()
    if (
        existing
        and existing["evidence"] == document["evidence"]
        and existing["valid_until"] > datetime.now(UTC)
    ):
        if not isinstance(existing["id"], UUID):
            raise EngineFailure("official_source_identity_invalid")
        source_id = existing["id"]
    else:
        revision = conn.execute(
            "SELECT coalesce(max(revision),0)+1 AS n FROM research_sources WHERE keyword_id=%s AND url=%s",
            (keyword_id, document["url"]),
        ).fetchone()["n"]
        source = conn.execute(
            """INSERT INTO research_sources(keyword_id,url,source_name,published_at,collected_at,evidence,
            reliability_reason,rights,access_policy,valid_until,is_primary,revision,source_language)
            VALUES (%s,%s,%s,%s,now(),%s,%s,%s,%s,%s,true,%s,'zh-TW') RETURNING id""",
            (
                keyword_id,
                document["url"],
                document["source_name"],
                document["published_at"],
                document["evidence"],
                f"Allowlisted official publisher; live HTTP {document['http_status']}; source body SHA-256 {document['body_sha256']}; robots policy SHA-256 {document['robots_sha256']}.",
                document["rights"],
                f"{document['access_policy']} Rights notice: {document['rights_url']}.",
                datetime.now(UTC) + timedelta(days=30),
                revision,
            ),
        ).fetchone()
        if source is None or not isinstance(source.get("id"), UUID):
            raise EngineFailure("official_source_persistence_failed")
        source_id = source["id"]
        conn.execute(
            """INSERT INTO source_reviews(source_id,approved,reason,reviewer,source_language)
            VALUES (%s,true,%s,'collector:taiwan_official_documents','zh-TW')""",
            (
                source_id,
                "Automated provenance screen only: exact official-host allowlist, robots permission, current reuse notice, successful bounded GET and source-span presence checked. Not a human semantic, independence, or publication approval.",
            ),
        )
    for raw_fact in fact_ledger(
        {"id": source_id, "source_language": "zh-TW", "evidence": document["evidence"]}
    ):
        fact = _typed_fact(raw_fact)
        conn.execute(
            """INSERT INTO evidence_facts(fact_key,source_id,source_language,source_excerpt,
            entity_ids,numeric_values,date_values,citation_ids,verification_status,extractor_version)
            VALUES (%s,%s,'zh-TW',%s,%s,%s,%s,ARRAY[%s]::uuid[],'source_span_verified',%s)
            ON CONFLICT(source_id,fact_key,extractor_version) DO NOTHING""",
            (
                fact["fact_key"],
                source_id,
                fact["source_excerpt"],
                fact["entity_ids"],
                Jsonb(fact["numeric_values"]),
                Jsonb(fact["date_values"]),
                source_id,
                fact["extractor_version"],
            ),
        )
    link = conn.execute(
        """INSERT INTO trend_topic_sources(topic_id,research_source_id,link_reason,linked_by,idempotency_key)
        VALUES (%s,%s,%s,'collector:taiwan_official_documents',%s)
        ON CONFLICT(topic_id,research_source_id) DO NOTHING RETURNING id""",
        (
            topic_id,
            source_id,
            "Curated official source catalog matched the TW Google Trends query and the document contains exact topic-specific spans; event and source independence remain human-review items.",
            f"official-source:{topic_id}:{document['key']}",
        ),
    ).fetchone()
    if link is None:
        link = conn.execute(
            "SELECT id FROM trend_topic_sources WHERE topic_id=%s AND research_source_id=%s",
            (topic_id, source_id),
        ).fetchone()
    topics._audit(
        conn,
        "trend.official_source.captured",
        topic_id=str(topic_id),
        run_id=str(run_id),
        source_id=str(source_id),
        source_key=document["key"],
        host=document["host"],
        http_status=document["http_status"],
        body_sha256=document["body_sha256"],
        fact_span_count=len(document["spans"]),
        independence_review="pending_human_review",
    )
    if not isinstance(source_id, UUID):
        raise EngineFailure("official_source_identity_invalid")
    return source_id


def discover_for_topic(topic_id: UUID) -> dict[str, Any]:
    """Match an exact configured trend, safely retrieve official records, and persist spans."""
    with connection() as conn:
        topics._assert_schema(conn)
        topic = conn.execute(
            """SELECT t.id,t.representative_geo,t.representative_query FROM trend_topics t
            WHERE t.id=%s""",
            (topic_id,),
        ).fetchone()
        if topic is None:
            raise OfficialResearchBlocked("trend_topic_not_found")
        if (
            topic["representative_geo"] != "TW"
            or "".join(topic["representative_query"].split()) != "國軍加薪"
        ):
            raise OfficialResearchBlocked("no_curated_official_source_match")
    documents: list[dict[str, Any]] = []
    source_ids: list[UUID] = []
    run_id = uuid4()
    rights: dict[str, tuple[str, str, str]] = {}
    current_source_key = "rights_policy"
    with connection() as conn:
        topics._audit(
            conn,
            "trend.official_source_discovery.started",
            topic_id=str(topic_id),
            run_id=str(run_id),
            provider="taiwan_official_documents",
            maximum_documents=MAX_DOCUMENTS_PER_RUN,
            human_review_required=True,
            publish_ready=False,
        )
    try:
        with external_run(str(run_id)):
            for entry in CATALOG[:MAX_DOCUMENTS_PER_RUN]:
                current_source_key = entry["key"]
                host = entry["host"]
                if host not in rights:
                    rights[host] = _read_rights(host)
                document = _capture_document(entry, rights[host][0], rights[host][2])
                documents.append(document)
                with connection() as conn:
                    keyword_id, _ = _source_anchor(conn, topic_id)
                    source_ids.append(_persist_source(conn, topic_id, keyword_id, document, run_id))
    except Exception as exc:
        partial_package: dict[str, Any] | None = None
        if source_ids:
            try:
                partial_package = topics.build_package(topic_id, run_id)
            except (EngineFailure, psycopg.Error):
                partial_package = None
        with connection() as conn:
            topics._audit(
                conn,
                "trend.official_source_discovery.failed",
                topic_id=str(topic_id),
                run_id=str(run_id),
                provider="taiwan_official_documents",
                source_key=current_source_key,
                error_code=str(exc)
                if isinstance(exc, OfficialResearchBlocked)
                else type(exc).__name__,
                fully_captured_documents=len(documents),
                persisted_source_ids=[str(value) for value in source_ids],
                partial_package_id=str(partial_package["id"]) if partial_package else None,
                partial_package_status=partial_package["status"] if partial_package else None,
                human_review_required=True,
                publish_ready=False,
            )
        raise
    with connection() as conn:
        conn.execute(
            "INSERT INTO audit_events(event_type,payload) VALUES (%s,%s)",
            (
                "trend.official_source_discovery.completed",
                Jsonb(
                    {
                        "topic_id": str(topic_id),
                        "run_id": str(run_id),
                        "provider": "taiwan_official_documents",
                        "source_ids": [str(value) for value in source_ids],
                        "document_count": len(source_ids),
                        "rights_hosts": sorted(rights),
                        "source_independence": "unreviewed",
                        "human_review_required": True,
                        "publish_ready": False,
                    }
                ),
            ),
        )
    package = topics.build_package(topic_id, run_id)
    return {
        "topic_id": str(topic_id),
        "run_id": str(run_id),
        "discovered_documents": [
            {
                "key": item["key"],
                "source_name": item["source_name"],
                "url": item["url"],
                "published_at": item["published_at"].isoformat() if item["published_at"] else None,
                "http_status": item["http_status"],
                "source_body_sha256": item["body_sha256"],
                "fact_span_count": len(item["spans"]),
            }
            for item in documents
        ],
        "package": package,
        "human_review_required": True,
        "publish_ready": False,
    }
