"""Bounded live-source capture for the first reviewed scheduled-source catalog.

This collector captures provenance only. It does not infer semantic support or
reuse permission, and an unsupported source URL is never fetched.
"""

from __future__ import annotations

import hashlib
import re
import time
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from . import external_policy
from .db import connection
from .external_policy import external_run
from .scheduled_auto_verification import _quantity_facts, excerpt_supported

MAX_RESPONSE_BYTES = 1024 * 1024
MAX_CAPTURE_SECONDS = 20
CAPTURE_POLICY_VERSION = "scheduled-live-source-capture-4"
_CATALOG: dict[str, dict[str, str]] = {
    "https://www.nenryo-teigakuhikisage.go.jp/": {
        "source_id": "S5",
        "provider": "japan_energy_subsidy_site",
        "source_host": "www.nenryo-teigakuhikisage.go.jp",
        "organization": "Agency for Natural Resources and Energy, METI",
    },
    "https://www.ons.gov.uk/economy/governmentpublicsectorandtaxes/publicsectorfinance/bulletins/publicsectorfinances/september2026": {
        "source_id": "ONS-PF-2026-09",
        "provider": "ons_official_statistics",
        "source_host": "www.ons.gov.uk",
        "source_path": "/economy/governmentpublicsectorandtaxes/publicsectorfinance/bulletins/publicsectorfinances/september2026",
        "organization": "Office for National Statistics",
        "reuse_terms_url": "https://www.ons.gov.uk/help/terms-conditions",
    },
}
_ONS_REUSE_POLICY_ID = "ons-open-government-licence"
_ONS_REUSE_POLICY_VERSION = "3.0"
_ONS_REUSE_POLICY_EXPIRES_AT = "2027-01-26T00:00:00+00:00"
_DATE_RE = re.compile(rf"(?:202\d)(?:{chr(0x5e74)}|[/.-])\d{{1,2}}(?:{chr(0x6708)}|[/.-])\d{{1,2}}{chr(0x65e5)}?")
_NUMBER_RE = re.compile(rf"(?<!\d)[+-]?\d[\d,.]*(?:\s?(?:{chr(0x5186)}/L|{chr(0x5186)}|%|bp|{chr(0x4e07)}|{chr(0x5104)}))?", re.IGNORECASE)
_ONS_RELEASE_DATE = re.compile(
    r"\brelease date:\s*(\d{1,2})\s+(january|february|march|april|may|june|july|august|september|october|november|december)\s+(20\d{2})\b",
    re.IGNORECASE,
)
_MONTHS = {
    name.casefold(): number for number, name in enumerate(
        ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"),
        start=1,
    )
}


def _ons_release_date(text: str) -> str | None:
    match = _ONS_RELEASE_DATE.search(text)
    if not match:
        return None
    return (
        f"{int(match.group(3)):04d}-{_MONTHS[match.group(2).casefold()]:02d}-"
        f"{int(match.group(1)):02d}"
    )


class _PageText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.title_depth = 0
        self.footer_depth = 0
        self.title: list[str] = []
        self.footer: list[str] = []
        self.current: list[str] = []
        self.paragraphs: list[str] = []
        self.published_at: str | None = None
        self.updated_at: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag in {"script", "style", "noscript", "svg", "nav", "footer", "iframe"}:
            self.skip_depth += 1
        if tag == "footer":
            self.footer_depth += 1
        if tag == "title":
            self.title_depth += 1
        if tag == "meta":
            key = (values.get("property") or values.get("name") or "").casefold()
            value = values.get("content")
            if value and key in {"article:published_time", "datepublished", "date"}:
                self.published_at = value[:80]
            if value and key in {"article:modified_time", "datemodified", "last-modified"}:
                self.updated_at = value[:80]
        if tag in {"p", "li", "h1", "h2", "h3", "time"} and not self.skip_depth:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.title_depth = max(0, self.title_depth - 1)
        if tag in {"script", "style", "noscript", "svg", "nav", "footer", "iframe"}:
            self.skip_depth = max(0, self.skip_depth - 1)
        if tag == "footer":
            self.footer_depth = max(0, self.footer_depth - 1)
        if tag in {"p", "li", "h1", "h2", "h3", "time"} and not self.skip_depth:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self.title_depth:
            self.title.append(data)
        if self.footer_depth and self.skip_depth == self.footer_depth:
            self.footer.append(data)
        if not self.skip_depth and not self.title_depth:
            self.current.append(data)

    def _flush(self) -> None:
        text = " ".join("".join(self.current).split())
        self.current.clear()
        if text and (not self.paragraphs or self.paragraphs[-1] != text):
            self.paragraphs.append(text[:1200])


