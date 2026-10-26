"""Zero-cost outbound policy: closed provider allowlist, hard quota stop, audited calls."""

from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from datetime import UTC, date, datetime
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
        "hosts": {"www.googleapis.com"}, "methods": {"GET"}, "rpm": 30,
        "rph": 120,
        "operations": {"blogger_read"},
        "paths": ("/blogger/v3/blogs", "/blogger/v3/users/self/blogs"),
        "cost": "readonly quota API; no per-call charge found; stop on provider quota",
        "commercial_use": "terms apply; review before monetized operation",
        "zero_cost_reviewed": False,
    },
    "google_oauth": {
        "hosts": {"oauth2.googleapis.com"}, "methods": {"POST"}, "rpm": 10,
        "rph": 20,
        "operations": {"oauth"},
        "paths": ("/token", "/revoke"),
        "cost": "OAuth token exchange/revocation; no separate call fee identified",
        "commercial_use": "Google OAuth terms and consent rules apply",
        "zero_cost_reviewed": True,
    },
    "federal_reserve": {
        "hosts": {"www.federalreserve.gov"}, "methods": {"GET"}, "rpm": 3,
        "rph": 24,
        "operations": {"source_collection"},
        "paths": ("/feeds/press_all.xml", "/newsevents/pressreleases/"),
        "cost": "public RSS/HTML; no account or API key; no provider fee identified",
        "commercial_use": "Board material subject to disclaimer; cite source, exclude third-party works",
        "zero_cost_reviewed": True,
    },
    "wikidata": {
        "hosts": {"www.wikidata.org"}, "methods": {"GET"}, "rpm": 10,
        "rph": 60,
        "operations": {"source_collection"}, "paths": ("/w/api.php",),
        "cost": "public API; no billing credential or paid tier used; hard-stop throttling",
        "commercial_use": "CC0 data; API policy/User-Agent and rate limits apply",
        "zero_cost_reviewed": True,
    },
    "artifact_setup": {
        "hosts": {
            "api.github.com", "github.com", "objects.githubusercontent.com",
            "release-assets.githubusercontent.com", "huggingface.co",
            "cdn-lfs.huggingface.co", "cas-bridge.xethub.hf.co",
            "us.aws.cdn.hf.co",
        },
        "methods": {"GET"},
        "rpm": 10,
        "rph": 20,
        "operations": {"artifact_download"},
        "paths_by_host": {
            "api.github.com": ("/repos/ggml-org/llama.cpp/releases/tags/b11889",),
            "github.com": ("/ggml-org/llama.cpp/releases/download/",),
            "huggingface.co": (
                "/api/models/Qwen/Qwen3-0.6B-GGUF/revision/",
                "/api/models/Qwen/Qwen3-1.7B-GGUF/revision/",
                "/api/models/Qwen/Qwen3-4B-GGUF/revision/",
                "/api/models/Qwen/Qwen3-8B-GGUF/revision/",
                "/Qwen/Qwen3-0.6B-GGUF/resolve/",
                "/Qwen/Qwen3-1.7B-GGUF/resolve/",
                "/Qwen/Qwen3-4B-GGUF/resolve/",
                "/Qwen/Qwen3-8B-GGUF/resolve/",
            ),
            "objects.githubusercontent.com": ("/",),
            "release-assets.githubusercontent.com": ("/",),
            "cdn-lfs.huggingface.co": ("/",),
            "cas-bridge.xethub.hf.co": ("/",),
            "us.aws.cdn.hf.co": ("/xet-bridge-us/",),
        },
        "cost": "unauthenticated public metadata/artifact download only; no hosted inference",
        "commercial_use": "only the pinned MIT engine and Apache-2.0 models; terms/limits apply",
        "zero_cost_reviewed": True,
    },
}

