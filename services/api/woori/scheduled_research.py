"""Fixed, zero-cost source collection for Local Codex Scheduled authoring.

The broker is a narrow research adapter, not a general URL fetcher or an AI
provider. It reuses the collection response bounds and the shared outbound
policy, then stores immutable, source-linked packages for the scheduled task.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb

from . import collection
from .db import connection
from .external_policy import client as external_client
from .external_policy import external_run

ROOT = Path(__file__).resolve().parents[3]
PACKAGE_DIR = ROOT / ".local" / "gpt-scheduled-import" / "research-packages"
MAX_ITEMS = 3
MAX_TOPIC_CHARS = 240
MAX_AGE_DAYS = 14
CODEX_RESEARCH_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["sources"],
    "properties": {
        "sources": {
            "type": "array", "maxItems": MAX_ITEMS,
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["title", "publisher", "url", "published_at", "event_date", "evidence_excerpt"],
                "properties": {
                    "title": {"type": "string", "minLength": 5, "maxLength": 300},
                    "publisher": {"type": "string", "minLength": 2, "maxLength": 160},
                    "url": {"type": "string", "format": "uri", "maxLength": 2048},
                    "published_at": {"type": "string", "minLength": 10, "maxLength": 80},
                    "event_date": {"type": ["string", "null"], "maxLength": 80},
                    "evidence_excerpt": {"type": "string", "minLength": 30, "maxLength": 700},
                },
            },
        },
    },
}

FEEDS: dict[str, tuple[dict[str, str], ...]] = {
    "politics": (
        {
            "provider": "whitehouse_public_news",
            "url": "https://www.whitehouse.gov/news/feed/",
            "publisher": "The White House",
            "rights": "Government-produced material is not copyright protected under the White House copyright policy; exclude or separately review third-party content and attribute the White House.",
            "rights_url": "https://www.whitehouse.gov/copyright/",
            "language": "en",
        },
    ),
    "economy": (
        {
            "provider": "bls_public_rss",
            "url": "https://www.bls.gov/feed/bls_latest.rss",
            "publisher": "U.S. Bureau of Labor Statistics",
            "rights": "U.S. federal government source; cite BLS and exclude third-party material, images and tables unless separately reviewed.",
            "rights_url": "https://www.bls.gov/",
            "language": "en",
        },
        {
            "provider": "federal_reserve",
            "url": "https://www.federalreserve.gov/feeds/press_all.xml",
            "publisher": "Federal Reserve Board",
            "rights": "Board-authored text may be public domain under its disclaimer; cite the Board and exclude third-party material.",
            "rights_url": "https://www.federalreserve.gov/disclaimer.htm",
            "language": "en",
        },
    ),
    "technology": (
        {
            "provider": "nist_public_rss",
            "url": "https://www.nist.gov/blogs/cybersecurity-insights/rss.xml",
            "publisher": "National Institute of Standards and Technology",
            "rights": "U.S. federal government source; cite NIST and exclude third-party material unless separately reviewed.",
            "rights_url": "https://www.nist.gov/",
            "language": "en",
        },
    ),
}

_ARTICLE_URLS = {
    "whitehouse_public_news": re.compile(
        r"https://www\.whitehouse\.gov/(?:releases|briefings-statements|presidential-actions)/"
        r"\d{4}/\d{2}/[a-z0-9][a-z0-9-]{1,180}/?"
    ),
    "bls_public_rss": re.compile(r"https://www\.bls\.gov/(?:news\.release|opub)/[a-z0-9_./-]{1,220}"),
    "federal_reserve": re.compile(
        r"https://www\.federalreserve\.gov/newsevents/pressreleases/[a-z0-9]+\.htm"
    ),
    "nist_public_rss": re.compile(
        r"https://www\.nist\.gov/blogs/cybersecurity-insights/[a-z0-9-]{1,180}/?"
    ),
}


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg", "nav", "header", "footer", "aside"}:
            self.skip += 1
        elif not self.skip and tag in {"h1", "h2", "h3", "p", "li"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg", "nav", "header", "footer", "aside"}:
            self.skip = max(0, self.skip - 1)
        elif not self.skip and tag in {"h1", "h2", "h3", "p", "li"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            value = " ".join(data.split())
            if value:
                self.parts.append(value)

    def text(self) -> str:
        return "\n".join(" ".join(x.split()) for x in "".join(self.parts).splitlines() if x.strip())


def _utc(value: str) -> datetime | None:
    value = value.strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))  # noqa: FURB162 - normalizes RFC3339 Z for older runtimes
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _fresh_publication_date(value: str, *, now: datetime) -> str | None:
    """Keep date-only source metadata date-only; never invent a time zone."""
    raw = value.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            published_date = date.fromisoformat(raw)
            if published_date > now.date() or (now.date() - published_date).days > MAX_AGE_DAYS:
                return None
            return raw
    except ValueError:
        return None
    instant = _utc(raw)
    if instant is None or instant > now or now - instant > timedelta(days=MAX_AGE_DAYS):
        return None
    return instant.isoformat()


def _research_url_key(value: str) -> str:
    """Match a source URL to the opened page while dropping known tracking parameters."""
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return ""
    query = [
        (key, item) for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_")
        and key.casefold() not in {"trk", "fbclid", "gclid", "mc_cid", "mc_eid"}
    ]
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), urlencode(query), ""))


def _parse_feed(raw: bytes, *, now: datetime) -> list[dict[str, Any]]:
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("scheduled_research_unsafe_feed")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        raise ValueError("scheduled_research_invalid_feed") from None
    items: list[dict[str, Any]] = []
    for node in root.findall(".//item") + root.findall(".//{http://www.w3.org/2005/Atom}entry"):
        title = " ".join((node.findtext("title") or node.findtext("{http://www.w3.org/2005/Atom}title") or "").split())
        link = node.findtext("link") or ""
        if not link:
            atom_link = node.find("{http://www.w3.org/2005/Atom}link")
            link = atom_link.get("href", "") if atom_link is not None else ""
        published_text = (
            node.findtext("pubDate")
            or node.findtext("published")
            or node.findtext("{http://www.w3.org/2005/Atom}published")
            or node.findtext("{http://www.w3.org/2005/Atom}updated")
            or ""
        )
        published = _utc(published_text)
        summary = node.findtext("description") or node.findtext("{http://www.w3.org/2005/Atom}summary") or ""
        if title and link and published and published <= now and now - published <= timedelta(days=MAX_AGE_DAYS):
            items.append({"title": title[:240], "url": link.strip(), "published_at": published, "feed_excerpt": " ".join(summary.split())[:1000]})
    return items


def _fetch(provider: str, url: str, *, run_id: str) -> bytes:
    with external_run(run_id), external_client(provider, "source_collection", timeout=15, headers={"User-Agent": "WooriBlogAgent/0.3.5 (bounded Automation research)"}) as client:
        return collection.fetch(client, url)


def _article(provider: str, url: str, *, run_id: str) -> tuple[str, str]:
    if not _ARTICLE_URLS[provider].fullmatch(url):
        raise ValueError("scheduled_research_article_url_not_approved")
    body = _fetch(provider, url, run_id=run_id)
    parser = _Text()
    parser.feed(body.decode("utf-8-sig", errors="replace"))
    return parser.text()[:1200], hashlib.sha256(body).hexdigest()


def gather(
    category: str,
    topic: str,
    *,
    occurrence_id: str | None = None,
    manual_run_id: str | None = None,
    audit_run_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    if category not in FEEDS:
        raise ValueError("scheduled_research_category_not_supported")
    if not isinstance(topic, str) or not topic.strip() or len(topic) > MAX_TOPIC_CHARS:
        raise ValueError("scheduled_research_topic_invalid")
    if isinstance(occurrence_id, str) and manual_run_id is None:
        if not re.fullmatch(r"codex-slot:[A-Za-z0-9_-]{1,80}:\d{8}T\d{4}KST", occurrence_id):
            raise ValueError("scheduled_research_occurrence_invalid")
        identity_field, identity, schema_version = (
            "occurrence_id", occurrence_id, "scheduled-research-package/1.0"
        )
    elif isinstance(manual_run_id, str) and occurrence_id is None:
        if not re.fullmatch(r"codex-manual:[A-Za-z0-9_-]{1,80}:[0-9a-fA-F-]{36}", manual_run_id):
            raise ValueError("manual_research_run_id_invalid")
        identity_field, identity, schema_version = (
            "manual_run_id", manual_run_id, "manual-research-package/1.0"
        )
    else:
        raise ValueError("research_package_identity_invalid")
    trace_id = audit_run_id or "research-source-" + uuid4().hex
    captured_at = (now or datetime.now(UTC)).astimezone(UTC)
    package_sources: list[dict[str, Any]] = []
    fetch_failures: list[dict[str, str]] = []
    for source in FEEDS[category]:
        provider, feed_url = source["provider"], source["url"]
        try:
            feed = _parse_feed(_fetch(provider, feed_url, run_id=trace_id), now=captured_at)
        except Exception as exc:  # noqa: BLE001 - classify bounded fetch/parser failures without raw response data
            reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
            fetch_failures.append({"provider": provider, "reason": reason[:120]})
            continue
        for item in feed[:MAX_ITEMS]:
            if not _ARTICLE_URLS[provider].fullmatch(item["url"]):
                fetch_failures.append({"provider": provider, "reason": "feed_article_url_not_approved"})
                continue
            try:
                evidence, body_sha256 = _article(provider, item["url"], run_id=trace_id)
            except Exception as exc:  # noqa: BLE001 - classify bounded fetch/parser failures without raw response data
                reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
                fetch_failures.append({"provider": provider, "reason": reason[:120]})
                continue
            if len(evidence) < 160:
                fetch_failures.append({"provider": provider, "reason": "article_evidence_too_short"})
                continue
            package_sources.append({
                "title": item["title"], "publisher": source["publisher"], "url": item["url"],
                "published_at": item["published_at"].isoformat(), "event_date": None,
                "collected_at": captured_at.isoformat(), "evidence_excerpt": evidence,
                "body_sha256": body_sha256,
                "feed_excerpt": item["feed_excerpt"], "rights": source["rights"],
                "rights_url": source["rights_url"], "source_language": source["language"],
                "source_role": "primary_source", "semantic_review": "required",
            })
    package_sources.sort(key=lambda item: item["published_at"], reverse=True)
    package = {
        "schema_version": schema_version,
        identity_field: identity,
        "category": category,
        "topic": topic.strip(),
        "captured_at": captured_at.isoformat(),
        "freshness_days": MAX_AGE_DAYS,
        "status": "evidence_available" if package_sources else "evidence_unavailable",
        "failure_class": None if package_sources else (
            "collection_failed" if fetch_failures else "no_fresh_source_items"
        ),
        "sources": package_sources[:MAX_ITEMS],
        "collection_failures": fetch_failures,
        "limitations": ["Official-source statements support only what the source itself says.", "Source collection does not complete semantic fact, rights, or publication review."],
    }
    return package


def _gather_with_codex_search(
    category: str, topic: str, *, run_id: str, identity_field: str,
    package_schema: str, audit_run_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Use the installed ChatGPT-auth Codex CLI search tool and retain its evidence.

    Search results are matched back to the CLI's emitted web_search result set.
    A source is eligible only when that exact result URL was also opened by the
    CLI and the quoted evidence matches the returned page/search excerpt.
    """
    from . import codex_runner

    if category not in {"politics", "economy", "technology", "general"}:
        raise ValueError("research_category_not_supported")
    if not isinstance(topic, str) or not topic.strip() or len(topic) > MAX_TOPIC_CHARS:
        raise ValueError("research_topic_invalid")
    if identity_field == "occurrence_id":
        if not re.fullmatch(r"codex-slot:[A-Za-z0-9_-]{1,80}:\d{8}T\d{4}KST", run_id):
            raise ValueError("scheduled_research_occurrence_invalid")
    elif identity_field == "manual_run_id":
        if not re.fullmatch(r"codex-manual:[A-Za-z0-9_-]{1,80}:[0-9a-fA-F-]{36}", run_id):
            raise ValueError("manual_research_run_id_invalid")
    else:
        raise ValueError("research_identity_field_invalid")
    captured_at = (now or datetime.now(UTC)).astimezone(UTC)
    prompt = (
        "Research this article topic using live web search: " + topic.strip() + "\n"
        "Category: " + category + ". Prefer current primary sources, then reputable news sources. "
        "Open the source pages before selecting them. Return at most three sources that you actually opened "
        "and that are present in your live web search results. For each, give the exact result title, publisher, "
        "canonical result URL, publication date as ISO-8601, event date if stated, and a 30-300 character "
        "evidence excerpt copied exactly from the opened source page. Do not select a search result whose "
        "page you did not open, and do not claim that the excerpt was independently verified. "
        "Do not invent a source, date, URL, or excerpt. Exclude results whose publication date is unclear or older than 14 days. "
        "If no current supported source exists, return an empty sources array. This is evidence collection only; "
        "do not draft an article and do not claim semantic or rights review."
    )
    data, evidence = codex_runner.execute(
        Path(tempfile.gettempdir()) / "woori-automation-research" / uuid4().hex,
        prompt,
        CODEX_RESEARCH_SCHEMA,
        lambda *_args: None,
        lambda: False,
        timeout=180,
        require_opened_sources=True,
        require_web_research=True,
        enable_search=True,
    )
    observed: dict[str, dict[str, Any]] = {}
    for result in evidence.get("searched_sources", []):
        url = str(result.get("url", ""))
        if url:
            observed[_research_url_key(url)] = result
    sources: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    opened_urls = {
        _research_url_key(url): str(opened_at)
        for url, opened_at in (evidence.get("opened_urls") or {}).items()
        if isinstance(url, str) and isinstance(opened_at, str)
    }
    for candidate in data.get("sources", []):
        url = str(candidate.get("url", "")).rstrip("/")
        source_key = _research_url_key(url)
        found = observed.get(source_key)
        if not found:
            failures.append({"provider": "codex_cli_chatgpt_search", "reason": "source_not_in_search_results"})
            continue
        opened_at = opened_urls.get(source_key)
        if not opened_at:
            failures.append({"provider": "codex_cli_chatgpt_search", "reason": "source_page_not_opened"})
            continue
        if " ".join(str(candidate.get("title", "")).split()).casefold() != " ".join(str(found.get("title", "")).split()).casefold():
            failures.append({"provider": "codex_cli_chatgpt_search", "reason": "source_title_not_in_search_results"})
            continue
        excerpt = " ".join(str(candidate.get("evidence_excerpt", "")).split())
        snippet = " ".join(str(found.get("snippet", "")).split())
        if len(snippet) < 30:
            failures.append({"provider": "codex_cli_chatgpt_search", "reason": "search_result_evidence_too_short"})
            continue
        if len(excerpt) < 30:
            failures.append({"provider": "codex_cli_chatgpt_search", "reason": "opened_source_evidence_too_short"})
            continue
        published = _fresh_publication_date(str(candidate.get("published_at", "")), now=captured_at)
        if published is None:
            failures.append({"provider": "codex_cli_chatgpt_search", "reason": "source_date_missing_future_or_stale"})
            continue
        sources.append({
            "title": str(candidate["title"]).strip(),
            "publisher": str(candidate["publisher"]).strip(),
            "url": url,
            "published_at": published,
            "event_date": candidate.get("event_date"),
            "collected_at": captured_at.isoformat(),
            "evidence_excerpt": excerpt[:700],
            "model_excerpt_matches_search_snippet": excerpt.casefold() in snippet.casefold(),
            "search_result_snippet": snippet[:1200],
            "search_result_domain": str(found.get("domain", ""))[:160],
            "source_opened_at": opened_at,
            "source_evidence_method": "codex_cli_chatgpt_opened_page_model_excerpt",
            "source_date_basis": "codex_cli_reported_not_independently_verified",
            "publisher_basis": "codex_cli_reported",
            "semantic_review": "required",
            "rights_review": "required",
        })
    sources.sort(key=lambda item: item["published_at"], reverse=True)
    return {
        "schema_version": package_schema,
        identity_field: run_id,
        "category": category,
        "topic": topic.strip(),
        "captured_at": captured_at.isoformat(),
        "freshness_days": MAX_AGE_DAYS,
        "research_engine": "codex_cli_chatgpt_search",
        "codex_model": evidence.get("model"),
        "web_search_count": evidence.get("web_search_count", 0),
        "execution_id": evidence.get("execution_id"),
        "status": "evidence_available" if sources else "evidence_unavailable",
        "failure_class": None if sources else ("source_validation_failed" if failures else "no_current_sources"),
        "sources": sources[:MAX_ITEMS],
        "collection_failures": failures,
        "limitations": [
            "Source metadata and date are reported by the authenticated Codex search session.",
            "The authenticated Codex research session reports opening each retained URL; returned excerpts are not independently verified here.",
            "Research Import must retrieve each source page and verify claim excerpts before publication eligibility.",
            "Source opening does not complete semantic fact, rights, or publication review.",
        ],
    }