def _ons_reuse_terms_allowed(source_footer: str, terms_text: str) -> bool:
    source = re.sub(r"\s+", " ", source_footer).casefold()
    terms = re.sub(r"\s+", " ", terms_text).casefold()
    source_notice = "open government licence v3.0" in source and "except where otherwise stated" in source
    terms_notice = (
        "open government licence (ogl)" in terms
        and "reproduction of information is subject to the terms of the ogl" in terms
        and "some photographs, illustrations and videos" in terms
    )
    return source_notice and terms_notice


def _fetch_ons_reuse_terms(url: str, run_id: UUID) -> dict[str, Any]:
    expected = "https://www.ons.gov.uk/help/terms-conditions"
    if url != expected:
        return {"status": "reuse_terms_url_not_allowlisted"}
    with (
        external_run(str(run_id)),
        external_policy.client(
            "ons_official_statistics", "source_collection", timeout=15,
            headers={"User-Agent": "WooriBlogAgent/0.3.5 (bounded source provenance)"},
        ) as client,
        client.stream("GET", url) as response,
    ):
        if response.status_code == 429:
            raise external_policy.FreeQuotaExceeded("ons_source_provider_http_429")
        if response.status_code != 200:
            return {"status": "reuse_terms_http_error", "http_status": response.status_code}
        if "html" not in response.headers.get("content-type", "").casefold():
            return {"status": "reuse_terms_unexpected_content_type", "http_status": response.status_code}
        body = bytearray()
        started = time.monotonic()
        for chunk in response.iter_bytes(65536):
            body.extend(chunk)
            if len(body) > MAX_RESPONSE_BYTES or time.monotonic() - started > MAX_CAPTURE_SECONDS:
                return {"status": "reuse_terms_response_limit", "http_status": response.status_code}
    raw = bytes(body)
    parser = _PageText()
    parser.feed(raw.decode("utf-8", errors="replace"))
    if parser.current:
        parser._flush()
    text = "\n".join(parser.paragraphs)
    return {
        "status": "captured" if text else "reuse_terms_document_missing",
        "http_status": 200,
        "reuse_terms_url": expected,
        "reuse_terms_sha256": hashlib.sha256(raw).hexdigest(),
        "reuse_terms_text": text,
    }


def _claim_fact_check(claim: dict[str, Any], paragraphs: list[str]) -> tuple[list[str], dict[str, Any]]:
    excerpt = str(claim.get("evidence_excerpt") or "")
    matched = [paragraph for paragraph in paragraphs if excerpt and excerpt in paragraph]
    if not matched and excerpt_supported(excerpt, paragraphs):
        fragments = [part.strip().rstrip(';').strip() for part in re.split(r'\.{3}|…|;', excerpt) if part.strip()]
        matched = [paragraph for paragraph in paragraphs if any(fragment in ' '.join(paragraph.split()) for fragment in fragments)]
    context = "\n".join(matched)
    claim_text = str(claim.get("claim") or "")
    claim_quantities = _quantity_facts(claim_text)
    evidence_quantities = _quantity_facts(context)
    exact = bool(matched)
    return matched, {
        "claim_id": str(claim.get("claim_id") or ""),
        "evidence_excerpt_exactly_present": exact,
        "normalized_quantities": [
            {"kind": kind, "value": value, "present": bool(exact and (kind, value) in evidence_quantities)}
            for kind, value in sorted(claim_quantities)
        ],
        "all_numeric_units_and_dates_match": bool(exact and claim_quantities.issubset(evidence_quantities)),
    }


def _catalog_entry(url: str) -> dict[str, str] | None:
    if re.fullmatch(r'https://www\.federalreserve\.gov/newsevents/pressreleases/monetary[0-9]{8}a\.htm', url):
        return {'provider': 'federal_reserve', 'source_host': 'www.federalreserve.gov',
                'source_path': urlsplit(url).path, 'organization': 'Federal Reserve Board'}
    return _CATALOG.get(url)


