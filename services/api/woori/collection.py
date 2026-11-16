"""Allowlisted, bounded public metadata/feed collection; no arbitrary URL fetches."""

import hashlib
import html
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any
from uuid import UUID

import httpx

from .ai import EngineFailure
from .db import connection
from .external_policy import FreeQuotaExceeded
from .external_policy import client as external_client
from .pipeline import emit, normalized, required

ENDPOINTS = {
    "fed_rss": "https://www.federalreserve.gov/feeds/press_all.xml",
    "wikidata": "https://www.wikidata.org/w/api.php",
    "sec_edgar": "https://data.sec.gov/submissions/",
}
USER_AGENT = (
    "WooriBlogAgent/0.3.5 (https://github.com/alsruddns/woori-blog-agent; bounded research)"
)


class Paragraphs(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.buffer: list[str] = []
        self.capture = False
        self.article_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "div":
            if self.article_depth:
                self.article_depth += 1
            elif dict(attrs).get("id") == "article":
                self.article_depth = 1
        if tag == "p":
            self.buffer = []
            self.capture = self.article_depth > 0 and dict(attrs).get("class") not in (
                "article__time",
                "releaseTime",
            )

    def handle_data(self, data: str) -> None:
        if self.capture:
            self.buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self.article_depth:
            self.article_depth -= 1
        if tag == "p" and self.capture:
            value = " ".join(" ".join(self.buffer).split())
            if len(value) > 40:
                self.parts.append(value)
            self.capture = False


def fetch(client: httpx.Client, url: str, params: dict[str, Any] | None = None) -> bytes:
    started = time.monotonic()
    try:
        with client.stream("GET", url, params=params) as response:
            if response.status_code == 429:
                delay = response.headers.get("Retry-After", "3600")
                raise EngineFailure(
                    "collection_rate_limit", True, int(delay) if delay.isdigit() else 3600
                )
            if response.status_code >= 500:
                raise EngineFailure("collection_unavailable", True)
            if response.status_code != 200:
                raise EngineFailure("collection_access_denied")
            result = b""
            for block in response.iter_bytes(65536):
                result += block
                if len(result) > 1024 * 1024 or time.monotonic() - started > 20:
                    raise EngineFailure("collection_response_limit")
            return result
    except FreeQuotaExceeded:
        raise EngineFailure("free_quota_exceeded") from None
    except httpx.HTTPError:
        raise EngineFailure("collection_network_error", True) from None


def retrieve(source: dict[str, Any], topics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if ENDPOINTS.get(source["adapter"]) != source["endpoint"]:
        raise EngineFailure("collection_endpoint_not_approved")
    results = []
    provider = {
        "fed_rss": "federal_reserve",
        "wikidata": "wikidata",
        "sec_edgar": "sec_edgar",
    }[source["adapter"]]
    headers = {"User-Agent": USER_AGENT}
    if source["adapter"] == "sec_edgar":
        contact = os.getenv("SEC_USER_AGENT_CONTACT", "").strip()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", contact):
            raise EngineFailure("sec_user_agent_contact_required")
        headers["User-Agent"] = f"WooriBlogAgent/0.3.8 ({contact})"
    with external_client(provider, "source_collection", timeout=15, headers=headers) as client:
        if source["adapter"] == "fed_rss":
            data = fetch(client, source["endpoint"])
            if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
                raise EngineFailure("unsafe_feed")
            try:
                items = ET.fromstring(data).findall(".//item")[:2]
            except ET.ParseError:
                raise EngineFailure("invalid_feed") from None
            for item in items:
                title = html.unescape(item.findtext("title", "")).strip()
                url = item.findtext("link", "").strip()
                if not re.fullmatch(
                    r"https://www\.federalreserve\.gov/newsevents/pressreleases/[a-z0-9]+\.htm", url
                ):
                    continue
                try:
                    published = parsedate_to_datetime(item.findtext("pubDate", ""))
                except (ValueError, TypeError):
                    continue
                if published.tzinfo is None or published > datetime.now(UTC):
                    continue
                time.sleep(1)
                parser = Paragraphs()
                parser.feed(fetch(client, url).decode("utf-8-sig"))
                evidence = (title + ". " + " ".join(parser.parts))[:1000]
                results.append(
                    {
                        "external_id": url,
                        "url": url,
                        "title": title[:150],
                        "evidence": evidence,
                        "published_at": published,
                        "source_language": "en",
                        "retrieved_at": datetime.now(UTC),
                        "category_id": topics[0]["category_id"],
                        "primary": True,
                        "valid_until": published + timedelta(days=30),
                    }
                )
        elif source["adapter"] == "wikidata":
            for topic in topics:
                time.sleep(1)
                data = json.loads(
                    fetch(
                        client,
                        source["endpoint"],
                        {
                            "action": "wbsearchentities",
                            "search": topic["query"],
                            "language": "en",
                            "format": "json",
                            "limit": 1,
                            "maxlag": 5,
                        },
                    )
                )
                if data.get("error"):
                    raise EngineFailure("wikidata_maxlag_or_api_error", True)
                for item in data.get("search", []):
                    if not re.fullmatch(r"Q[0-9]+", item.get("id", "")):
                        continue
                    results.append(
                        {
                            "external_id": item["id"] + ":" + str(topic["category_id"]),
                            "url": "https://www.wikidata.org/wiki/" + item["id"],
                            "title": item.get("label", topic["query"])[:150],
                            "evidence": item.get("label", "") + ": " + item.get("description", ""),
                            "published_at": None,
                            "source_language": "en",
                            "retrieved_at": datetime.now(UTC),
                            "category_id": topic["category_id"],
                            "primary": False,
                            "valid_until": datetime.now(UTC) + timedelta(days=7),
                        }
                    )
        else:
            # A topic is a CIK, stored as data, never interpolated into an arbitrary host/path.
            for topic in topics[:2]:
                cik = str(topic["query"]).strip().removeprefix("CIK").zfill(10)
                if not re.fullmatch(r"\d{10}", cik):
                    continue
                data = json.loads(fetch(client, source["endpoint"] + f"CIK{cik}.json"))
                recent = data.get("filings", {}).get("recent", {})
                forms = recent.get("form", [])
                chosen = next((i for i, form in enumerate(forms) if form in {"10-K", "10-Q"}), None)
                if chosen is None:
                    continue
                accession = recent["accessionNumber"][chosen]
                accession_compact = accession.replace("-", "")
                filed = datetime.fromisoformat(recent["filingDate"][chosen]).replace(tzinfo=UTC)
                period = str(recent.get("reportDate", [""])[chosen] or "")
                company = str(data.get("name", "SEC filer"))[:120]
                form = str(forms[chosen])
                fact_terms = (
                    ("RevenueFromContractWithCustomerExcludingAssessedTax", "revenue"),
                    ("NetIncomeLoss", "net income"),
                )
                fact_lines: list[str] = []
                for concept, label in fact_terms:
                    fact_url = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{concept}.json"
                    concept_payload = json.loads(fetch(client, fact_url))
                    units = concept_payload.get("units", {})
                    entries = [
                        entry
                        for unit_entries in units.values()
                        for entry in unit_entries
                        if entry.get("accn") == accession
                        and (not period or entry.get("end") == period)
                    ]
                    if not entries:
                        continue
                    entry = entries[-1]
                    value = entry.get("val")
                    if not isinstance(value, (int, float)):
                        continue
                    fact_lines.append(
                        f"{label}: {value} {next(iter(units), 'reported units')}"
                        + (
                            f" for period {entry.get('start')} to {entry.get('end')}"
                            if entry.get("start")
                            else f" as of {entry.get('end')}"
                        )
                    )
                if len(fact_lines) < 2:
                    continue
                accession_path = accession_compact.lstrip("0")
                primary = str(recent.get("primaryDocument", [""])[chosen])
                if not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", primary):
                    continue
                filing_url = (
                    f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_path}/{primary}"
                )
                published = filed
                results.append(
                    {
                        "external_id": f"{cik}:{accession}",
                        "url": filing_url,
                        "title": f"{company} {form} filed {filed.date().isoformat()}",
                        "evidence": (
                            f"{company} filed SEC Form {form} on {filed.date().isoformat()}"
                            + (f" for the period ended {period}. " if period else ". ")
                            + "; ".join(fact_lines)
                            + f". SEC accession number {accession}."
                        )[:1000],
                        "published_at": published,
                        "source_language": "en",
                        "retrieved_at": datetime.now(UTC),
                        "category_id": topic["category_id"],
                        "primary": True,
                        "valid_until": datetime.now(UTC) + timedelta(days=90),
                    }
                )
    return results


def request(
    source_id: UUID, profile_id: UUID, key: str, auto_generate: bool = False
) -> dict[str, Any]:
    with connection() as conn:
        source = conn.execute(
            "SELECT * FROM collection_sources WHERE id=%s AND active", (source_id,)
        ).fetchone()
        if not source:
            raise EngineFailure("collection_source_disabled")
        conn.execute("SELECT pg_advisory_xact_lock(781210)")
        old = conn.execute(
            "SELECT r.*,j.source_id,j.profile_id,j.auto_generate FROM job_runs r JOIN collection_jobs j ON j.run_id=r.id WHERE r.idempotency_key=%s",
            (key,),
        ).fetchone()
        if old:
            if (
                old["source_id"] != source_id
                or old["profile_id"] != profile_id
                or old["auto_generate"] != auto_generate
            ):
                raise EngineFailure("idempotency_conflict")
            return old
        recent = conn.execute(
            "SELECT 1 FROM collection_jobs j JOIN job_runs r ON r.id=j.run_id WHERE source_id=%s AND r.created_at>now()-interval '1 hour'",
            (source_id,),
        ).fetchone()
        if recent:
            raise EngineFailure("collection_hourly_limit")
        row = required(
            conn.execute(
                "INSERT INTO job_runs(idempotency_key,task_kind) VALUES (%s,'collection') RETURNING *",
                (key,),
            ).fetchone()
        )
        conn.execute(
            "INSERT INTO collection_jobs VALUES (%s,%s,%s,%s)",
            (row["id"], source_id, profile_id, auto_generate),
        )
        emit(conn, "collection.queued", row["id"], source_id=str(source_id))
        return row


def collect(run: dict[str, Any]) -> None:
    with connection() as conn:
        job = required(
            conn.execute("SELECT * FROM collection_jobs WHERE run_id=%s", (run["id"],)).fetchone()
        )
        source = required(
            conn.execute(
                "SELECT * FROM collection_sources WHERE id=%s AND active", (job["source_id"],)
            ).fetchone()
        )
        topics = conn.execute(
            "SELECT * FROM collection_topics WHERE source_id=%s", (source["id"],)
        ).fetchall()
    items = retrieve(source, topics)
    for item in items:
        if item["valid_until"] <= datetime.now(UTC):
            continue
        fingerprint = hashlib.sha256(
            json.dumps(item, sort_keys=True, default=str).encode()
        ).hexdigest()
        # Exclude moving collection expiry from identity for structured metadata.
        if not item["published_at"]:
            fingerprint = hashlib.sha256(
                (item["url"] + item["title"] + item["evidence"]).encode()
            ).hexdigest()
        with connection() as conn:
            fence = conn.execute(
                "SELECT id FROM job_runs WHERE id=%s AND attempts=%s AND status='running' AND lease_until>now() FOR UPDATE",
                (run["id"], run["attempts"]),
            ).fetchone()
            if not fence:
                raise EngineFailure("collection_lease_lost")
            exists = conn.execute(
                "SELECT 1 FROM collection_items WHERE source_id=%s AND external_id=%s AND payload_hash=%s",
                (source["id"], item["external_id"], fingerprint),
            ).fetchone()
            if exists:
                continue
            keyword = conn.execute(
                """INSERT INTO keyword_candidates(profile_id,category_id,keyword,normalized_keyword,search_intent,collection_source,rationale,expires_at,priority,status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,50,%s) ON CONFLICT(profile_id,normalized_keyword) DO NOTHING RETURNING *""",
                (
                    job["profile_id"],
                    item["category_id"],
                    item["title"],
                    normalized(item["title"]),
                    "Informational: understand the supplied official source",
                    source["name"],
                    "Automatic source discovery; no search-volume/competition/CPC claim",
                    item["valid_until"],
                    "selected" if item["primary"] else "candidate",
                ),
            ).fetchone()
            if not keyword:
                keyword = required(
                    conn.execute(
                        "SELECT * FROM keyword_candidates WHERE profile_id=%s AND normalized_keyword=%s",
                        (job["profile_id"], normalized(item["title"])),
                    ).fetchone()
                )
            revision = required(
                conn.execute(
                    "SELECT coalesce(max(revision),0)+1 AS n FROM research_sources WHERE keyword_id=%s AND url=%s",
                    (keyword["id"], item["url"]),
                ).fetchone()
            )["n"]
            stored = required(
                conn.execute(
                    """INSERT INTO research_sources(keyword_id,url,source_name,published_at,collected_at,evidence,reliability_reason,rights,access_policy,valid_until,is_primary,revision,source_language)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                    (
                        keyword["id"],
                        item["url"],
                        source["name"],
                        item["published_at"],
                        item.get("retrieved_at", datetime.now(UTC)),
                        item["evidence"],
                        "Fixed official feed URL and article provenance"
                        if item["primary"]
                        else "Community CC0 topic metadata; primary confirmation required",
                        source["rights"],
                        "Explicit RSS/API access; bounded requests, no redirects, 1 MiB cap; cite provider",
                        item["valid_until"],
                        item["primary"],
                        revision,
                        item.get("source_language", "und"),
                    ),
                ).fetchone()
            )
            if item["primary"]:
                conn.execute(
                    "INSERT INTO source_reviews(source_id,approved,reason,reviewer,source_language) VALUES (%s,true,%s,%s,%s)",
                    (
                        stored["id"],
                        "Primary public filing/feed origin and filing metadata checked mechanically; substantive article claims remain subject to human review",
                        "collector:" + source["adapter"],
                        item.get("source_language", "und"),
                    ),
                )
            conn.execute(
                "INSERT INTO collection_items(source_id,external_id,keyword_id,research_source_id,payload_hash,collected_at) VALUES (%s,%s,%s,%s,%s,%s)",
                (
                    source["id"],
                    item["external_id"],
                    keyword["id"],
                    stored["id"],
                    fingerprint,
                    item.get("retrieved_at", datetime.now(UTC)),
                ),
            )
            emit(
                conn,
                "collection.saved",
                run["id"],
                keyword_id=str(keyword["id"]),
                source_id=str(stored["id"]),
                primary=item["primary"],
                rights=source["rights"],
            )
    # Historical generation flags are retained, but no writer provider is currently attached.
    if job["auto_generate"]:
        with connection() as conn:
            emit(
                conn,
                "collection.auto_generation_blocked",
                run["id"],
                reason="generation_provider_not_configured",
            )
    with connection() as conn:
        conn.execute(
            "UPDATE collection_sources SET last_collected_at=now(),last_attempt_at=now(),last_successful_at=now(),last_error=NULL WHERE id=%s",
            (source["id"],),
        )


def tick(run_id: UUID | None = None) -> bool:
    with connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(781211)")
        if required(conn.execute("SELECT paused FROM pipeline_controls").fetchone())["paused"]:
            return False
        expired = conn.execute(
            """UPDATE job_runs SET status=CASE WHEN attempts>=3 THEN 'failed' ELSE 'queued' END,lease_until=NULL
            WHERE task_kind='collection' AND status='running' AND lease_until<now()
              AND (%s::uuid IS NULL OR id=%s) RETURNING id""",
            (run_id, run_id),
        ).fetchall()
        for row in expired:
            emit(conn, "collection.recovered", row["id"])
        run = conn.execute(
            "SELECT r.* FROM job_runs r JOIN collection_jobs j ON j.run_id=r.id WHERE r.status='queued' AND r.available_at<=now() AND r.task_kind='collection' AND (%s::uuid IS NULL OR r.id=%s) ORDER BY r.created_at FOR UPDATE OF r SKIP LOCKED LIMIT 1",
            (run_id, run_id),
        ).fetchone()
        if not run:
            return False
        run = required(
            conn.execute(
                "UPDATE job_runs SET status='running',attempts=attempts+1,lease_until=now()+interval '120 seconds' WHERE id=%s RETURNING *",
                (run["id"],),
            ).fetchone()
        )
        emit(conn, "collection.started", run["id"], attempt=run["attempts"])
    category: str | None = None
    delay = 60
    try:
        collect(run)
    except (EngineFailure, ValueError, KeyError, TypeError) as exc:
        category = exc.category if isinstance(exc, EngineFailure) else "invalid_collection_response"
        retry = isinstance(exc, EngineFailure) and exc.retryable and run["attempts"] < 3
        if isinstance(exc, EngineFailure):
            delay = exc.retry_after_seconds
        status = "queued" if retry else "failed"
    else:
        category, status = None, "succeeded"
    with connection() as conn:
        changed = conn.execute(
            """UPDATE job_runs SET status=%s,error_type=%s,error_message=%s,error_location='collector',
            error_at=CASE WHEN %s::text IS NOT NULL THEN now() ELSE NULL END,available_at=now()+interval '1 second'*%s,lease_until=NULL,updated_at=now()
            WHERE id=%s AND attempts=%s AND status='running' RETURNING id""",
            (status, category, category, category, delay, run["id"], run["attempts"]),
        ).fetchone()
        if changed:
            emit(conn, "collection." + status, run["id"], category=category)
            conn.execute(
                "UPDATE collection_sources SET last_attempt_at=now(),last_error=%s WHERE id=(SELECT source_id FROM collection_jobs WHERE run_id=%s)",
                (category, run["id"]),
            )
    return True


def schedule_tick() -> None:
    with connection() as conn:
        due = conn.execute(
            "SELECT * FROM collection_sources WHERE scheduled AND active AND profile_id IS NOT NULL AND next_run_at<=now()"
        ).fetchall()
    for source in due:
        try:
            request(
                source["id"],
                source["profile_id"],
                "collector-"
                + str(source["id"])
                + "-"
                + str(int(source["next_run_at"].timestamp())),
                source["auto_generate"],
            )
        except EngineFailure:
            continue
        with connection() as conn:
            conn.execute(
                "UPDATE collection_sources SET next_run_at=now()+interval '1 minute'*interval_minutes WHERE id=%s",
                (source["id"],),
            )