_BILLING_PREFIXES = (
    "OPENAI_", "ANTHROPIC_", "GEMINI_", "AWS_", "AZURE_", "STRIPE_", "PAYPAL_",
    "BILLING_", "PAYMENT_", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "PROXY_",
    "GOOGLE_CLOUD_", "GOOGLE_BILLING_", "CLOUD_BILLING_", "HUGGINGFACEHUB_",
)
_BILLING_NAMES = {
    "GOOGLE_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_CLOUD_PROJECT",
    "CLOUDSDK_CORE_PROJECT", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT",
    "COHERE_API_KEY", "MISTRAL_API_KEY", "DEEPSEEK_API_KEY", "GROQ_API_KEY",
    "HF_TOKEN", "HUGGINGFACE_HUB_TOKEN", "GITHUB_TOKEN",
    "FIRECRAWL_API_KEY", "SERPAPI_API_KEY", "TAVILY_API_KEY", "EXA_API_KEY",
    "SERPER_API_KEY", "BING_SEARCH_V7_SUBSCRIPTION_KEY", "NEWSAPI_KEY",
    "ALPHAVANTAGE_API_KEY", "POLYGON_API_KEY", "COINMARKETCAP_API_KEY",
    "REPLICATE_API_TOKEN", "TOGETHER_API_KEY", "PERPLEXITY_API_KEY",
}
_ROOT = Path(__file__).resolve().parents[3]
TERMS_REVIEWED_AT = date(2026, 10, 26)
TERMS_REVIEW_DUE = date(2027, 1, 26)
_lock = threading.Lock()
_windows: dict[tuple[str, int], deque[float]] = {}


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


def status() -> dict[str, Any]:
    blocked = billing_credential_names()
    review_due = datetime.now(UTC).date() > TERMS_REVIEW_DUE
    providers: list[dict[str, Any]] = []
    blocked_providers: list[dict[str, str]] = []
    for name, rule in sorted(PROVIDERS.items()):
        reason = (
            "potentially_billable_credentials_detected" if blocked
            else "external_terms_review_expired" if review_due
            else None if rule["zero_cost_reviewed"]
            else "manual_zero_cost_review_required"
        )
        allowed = reason is None
        providers.append({
            "name": name,
            "cost": rule["cost"],
            "usage_limit": (
                f"local hard caps {rule['rpm']} calls/minute and {rule['rph']} calls/hour; "
                "provider 429/quota stops immediately"
            ),
            "commercial_use": rule["commercial_use"],
            "calls_allowed": allowed,
            "block_reason": reason,
        })
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

    with connection() as conn:
        conn.execute(
            "INSERT INTO audit_events(event_type,payload) VALUES (%s,%s)",
            (f"external.{phase}", Jsonb({"provider": provider, "operation": operation, **fields})),
        )


def _deny(provider: str, operation: str, request: httpx.Request, reason: str) -> NoReturn:
    try:
        _audit(
            provider, operation, "call.blocked", host=request.url.host,
            method=request.method, reason=reason,
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
    if datetime.now(UTC).date() > TERMS_REVIEW_DUE:
        _deny(provider, operation, request, "external_terms_review_expired")
    parsed = request.url
    path_prefixes = rule.get("paths_by_host", {}).get(parsed.host, rule.get("paths", ()))
    if (
        parsed.scheme != "https"
        or parsed.host not in rule["hosts"]
        or parsed.port not in (None, 443)
        or request.method not in rule["methods"]
        or not any(parsed.path.startswith(prefix) for prefix in path_prefixes)
        or parsed.username
        or parsed.password
    ):
        _deny(provider, operation, request, "destination_or_method_not_allowlisted")
    if not rule["zero_cost_reviewed"]:
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
                if reasons.intersection({"quotaExceeded", "rateLimitExceeded", "userRateLimitExceeded"}):
                    response.close()
                    raise FreeQuotaExceeded("provider_free_quota_or_rate_limit")
                content = response.content
                headers = response.headers
                response.close()
                response = httpx.Response(
                    response.status_code, headers=headers, content=content,
                    request=request,
                )
            try:
                _audit(
                    self.provider, self.operation, "call.completed", host=request.url.host,
                    method=request.method, status=response.status_code,
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


def guarded_transport(provider: str, operation: str, inner: httpx.BaseTransport) -> httpx.BaseTransport:
    """Test seam for deterministic MockTransport tests; production uses client()."""
    if provider not in PROVIDERS or operation not in PROVIDERS[provider]["operations"]:
        raise ExternalCallBlocked("provider_not_allowlisted")
    return _GuardedTransport(provider, operation, inner)
