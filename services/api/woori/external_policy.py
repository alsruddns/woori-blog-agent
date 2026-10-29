"""Zero-cost outbound policy: closed provider allowlist, hard quota stop, audited calls."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, NoReturn

import httpx
import psycopg


class ExternalCallBlocked(RuntimeError):
    pass


class FreeQuotaExceeded(httpx.TransportError):
    """A provider throttled the free allocation; do not retry or switch providers."""


# Hosts, methods and per-minute local caps are intentionally closed. Pricing is
# reviewed in docs/operations/zero-cost-policy.md; no provider may use auto-billing.
PROVIDERS: dict[str, dict[str, Any]] = {
    "google_blogger_read": {
        "hosts": {"www.googleapis.com"},
        "methods": {"GET", "POST", "PATCH", "PUT"},
        "rpm": 30,
        "rph": 120,
        "operations": {
            "blogger_read",
            "blogger_draft_create",
            "blogger_post_update",
            "blogger_public_publish",
        },
        "paths": (
            "/blogger/v3/blogs",
            "/blogger/v3/users/self",
            "/blogger/v3/users/self/blogs",
        ),
        "cost": "Blogger-specific project-owner attestation required; current policy approval is read from append-only audit history",
        "commercial_use": "terms apply; review before monetized operation",
        "zero_cost_reviewed": False,
    },
    "google_oauth": {
        "hosts": {"oauth2.googleapis.com"},
        "methods": {"POST"},
        "rpm": 10,
        "rph": 20,
        "operations": {"oauth"},
        "paths": ("/token", "/revoke"),
        "cost": "OAuth token exchange/revocation; no separate call fee identified",
        "commercial_use": "Google OAuth terms and consent rules apply",
        "zero_cost_reviewed": True,
    },
    "federal_reserve": {
        "hosts": {"www.federalreserve.gov"},
        "methods": {"GET"},
        "rpm": 3,
        "rph": 24,
        "operations": {"source_collection"},
        "paths": ("/feeds/press_all.xml", "/newsevents/pressreleases/"),
        "cost": "public RSS/HTML; no account or API key; no provider fee identified",
        "commercial_use": "Board material subject to disclaimer; cite source, exclude third-party works",
        "zero_cost_reviewed": True,
    },
    "sec_edgar": {
        "hosts": {"data.sec.gov"},
        "methods": {"GET"},
        "rpm": 3,
        "rph": 24,
        "operations": {"source_collection"},
        "paths_by_host": {
            "data.sec.gov": ("/submissions/CIK", "/api/xbrl/companyconcept/CIK"),
        },
        "cost": "public EDGAR submissions and companyfacts JSON; no key or per-call fee identified",
        "commercial_use": "SEC states government-created sec.gov and EDGAR public filing content may be reused; filing source must be cited",
        "zero_cost_reviewed": True,
    },
    "wikidata": {
        "hosts": {"www.wikidata.org"},
        "methods": {"GET"},
        "rpm": 10,
        "rph": 60,
        "operations": {"source_collection"},
        "paths": ("/w/api.php",),
        "cost": "public API; no billing credential or paid tier used; hard-stop throttling",
        "commercial_use": "CC0 data; API policy/User-Agent and rate limits apply",
        "zero_cost_reviewed": True,
    },
    "google_trends_rss": {
        "hosts": {"trends.google.com"},
        "methods": {"GET"},
        "rpm": 1,
        "rph": 12,
        "operations": {"trend_collection"},
        "paths": ("/trending/rss",),
        "cost": "Google Trends public RSS export; no key, metered API, or billing account used; application hard caps apply",
        "commercial_use": "Google Trends help documents RSS export; preserve trend attribution and Google terms; no search-volume ranks are inferred",
        "zero_cost_reviewed": True,
    },
    "taiwan_official_documents": {
        "hosts": {"www.ey.gov.tw", "www.ly.gov.tw"},
        "methods": {"GET"},
        "rpm": 8,
        "rph": 8,
        "operations": {"source_collection"},
        "paths_by_host": {
            "www.ey.gov.tw": (
                "/robots.txt", "/Page/448DE008087A1971/5020ed44-2196-4da0-9dbe-fe6ae7f44afc",
                "/Page/9277F759E41CCD91/e6b90fcf-0d42-40e3-b001-1c790c076657", "/Page/2EADDBFEDDB6357E",
            ),
            "www.ly.gov.tw": ("/robots.txt", "/Pages/List.aspx", "/Pages/Detail.aspx"),
        },
        "cost": "public official web pages; no key, account, or per-request fee identified; low bounded GET quota",
        "commercial_use": "EY and LY reuse notices permit attributed reuse subject to stated exceptions; rights and semantic review remain required",
        "zero_cost_reviewed": True,
    },
    "japan_energy_subsidy_site": {
        "hosts": {"www.nenryo-teigakuhikisage.go.jp"},
        "methods": {"GET"},
        "rpm": 2,
        "rph": 12,
        "operations": {"source_collection"},
        "paths_by_host": {"www.nenryo-teigakuhikisage.go.jp": ("/",)},
        "cost": "One public government campaign page; no key, account, paywall, or per-request API fee identified; bounded local limits",
        "commercial_use": "Campaign page has no visible reuse notice in the checked content; rights stay unknown unless a governing reuse notice is confirmed",
        "zero_cost_reviewed": True,
    },
    "ons_official_statistics": {
        "hosts": {"www.ons.gov.uk"},
        "methods": {"GET"},
        "rpm": 3,
        "rph": 6,
        "operations": {"source_collection"},
        "paths_by_host": {
            "www.ons.gov.uk": (
                "/economy/governmentpublicsectorandtaxes/publicsectorfinance/bulletins/publicsectorfinances/september2026",
                "/help/terms-conditions",
            ),
        },
        "cost": "Public ONS bulletin and terms pages; no key, account, or per-request API fee identified; bounded GET quota",
        "commercial_use": "ONS bulletin explicitly states OGL v3.0 except where otherwise stated; exclude third-party images and confirm page-specific notices",
        "terms_reviewed_at": "2026-10-29",
        "terms_review_due": "2027-01-29",
        "zero_cost_reviewed": True,
    },
}

_BILLING_PREFIXES = (
    "OPENAI_",
    "ANTHROPIC_",
    "GEMINI_",
    "AWS_",
    "AZURE_",
    "STRIPE_",
    "PAYPAL_",
    "BILLING_",
    "PAYMENT_",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "PROXY_",
    "GOOGLE_CLOUD_",
    "GOOGLE_BILLING_",
    "CLOUD_BILLING_",
    "HUGGINGFACEHUB_",
)
_BILLING_NAMES = {
    "GOOGLE_API_KEY",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GOOGLE_CLOUD_PROJECT",
    "CLOUDSDK_CORE_PROJECT",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_ENDPOINT",
    "COHERE_API_KEY",
    "MISTRAL_API_KEY",
    "DEEPSEEK_API_KEY",
    "GROQ_API_KEY",
    "HF_TOKEN",
    "HUGGINGFACE_HUB_TOKEN",
    "GITHUB_TOKEN",
    "FIRECRAWL_API_KEY",
    "SERPAPI_API_KEY",
    "TAVILY_API_KEY",
    "EXA_API_KEY",
    "SERPER_API_KEY",
    "BING_SEARCH_V7_SUBSCRIPTION_KEY",
    "NEWSAPI_KEY",
    "ALPHAVANTAGE_API_KEY",
    "POLYGON_API_KEY",
    "COINMARKETCAP_API_KEY",
    "REPLICATE_API_TOKEN",
    "TOGETHER_API_KEY",
    "PERPLEXITY_API_KEY",
}
_ROOT = Path(__file__).resolve().parents[3]
TERMS_REVIEWED_AT = date(2026, 10, 26)
TERMS_REVIEW_DUE = date(2027, 1, 26)
_lock = threading.Lock()
_windows: dict[tuple[str, int], deque[float]] = {}
_external_run_id: ContextVar[str | None] = ContextVar("external_run_id", default=None)
_scheduled_publication_blog_id: ContextVar[str | None] = ContextVar(
    "scheduled_publication_blog_id", default=None
)


@contextmanager
def external_run(run_id: str) -> Iterator[None]:
    token = _external_run_id.set(run_id)
    try:
        yield
    finally:
        _external_run_id.reset(token)


@contextmanager
def scheduled_publication_context(blog_id: str) -> Iterator[None]:
    """Scope a live-write approval check to the scheduled-only worker and one blog."""
    token = _scheduled_publication_blog_id.set(blog_id)
    try:
        yield
    finally:
        _scheduled_publication_blog_id.reset(token)


def _dotenv_names() -> dict[str, str]:
    """Return only nonempty suspicious variable names; never return their values."""
    values: dict[str, str] = {k: v for k, v in os.environ.items() if v.strip()}
    paths = [*_ROOT.glob(".env*"), *_ROOT.joinpath("apps/dashboard").glob(".env*")]
    for path in paths:
        if path.name.endswith((".example", ".sample", ".template")):
            continue
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.removeprefix("export ").strip()
                if value.strip().strip("\"'"):
                    values[key] = "present"
        except OSError:
            continue
    return values


def billing_credential_names() -> list[str]:
    return sorted(
        name
        for name, value in _dotenv_names().items()
        if value.strip()
        and (
            name in _BILLING_NAMES
            or name.startswith(_BILLING_PREFIXES)
            or name.endswith(("_API_KEY", "_API_TOKEN", "_ACCESS_KEY", "_SECRET_ACCESS_KEY"))
        )
    )


BLOGGER_APPROVAL_EVENT = "external.blogger.cost_policy.approved"
BLOGGER_REVOCATION_EVENT = "external.blogger.cost_policy.revoked"
BLOGGER_PUBLIC_APPROVAL_EVENT = "external.blogger.public_publish.approved"
BLOGGER_PUBLIC_REVOCATION_EVENT = "external.blogger.public_publish.revoked"
BLOGGER_APPROVAL_SCOPE = {
    "blogger_read",
    "private_draft_create",
    "user_approved_post_update",
}


def _blogger_policy_approval() -> dict[str, Any] | None:
    """Return the latest explicit Blogger-only owner attestation, fail-closed."""
    try:
        from .db import connection

        with connection() as conn:
            row = conn.execute(
                """SELECT event_type,payload,created_at FROM audit_events
                WHERE event_type IN (%s,%s) AND payload->>'provider'='google_blogger_read'
                ORDER BY id DESC LIMIT 1""",
                (BLOGGER_APPROVAL_EVENT, BLOGGER_REVOCATION_EVENT),
            ).fetchone()
    except (psycopg.Error, OSError):
        return None
    if (
        row is None
        or row["event_type"] != BLOGGER_APPROVAL_EVENT
        or row["payload"].get("policy_version") != 1
        or row["payload"].get("actor") != "project_owner_attestation_from_user_instruction"
        or row["payload"].get("evidence") != "PROJECT_OWNER_CONFIRMS_BLOGGER_API_ZERO_COST"
    ):
        return None
    approved_scope = row["payload"].get("approved_scope")
    if not isinstance(approved_scope, list) or set(approved_scope) != BLOGGER_APPROVAL_SCOPE:
        return None
    return {"created_at": row["created_at"], "scope": sorted(BLOGGER_APPROVAL_SCOPE)}


def _blogger_operation_is_approved(operation: str) -> bool:
    approval = _blogger_policy_approval()
    if approval is None:
        return False
    if operation == "blogger_public_publish":
        scoped_blog_id = _scheduled_publication_blog_id.get()
        if scoped_blog_id is not None:
            return _scheduled_publication_approval(scoped_blog_id) is not None
        return _blogger_public_publish_approval() is not None
    permitted = {
        "blogger_read": "blogger_read",
        "blogger_draft_create": "private_draft_create",
        "blogger_post_update": "user_approved_post_update",
        # Public publishing and unattended operation require a newer, distinct
        # append-only owner policy record. Existing approvals do not grant them.
        "blogger_public_publish": "public_post_publish",
    }
    return permitted.get(operation) in approval["scope"]


def _blogger_public_publish_approval() -> dict[str, Any] | None:
    """Require a separate append-only owner approval before public Blogger writes."""
    if _blogger_policy_approval() is None:
        return None
    try:
        from .db import connection

        with connection() as conn:
            row = conn.execute(
                """SELECT event_type,payload,created_at FROM audit_events
                WHERE event_type IN (%s,%s) AND payload->>'provider'='google_blogger_read'
                ORDER BY id DESC LIMIT 1""",
                (BLOGGER_PUBLIC_APPROVAL_EVENT, BLOGGER_PUBLIC_REVOCATION_EVENT),
            ).fetchone()
    except (psycopg.Error, OSError):
        return None
    if (
        row is None
        or row["event_type"] != BLOGGER_PUBLIC_APPROVAL_EVENT
        or row["payload"].get("policy_version") != 1
        or row["payload"].get("actor") != "project_owner_explicit_public_publish_approval"
        or row["payload"].get("evidence") != "I_APPROVE_BLOGGER_PUBLIC_PUBLISH"
        or row["payload"].get("approved_scope") != ["public_post_publish"]
    ):
        return None
    return {"created_at": row["created_at"], "scope": ["public_post_publish"]}


def _scheduled_publication_approval(blog_id: str) -> dict[str, Any] | None:
    """Scheduled approval is usable only inside its scoped worker context."""
    try:
        from .db import connection

        with connection() as conn:
            row = conn.execute(
                """SELECT approved_blog_ids,created_at FROM scheduled_publication_policy_events
                WHERE action='enabled' ORDER BY id DESC LIMIT 1"""
            ).fetchone()
    except (psycopg.Error, OSError):
        return None
    if not row or str(blog_id) not in {str(value) for value in row["approved_blog_ids"]}:
        return None
    return {"created_at": row["created_at"], "scope": ["scheduled_publication"]}


def status() -> dict[str, Any]:
    blocked = billing_credential_names()
    review_due = datetime.now(UTC).date() > TERMS_REVIEW_DUE
    providers: list[dict[str, Any]] = []
    blogger_approval = _blogger_policy_approval()
    blocked_providers: list[dict[str, str]] = []
    for name, rule in sorted(PROVIDERS.items()):
        blogger_reviewed = name == "google_blogger_read" and blogger_approval is not None
        approval_scope = blogger_approval["scope"] if blogger_approval else []
        approval_at = blogger_approval["created_at"].isoformat() if blogger_approval else None
        reason = (
            "potentially_billable_credentials_detected"
            if blocked
            else "external_terms_review_expired"
            if review_due
            else None
            if rule["zero_cost_reviewed"] or blogger_reviewed
            else "manual_zero_cost_review_required"
        )
        allowed = reason is None
        providers.append(
            {
                "name": name,
                "cost": rule["cost"],
                "usage_limit": (
                    f"local hard caps {rule['rpm']} calls/minute and {rule['rph']} calls/hour; "
                    "provider 429/quota stops immediately"
                ),
                "commercial_use": rule["commercial_use"],
                "calls_allowed": allowed,
                "block_reason": reason,
                "zero_cost_reviewed": bool(rule["zero_cost_reviewed"] or blogger_reviewed),
                "approval_scope": approval_scope if blogger_reviewed else [],
                "approval_at": approval_at if blogger_reviewed else None,
                "public_publish_approved": _blogger_public_publish_approval() is not None
                if name == "google_blogger_read" and blogger_reviewed else False,
            }
        )
        if not allowed:
            blocked_providers.append({"name": name, "reason": str(reason)})
    return {
        "policy": "zero_additional_cost",
        "external_calls_allowed": not blocked and not review_due,
        "blocked_credential_names": blocked,
        "providers": providers,
        "blocked_providers": blocked_providers,
        "paid_fallback": False,
        "automatic_paid_upgrade": False,
        "terms_reviewed_at": TERMS_REVIEWED_AT.isoformat(),
        "terms_review_due": TERMS_REVIEW_DUE.isoformat(),
        "review_expired": review_due,
    }


def _audit(provider: str, operation: str, phase: str, **fields: Any) -> None:
    # Store metadata only: never URL query strings, headers, bodies or credentials.
    from psycopg.types.json import Jsonb

    from .db import connection

    run_id = _external_run_id.get()
    payload = {"provider": provider, "operation": operation, **fields}
    if run_id:
        payload["run_id"] = run_id
    with connection() as conn:
        conn.execute(
            "INSERT INTO audit_events(event_type,payload) VALUES (%s,%s)",
            (f"external.{phase}", Jsonb(payload)),
        )


def _reserve_taiwan_official_call(host: str, method: str, hourly_limit: int) -> None:
    """Persist the rolling-hour reservation so restarting cannot reset its cap."""
    from psycopg.types.json import Jsonb

    from .db import connection

    with connection() as conn:
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            ("external-provider:taiwan_official_documents:rolling-hour",),
        )
        count = conn.execute(
            """SELECT count(*) AS n FROM audit_events
            WHERE event_type='external.call.started'
              AND payload->>'provider'='taiwan_official_documents'
              AND created_at >= now()-interval '1 hour'"""
        ).fetchone()
        if count is None or count["n"] >= hourly_limit:
            raise FreeQuotaExceeded("durable_free_hourly_call_limit_reached")
        conn.execute(
            "INSERT INTO audit_events(event_type,payload) VALUES (%s,%s)",
            ("external.call.started", Jsonb({"provider": "taiwan_official_documents", "operation": "source_collection", "host": host, "method": method, "run_id": _external_run_id.get()})),
        )


def _reserve_japan_energy_call(host: str, method: str, hourly_limit: int) -> None:
    """Persist the public microsite cap so restarts cannot reset this allowance."""
    from psycopg.types.json import Jsonb

    from .db import connection

    with connection() as conn:
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            ("external-provider:japan_energy_subsidy_site:rolling-hour",),
        )
        row = conn.execute(
            """SELECT count(*) FILTER (WHERE created_at>=now()-interval '1 hour') AS hour_count,
            max(created_at) AS last_call FROM audit_events
            WHERE event_type='external.call.started'
              AND payload->>'provider'='japan_energy_subsidy_site'"""
        ).fetchone()
        if row is None:
            raise ExternalCallBlocked("durable_provider_quota_state_unavailable")
        if int(row["hour_count"]) >= hourly_limit:
            raise FreeQuotaExceeded("durable_free_hourly_call_limit_reached")
        if row["last_call"] is not None:
            elapsed = conn.execute(
                "SELECT now()-%s AS age", (row["last_call"],)
            ).fetchone()
            if elapsed is None or elapsed["age"] < timedelta(seconds=30):
                raise ExternalCallBlocked("provider_minimum_spacing")
        payload: dict[str, Any] = {
            "provider": "japan_energy_subsidy_site",
            "operation": "source_collection",
            "host": host,
            "method": method,
        }
        if _external_run_id.get():
            payload["run_id"] = _external_run_id.get()
        conn.execute(
            "INSERT INTO audit_events(event_type,payload) VALUES ('external.call.started',%s)",
            (Jsonb(payload),),
        )


def _reserve_google_trends_call(host: str, method: str, operation: str) -> str | None:
    """Durably share RSS spacing and rolling-hour caps across every caller/process."""
    from psycopg.types.json import Jsonb

    from .db import connection

    with connection() as conn:
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            ("external-provider:google_trends_rss:rolling-caps",),
        )
        row = conn.execute(
            """SELECT count(*) FILTER (WHERE created_at>=now()-interval '1 hour') AS hour_count,
            min(created_at) FILTER (WHERE created_at>=now()-interval '1 hour') AS oldest_in_hour,
            max(created_at) AS last_call FROM audit_events
            WHERE event_type='external.call.started'
              AND payload->>'provider'='google_trends_rss'"""
        ).fetchone()
        if row is None:
            return "durable_quota_state_unavailable"
        if row["hour_count"] >= 12:
            return "durable_free_hourly_call_limit_reached"
        if row["last_call"] is not None:
            elapsed = conn.execute(
                "SELECT now()-%s AS age", (row["last_call"],)
            ).fetchone()
            if elapsed is None or elapsed["age"] < timedelta(minutes=5):
                return "provider_minimum_spacing"
        run_id = _external_run_id.get()
        last_collector_attempt = conn.execute(
            """SELECT max(attempted_at) AS last_attempt FROM trend_collection_attempts
            WHERE provider='google_trends_rss' AND (%s::text IS NULL OR id::text<>%s::text)""",
            (run_id, run_id),
        ).fetchone()
        if last_collector_attempt and last_collector_attempt["last_attempt"] is not None:
            elapsed = conn.execute(
                "SELECT now()-%s AS age", (last_collector_attempt["last_attempt"],)
            ).fetchone()
            if elapsed is None or elapsed["age"] < timedelta(minutes=5):
                return "provider_minimum_spacing"
        payload: dict[str, Any] = {
            "provider": "google_trends_rss",
            "operation": operation,
            "host": host,
            "method": method,
        }
        if run_id:
            payload["run_id"] = run_id
        conn.execute(
            "INSERT INTO audit_events(event_type,payload) VALUES ('external.call.started',%s)",
            (Jsonb(payload),),
        )
    return None


def _deny(provider: str, operation: str, request: httpx.Request, reason: str) -> NoReturn:
    try:
        _audit(
            provider,
            operation,
            "call.blocked",
            host=request.url.host,
            method=request.method,
            reason=reason,
        )
    except psycopg.Error:
        pass
    raise ExternalCallBlocked(reason)


def _authorize(provider: str, operation: str, request: httpx.Request) -> None:
    rule = PROVIDERS.get(provider)
    if rule is None:
        _deny(provider, operation, request, "provider_not_allowlisted")
    if billing_credential_names():
        _deny(provider, operation, request, "potentially_billable_credentials_detected")
    try:
        terms_review_due = date.fromisoformat(rule.get("terms_review_due", TERMS_REVIEW_DUE.isoformat()))
    except ValueError:
        _deny(provider, operation, request, "external_terms_review_date_invalid")
    if datetime.now(UTC).date() > terms_review_due:
        _deny(provider, operation, request, "external_terms_review_expired")
    parsed = request.url
    path_prefixes = rule.get("paths_by_host", {}).get(parsed.host, rule.get("paths", ()))
    method_allowed = request.method in rule["methods"]
    operation_path_allowed = any(parsed.path.startswith(prefix) for prefix in path_prefixes)
    if provider == "japan_energy_subsidy_site":
        operation_path_allowed = parsed.host == "www.nenryo-teigakuhikisage.go.jp" and parsed.path == "/" and not parsed.query
    if provider == "ons_official_statistics":
        operation_path_allowed = (
            parsed.host == "www.ons.gov.uk"
            and parsed.path in rule["paths_by_host"]["www.ons.gov.uk"]
            and not parsed.query
            and not parsed.fragment
        )
    if provider == "google_blogger_read":
        blog_id = r"[0-9]{1,40}"
        post_id = r"[0-9]{1,40}"
        path = parsed.path
        if operation == "blogger_read":
            method_allowed = request.method == "GET"
            operation_path_allowed = bool(
                path in ("/blogger/v3/users/self", "/blogger/v3/users/self/blogs")
                or re.fullmatch(rf"/blogger/v3/blogs/{blog_id}(?:/posts(?:/{post_id})?)?", path)
                or path == "/blogger/v3/blogs/byurl"
            )
        elif operation == "blogger_draft_create":
            params = list(request.url.params.multi_items())
            method_allowed = request.method == "POST"
            operation_path_allowed = bool(
                re.fullmatch(rf"/blogger/v3/blogs/{blog_id}/posts", path)
                and params == [("isDraft", "true")]
            )
        elif operation == "blogger_post_update":
            method_allowed = request.method in {"PATCH", "PUT"}
            operation_path_allowed = bool(
                re.fullmatch(rf"/blogger/v3/blogs/{blog_id}/posts/{post_id}", path)
                and not request.url.query
            )
        elif operation == "blogger_public_publish":
            method_allowed = request.method == "POST"
            operation_path_allowed = bool(
                re.fullmatch(
                    rf"/blogger/v3/blogs/{blog_id}/posts/{post_id}/publish", path
                )
                and not request.url.query
            )
        else:
            method_allowed = False
            operation_path_allowed = False
    elif provider == "google_trends_rss":
        method_allowed = request.method == "GET"
        trend_params = list(request.url.params.multi_items())
        operation_path_allowed = bool(
            parsed.path == "/trending/rss"
            and trend_params in [[("geo", code)] for code in ("KR", "US", "JP", "TW", "HK", "SG", "GB", "CA", "AU", "IN", "PH")]
        )
    if (
        parsed.scheme != "https"
        or parsed.host not in rule["hosts"]
        or parsed.port not in (None, 443)
        or not method_allowed
        or not operation_path_allowed
        or parsed.username
        or parsed.password
    ):
        _deny(provider, operation, request, "destination_or_method_not_allowlisted")
    if not rule["zero_cost_reviewed"] and not _blogger_operation_is_approved(operation):
        _deny(provider, operation, request, "provider_cost_unverified")
    # Per-process safety caps supplement durable application quotas. Provider 429
    # and quota errors remain hard stops; this limiter never sleeps or retries.
    now = time.monotonic()
    with _lock:
        for seconds, cap_key in ((60, "rpm"), (3600, "rph")):
            calls = _windows.setdefault((provider, seconds), deque())
            while calls and now - calls[0] >= seconds:
                calls.popleft()
            if len(calls) >= rule[cap_key]:
                raise FreeQuotaExceeded("local_free_call_limit_reached")
        for seconds in (60, 3600):
            _windows[(provider, seconds)].append(now)
    try:
        if provider == "taiwan_official_documents":
            _reserve_taiwan_official_call(parsed.host, request.method, rule["rph"])
        elif provider == "japan_energy_subsidy_site":
            _reserve_japan_energy_call(parsed.host, request.method, rule["rph"])
        elif provider == "google_trends_rss":
            block_reason = _reserve_google_trends_call(parsed.host, request.method, operation)
            if block_reason:
                _deny(provider, operation, request, block_reason)
        else:
            _audit(provider, operation, "call.started", host=parsed.host, method=request.method)
    except psycopg.Error:
        raise ExternalCallBlocked("audit_unavailable") from None


class _GuardedTransport(httpx.BaseTransport):
    def __init__(self, provider: str, operation: str, inner: httpx.BaseTransport | None = None):
        self.provider, self.operation = provider, operation
        self.inner = inner or httpx.HTTPTransport(retries=0)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        started = time.monotonic()
        try:
            _authorize(self.provider, self.operation, request)
            response = self.inner.handle_request(request)
            # Buffer only provider error responses so quota signals cannot be retried
            # by higher layers. Successful response bodies remain streaming.
            if response.status_code == 429:
                response.read()
                response.close()
                raise FreeQuotaExceeded("provider_free_quota_or_rate_limit")
            if response.status_code == 403:
                response.read()
                try:
                    body = json.loads(response.content)
                    reasons = {
                        e.get("reason")
                        for e in body.get("error", {}).get("errors", [])
                        if isinstance(e, dict)
                    }
                except (ValueError, AttributeError, TypeError):
                    reasons = set()
                if reasons.intersection(
                    {"quotaExceeded", "rateLimitExceeded", "userRateLimitExceeded"}
                ):
                    response.close()
                    raise FreeQuotaExceeded("provider_free_quota_or_rate_limit")
                content = response.content
                headers = response.headers
                response.close()
                response = httpx.Response(
                    response.status_code,
                    headers=headers,
                    content=content,
                    request=request,
                )
            try:
                _audit(
                    self.provider,
                    self.operation,
                    "call.completed",
                    host=request.url.host,
                    method=request.method,
                    status=response.status_code,
                    elapsed_ms=round((time.monotonic() - started) * 1000),
                    response_bytes=response.headers.get("content-length"),
                )
            except psycopg.Error:
                response.close()
                raise ExternalCallBlocked("audit_unavailable_after_call") from None
            return response
        except FreeQuotaExceeded:
            try:
                _audit(self.provider, self.operation, "call.quota_stopped", host=request.url.host)
            except psycopg.Error:
                pass
            raise

    def close(self) -> None:
        self.inner.close()


def client(provider: str, operation: str, **kwargs: Any) -> httpx.Client:
    if provider not in PROVIDERS or operation not in PROVIDERS[provider]["operations"]:
        raise ExternalCallBlocked("provider_not_allowlisted")
    if "transport" in kwargs:
        raise ExternalCallBlocked("custom_transport_not_allowed_for_live_calls")
    kwargs.setdefault("timeout", 15)
    kwargs.setdefault("follow_redirects", False)
    kwargs.setdefault("trust_env", False)
    return httpx.Client(transport=_GuardedTransport(provider, operation), **kwargs)


def guarded_transport(
    provider: str, operation: str, inner: httpx.BaseTransport
) -> httpx.BaseTransport:
    """Test seam for deterministic MockTransport tests; production uses client()."""
    if provider not in PROVIDERS or operation not in PROVIDERS[provider]["operations"]:
        raise ExternalCallBlocked("provider_not_allowlisted")
    return _GuardedTransport(provider, operation, inner)