def _fetch(url: str, run_id: UUID) -> dict[str, Any]:
    catalog = _catalog_entry(url)
    if not catalog:
        return {"status": "not_in_reviewed_catalog", "source_url": url}
    parts = urlsplit(url)
    if (
        parts.scheme != "https" or parts.hostname != catalog["source_host"]
        or parts.path != catalog.get("source_path", "/") or parts.query or parts.fragment
    ):
        return {"status": "source_url_not_exactly_allowlisted", "source_url": url}
    started = time.monotonic()
    with (
        external_run(str(run_id)),
        external_policy.client(
            catalog["provider"], "source_collection", timeout=15,
            headers={"User-Agent": "WooriBlogAgent/0.3.5 (bounded source provenance)",
                     "Accept": "text/html,application/xhtml+xml"},
        ) as client,
        client.stream("GET", url) as response,
    ):
        if response.status_code == 429:
            raise external_policy.FreeQuotaExceeded("source_provider_http_429")
        if response.status_code != 200:
            return {"status": "http_error", "source_url": url,
                    "http_status": response.status_code}
        if "html" not in response.headers.get("content-type", "").casefold():
            return {"status": "unexpected_content_type", "source_url": url,
                    "http_status": response.status_code}
        body = bytearray()
        for chunk in response.iter_bytes(65536):
            body.extend(chunk)
            if len(body) > MAX_RESPONSE_BYTES or time.monotonic() - started > MAX_CAPTURE_SECONDS:
                return {"status": "response_limit", "source_url": url,
                        "http_status": response.status_code}
        raw = bytes(body)
        parser = _PageText()
        parser.feed(raw.decode("utf-8", errors="replace"))
        if parser.current:
            parser._flush()
        text = "\n".join(parser.paragraphs)
        if not parser.title or not text:
            return {"status": "document_metadata_missing", "source_url": url,
                    "http_status": response.status_code,
                    "source_body_sha256": hashlib.sha256(raw).hexdigest()}
        release_date = parser.published_at
        if catalog["provider"] == "ons_official_statistics" and not release_date:
            release_date = _ons_release_date(text)
        reuse = {"status": "not_applicable"}
        reuse_allowed = False
        if catalog["provider"] == "ons_official_statistics":
            reuse = _fetch_ons_reuse_terms(catalog["reuse_terms_url"], run_id)
            reuse_text = str(reuse.pop("reuse_terms_text", ""))
            reuse_allowed = (
                reuse.get("status") == "captured"
                and _ons_reuse_terms_allowed("".join(parser.footer), reuse_text)
            )
        return {
            "status": "captured",
            "http_status": response.status_code,
            "source_url": url,
            "source_host": catalog["source_host"],
            "organization": catalog["organization"],
            "source_title": " ".join("".join(parser.title).split())[:300],
            "source_published_at": parser.published_at,
            "source_published_date": release_date,
            "source_updated_at": parser.updated_at,
            "retrieved_at": datetime.now(UTC).isoformat(),
            "source_body_sha256": hashlib.sha256(raw).hexdigest(),
            "source_body_bytes": len(raw),
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "paragraphs": parser.paragraphs,
            "visible_text": text,
            "page_dates": sorted(set(_DATE_RE.findall(text))),
            "page_numbers": sorted(set(_NUMBER_RE.findall(text))),
            "reuse_terms_verified": reuse_allowed,
            "reuse_terms_status": "allowed" if reuse_allowed else "unknown",
            "reuse_terms_url": reuse.get("reuse_terms_url"),
            "reuse_terms_sha256": reuse.get("reuse_terms_sha256"),
            "reuse_policy_id": _ONS_REUSE_POLICY_ID if reuse_allowed else None,
            "reuse_policy_version": _ONS_REUSE_POLICY_VERSION if reuse_allowed else None,
            "reuse_policy_expires_at": _ONS_REUSE_POLICY_EXPIRES_AT if reuse_allowed else None,
            "rights_reason": (
                "page_and_terms_confirm_ogl_v3_text_only" if reuse_allowed
                else "page_bound_reuse_terms_not_verified"
            ),
        }