def gather_with_codex_search(
    category: str, topic: str, *, occurrence_id: str, audit_run_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Gather live web-search evidence for a scheduled slot."""
    return _gather_with_codex_search(
        category, topic, run_id=occurrence_id, identity_field="occurrence_id",
        package_schema="scheduled-research-package/1.0",
        audit_run_id=audit_run_id or "scheduled:" + occurrence_id, now=now,
    )


def gather_manual_with_codex_search(
    category: str, topic: str, *, manual_run_id: str, now: datetime | None = None,
) -> dict[str, Any]:
    """Gather live evidence for one resolver-confirmed manual Run now."""
    return _gather_with_codex_search(
        category, topic, run_id=manual_run_id, identity_field="manual_run_id",
        package_schema="manual-research-package/1.0",
        audit_run_id="manual:" + manual_run_id, now=now,
    )


def run_authorized_research(
    *, automation_id: str, category: str, topic: str, preflight: dict[str, Any]
) -> dict[str, Any]:
    """Require the same live Desktop scheduled invocation and clear local preflight."""
    from .automation_controls import authoring_permission
    from .automation_invocation import resolve_current_invocation

    invocation = resolve_current_invocation(automation_id, project_root=ROOT)
    if invocation.get("execution_mode") != "scheduled":
        raise ValueError("scheduled_research_requires_scheduled_trigger")
    permission = authoring_permission()
    if permission.get("allowed") is not True:
        raise ValueError("scheduled_research_authoring_policy_not_allowed")
    expected = {
        key: invocation.get(key)
        for key in ("automation_id", "execution_mode", "occurrence_id", "scheduled_slot")
    }
    evidence = preflight.get("automation_execution")
    evidence_invocation = evidence.get("invocation") if isinstance(evidence, dict) else None
    if not isinstance(evidence_invocation, dict) or any(
        evidence_invocation.get(key) != value for key, value in expected.items()
    ):
        raise ValueError("scheduled_research_preflight_invocation_mismatch")
    if (
        preflight.get("draft_import_allowed") is not True
        or preflight.get("local_status") not in {"not_found", "failed_only"}
    ):
        raise ValueError("scheduled_research_local_duplicate_preflight_not_clear")
    # overall/remote unknown stays unknown. Only the local generation decision
    # opens the source-research step; publication still rechecks remote state.
    occurrence_id = str(invocation["occurrence_id"])
    try:
        package = gather_with_codex_search(
            category, topic, occurrence_id=occurrence_id,
            audit_run_id="scheduled:" + occurrence_id,
        )
    except (RuntimeError, OSError, ValueError) as exc:
        reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        _record_codex_search_failure(automation_id, occurrence_id, reason)
        # A category feed cannot establish country/topic relevance. Scheduled
        # Codex research therefore fails closed on every live-search error;
        # unlike a completed source-validation result, retain the exception as
        # a blocked operational outcome rather than a research package.
        if any(marker in reason for marker in ("usage_limit", "capacity", "auth", "timeout", "billable_credentials")):
            raise ValueError("scheduled_codex_search_blocked:" + reason[:100]) from None
        raise ValueError("scheduled_codex_search_unavailable:" + reason[:100]) from None
    # A completed live search that found no usable source is not a transport
    # outage. Falling back by category alone can attach a U.S. feed item to an
    # unrelated country/topic and incorrectly turn failed validation into
    # evidence_available. Preserve the Codex failure package as-is.
    result = write_package(package, automation_id=automation_id)
    return {
        **result,
        "execution_mode": "scheduled",
        "occurrence_id": invocation["occurrence_id"],
        "remote_status": preflight.get("remote_status", "not_checked"),
        "overall_status": preflight.get("status", "unknown"),
    }


def run_manual_authorized_research(
    *, automation_id: str, category: str, topic: str, preflight: dict[str, Any]
) -> dict[str, Any]:
    """Research only for the exact current manual Run now and its clear preflight."""
    from .automation_authoring_contract import select_authoring_contract
    from .automation_invocation import resolve_current_invocation
    from .automation_ready_handoff import preflight_allows_import

    invocation = resolve_current_invocation(automation_id, project_root=ROOT)
    if invocation.get("execution_mode") != "manual" or invocation.get("trigger") != "automation_cron_run_now":
        raise ValueError("manual_research_requires_run_now_trigger")
    execution = preflight.get("automation_execution")
    recorded_invocation = execution.get("invocation") if isinstance(execution, dict) else None
    contract = execution.get("contract") if isinstance(execution, dict) else None
    if recorded_invocation != invocation:
        raise ValueError("manual_research_preflight_invocation_mismatch")
    if contract != select_authoring_contract(invocation):
        raise ValueError("manual_research_authoring_contract_mismatch")
    if not preflight_allows_import(preflight):
        raise ValueError("manual_research_local_duplicate_preflight_not_clear")

    manual_run_id = str(invocation["manual_run_id"])
    try:
        package = gather_manual_with_codex_search(category, topic, manual_run_id=manual_run_id)
    except (RuntimeError, OSError, ValueError) as exc:
        reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        _record_codex_search_failure(automation_id, manual_run_id, reason, manual=True)
        if any(marker in reason for marker in (
            "usage_limit", "capacity", "auth", "timeout", "billable_credentials"
        )):
            raise ValueError("manual_codex_search_blocked:" + reason[:100]) from None
        if reason not in {
            "codex_not_installed", "web_research_not_observed", "codex_execution_failed"
        } or category not in FEEDS:
            raise ValueError("manual_codex_search_unavailable:" + reason[:100]) from None
        package = gather(
            category, topic, manual_run_id=manual_run_id,
            audit_run_id="manual:" + manual_run_id,
        )
        package["research_engine"] = "fixed_rss_fallback"
        package["codex_search_failure"] = reason[:120]
    if (
        package.get("status") != "evidence_available"
        and package.get("failure_class") in {"no_current_sources", "source_validation_failed"}
        and category in FEEDS
    ):
        search_failure = str(package.get("failure_class"))
        package = gather(
            category, topic, manual_run_id=manual_run_id,
            audit_run_id="manual:" + manual_run_id,
        )
        package["research_engine"] = "fixed_rss_fallback"
        package["codex_search_failure"] = search_failure
    result = write_package(package, automation_id=automation_id)
    return {
        **result,
        "execution_mode": "manual",
        "manual_run_id": manual_run_id,
        "remote_status": preflight.get("remote_status", "not_checked"),
        "overall_status": preflight.get("status", "unknown"),
    }


def _record_codex_search_failure(
    automation_id: str, run_identity: str, reason: str, *, manual: bool = False
) -> None:
    """Append a safe execution result; never persist prompts, sources or credentials here."""
    try:
        with connection() as conn:
            conn.execute(
                "INSERT INTO audit_events(event_type,payload) VALUES (%s,%s)",
                (
                    "research.manual_codex_search.failed" if manual else "research.scheduled_codex_search.failed",
                    Jsonb({
                    "automation_id": automation_id,
                    "manual_run_id" if manual else "occurrence_id": run_identity,
                    "reason_code": reason[:120],
                    "api_key_fallback": False,
                    }),
                ),
            )
    except (OSError, psycopg.Error):
        raise ValueError("scheduled_research_audit_failed") from None


def write_package(package: dict[str, Any], *, automation_id: str) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", automation_id):
        raise ValueError("scheduled_research_automation_id_invalid")
    occurrence = package.get("occurrence_id")
    manual_run_id = package.get("manual_run_id")
    if isinstance(occurrence, str) and not manual_run_id:
        if not re.fullmatch(r"codex-slot:[A-Za-z0-9_-]{1,80}:\d{8}T\d{4}KST", occurrence):
            raise ValueError("scheduled_research_occurrence_invalid")
        run_identity = occurrence
        slug = occurrence.rsplit(":", 1)[1]
        event_prefix = "scheduled"
    elif isinstance(manual_run_id, str) and not occurrence:
        match = re.fullmatch(r"codex-manual:([A-Za-z0-9_-]{1,80}):([0-9a-fA-F-]{36})", manual_run_id)
        if match is None or match.group(1) != automation_id:
            raise ValueError("manual_research_run_id_invalid")
        run_identity = manual_run_id
        slug = "manual-" + match.group(2).lower()
        event_prefix = "manual"
    else:
        raise ValueError("research_package_identity_invalid")
    PACKAGE_DIR.mkdir(parents=True, exist_ok=True)
    destination = PACKAGE_DIR / f"{automation_id}-{slug}.research.json"
    raw = (json.dumps(package, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    from .research_snapshot import write_snapshot

    temporary = PACKAGE_DIR / f".{automation_id}-{slug}-{digest[:12]}.part"
    with temporary.open("xb") as staging:
        staging.write(raw)
        staging.flush()
    try:
        try:
            saved_digest = write_snapshot(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
    except FileExistsError:
        existing = destination.read_bytes()
        saved_digest = hashlib.sha256(existing).hexdigest()
        if saved_digest != digest:
            raise ValueError(f"{event_prefix}_research_package_conflict") from None
    try:
        with connection() as conn:
            event = (
                f"research.{event_prefix}_package.saved"
                if package.get("status") == "evidence_available"
                else f"research.{event_prefix}_package.unavailable"
            )
            conn.execute(
                "INSERT INTO audit_events(event_type,payload) VALUES (%s,%s)",
                (event, Jsonb({
                    "automation_id": automation_id,
                    "manual_run_id" if event_prefix == "manual" else "occurrence_id": run_identity,
                    "category": package.get("category"),
                    "source_count": len(package.get("sources", [])),
                    "failure_class": package.get("failure_class"),
                    "sha256": saved_digest,
                })),
            )
    except (OSError, psycopg.Error):
        raise ValueError("scheduled_research_audit_failed") from None
    return {"status": package.get("status"), "path": str(destination), "sha256": saved_digest, "source_count": len(package.get("sources", [])), "collection_failure_count": len(package.get("collection_failures", []))}