def capture_import_sources(import_id: UUID) -> dict[str, Any]:
    """Capture only exact reviewed URLs and append source-bound provenance events."""
    with connection() as conn:
        row = conn.execute(
            "SELECT id,sources,claims FROM external_content_imports WHERE id=%s",
            (import_id,),
        ).fetchone()
        if row is None:
            raise ValueError("scheduled_import_not_found")
        sources = row["sources"] or []
        claims = row["claims"] or []

    run_id = uuid4()
    outcomes: list[dict[str, Any]] = []
    for source in sources:
        source_id = str(source.get("source_id") or "")
        source_url = str(source.get("url") or "")
        catalog = _catalog_entry(source_url)
        if not catalog:
            outcomes.append({"source_id": source_id, "status": "not_in_reviewed_catalog"})
            with connection() as conn:
                conn.execute("INSERT INTO audit_events(event_type,payload) VALUES ('research.source.live_document_capture_failed',%s)",
                             (Jsonb({'import_id':str(import_id), 'source_id':source_id,
                                     'source_url':source_url, 'status':'not_in_reviewed_catalog',
                                     'http_attempted':False, 'policy_version':CAPTURE_POLICY_VERSION}),))
            continue
        with connection() as conn:
            recent = conn.execute(
                """SELECT payload FROM audit_events
                WHERE event_type='research.source.live_document_verified'
                  AND payload->>'import_id'=%s AND payload->>'source_id'=%s
                ORDER BY id DESC LIMIT 1""",
                (str(import_id), source_id),
            ).fetchone()
        if recent and recent["payload"].get("source_url") == source_url:
            age = None
            with connection() as conn:
                age_row = conn.execute(
                    "SELECT now()-created_at AS age FROM audit_events WHERE event_type='research.source.live_document_verified' AND payload->>'import_id'=%s AND payload->>'source_id'=%s ORDER BY id DESC LIMIT 1",
                    (str(import_id), source_id),
                ).fetchone()
                age = age_row["age"] if age_row else None
            if (age is not None and age.total_seconds() < 3600
                    and recent["payload"].get("policy_version") == CAPTURE_POLICY_VERSION):
                outcomes.append({"source_id": source_id, "status": "already_fresh",
                                 "source_body_sha256": recent["payload"].get("source_body_sha256")})
                continue

        proof = _fetch(source_url, run_id)
        proof["import_id"] = str(import_id)
        proof["source_id"] = source_id
        proof["source_url"] = source_url
        if proof.get("status") == "captured":
            attached_claims = [claim for claim in claims
                               if source_id in {str(x) for x in claim.get("source_ids", [])}]
            exact_evidence: list[str] = []
            fact_checks: list[dict[str, Any]] = []
            paragraphs = list(proof["paragraphs"])
            for claim in attached_claims:
                matched, fact_check = _claim_fact_check(claim, paragraphs)
                exact_evidence.extend(matched)
                fact_checks.append(fact_check)
            proof["verified_claim_evidence"] = sorted(set(exact_evidence))
            proof["fact_checks"] = fact_checks
            proof.pop("visible_text", None)
            proof.pop("paragraphs", None)
            proof["policy_version"] = CAPTURE_POLICY_VERSION
            proof["source_rights_status"] = proof.get("reuse_terms_status", "unknown")
            event_type = "research.source.live_document_verified"
        else:
            proof["policy_version"] = CAPTURE_POLICY_VERSION
            proof["live_write_performed"] = False
            event_type = "research.source.live_document_capture_failed"
        with connection() as conn:
            conn.execute(
                "INSERT INTO audit_events(event_type,payload) VALUES (%s,%s)",
                (event_type, Jsonb(proof)),
            )
        outcomes.append({"source_id": source_id, "status": proof.get("status"),
                         "source_body_sha256": proof.get("source_body_sha256"),
                         "source_title": proof.get("source_title"),
                         "source_published_at": proof.get("source_published_at"),
                         "rights_status": proof.get("reuse_terms_status"),
                         "exact_claims": sum(bool(item.get("evidence_excerpt_exactly_present"))
                                              for item in proof.get("fact_checks", []))})

    with connection() as conn:
        conn.execute(
            "INSERT INTO audit_events(event_type,payload) VALUES (%s,%s)",
            ("research.scheduled_source_capture.completed", Jsonb({
                "import_id": str(import_id), "run_id": str(run_id),
                "policy_version": CAPTURE_POLICY_VERSION,
                "source_count": len(sources), "captured_count": sum(x["status"] in {"captured", "already_fresh"} for x in outcomes),
                "outcomes": outcomes, "blogger_write_performed": False,
            })),
        )
    return {"import_id": str(import_id), "run_id": str(run_id), "outcomes": outcomes,
            "blogger_write_performed": False, "auto_eligible": False}
