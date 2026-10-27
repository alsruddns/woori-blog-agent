"""Fixed Google endpoints, bounded read retries, metadata-only audit hooks."""

import random
import time
from collections.abc import Callable
from typing import Any

import httpx

from .external_policy import FreeQuotaExceeded
from .external_policy import client as external_client

BASE = "https://www.googleapis.com/blogger/v3"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
READ_SCOPE = "https://www.googleapis.com/auth/blogger.readonly"
WRITE_SCOPE = "https://www.googleapis.com/auth/blogger"


class GoogleFailure(RuntimeError):
    def __init__(self, category: str, status: int | None = None) -> None:
        self.category, self.status = category, status
        super().__init__(category)


def classify(response: httpx.Response) -> str:
    if response.status_code == 401:
        return "unauthorized"
    if response.status_code == 404:
        return "not_found"
    if response.status_code == 429:
        return "free_quota_exceeded"
    if response.status_code >= 500:
        return "unavailable"
    if response.status_code == 403:
        try:
            reasons = [e.get("reason") for e in response.json().get("error", {}).get("errors", [])]
        except (ValueError, AttributeError, TypeError):
            reasons = []
        return "free_quota_exceeded" if any(
            r in ("rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded")
            for r in reasons
        ) else "permission_denied"
    return "invalid_request"


def client() -> httpx.Client:
    return external_client("google_blogger_read", "blogger_read", timeout=15)


class BloggerReader:
    def __init__(
        self,
        transport: httpx.Client,
        token: Callable[[], str],
        audit: Callable[[str, int, str, int | None, str | None], None],
        pause: Callable[[float], None] = time.sleep,
    ) -> None:
        self.transport, self.token, self.audit, self.pause = transport, token, audit, pause

    def get(
        self, operation: str, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if (
            (not path.startswith("/blogs/") and path != "/users/self/blogs")
            or ".." in path
            or "?" in path
        ):
            raise GoogleFailure("invalid_path")
        for attempt in range(1, 4):
            self.audit(operation, attempt, "requested", None, None)
            try:
                response = self.transport.get(
                    BASE + path, params=params, headers={"Authorization": "Bearer " + self.token()}
                )
            except GoogleFailure as exc:
                self.audit(operation, attempt, "failed", exc.status, exc.category)
                raise
            except FreeQuotaExceeded:
                self.audit(operation, attempt, "failed", None, "free_quota_exceeded")
                raise GoogleFailure("free_quota_exceeded") from None
            except httpx.TransportError:
                category, status = "network", None
            else:
                if response.is_success:
                    try:
                        value = response.json()
                        if not isinstance(value, dict):
                            raise TypeError
                    except (ValueError, TypeError):
                        self.audit(
                            operation, attempt, "failed", response.status_code, "invalid_response"
                        )
                        raise GoogleFailure("invalid_response") from None
                    self.audit(operation, attempt, "succeeded", response.status_code, None)
                    return value
                category, status = classify(response), response.status_code
            self.audit(operation, attempt, "failed", status, category)
            if category not in ("unavailable", "network") or attempt == 3:
                raise GoogleFailure(category, status)
            self.audit(operation, attempt, "retry", status, category)
            retry_after = response.headers.get("Retry-After", "0") if status is not None else "0"
            delay = min(
                5.0,
                max(
                    2 ** (attempt - 1) + random.random(),
                    float(retry_after) if retry_after.isdigit() else 0,
                ),
            )
            self.pause(delay)
        raise GoogleFailure("unavailable")

    def blog_by_url(self, url: str) -> dict[str, Any]:
        return self.get("get_by_url", "/blogs/byurl", {"url": url})

    def account_blogs(self) -> dict[str, Any]:
        return self.get("list_account_blogs", "/users/self/blogs")

    def blog(self, blog_id: str) -> dict[str, Any]:
        return self.get("get_blog", f"/blogs/{numeric_id(blog_id)}")

    def posts(
        self, blog_id: str, limit: int = 20, page_token: str = "", status: str = "live"
    ) -> dict[str, Any]:
        if status not in ("live", "draft", "scheduled"):
            raise GoogleFailure("invalid_status")
        return self.get(
            "list_posts",
            f"/blogs/{numeric_id(blog_id)}/posts",
            {
                "maxResults": limit,
                **({"pageToken": page_token} if page_token else {}),
                "status": status,
                "fetchBodies": "false",
                "view": "AUTHOR",
            },
        )

    def post(self, blog_id: str, post_id: str) -> dict[str, Any]:
        return self.get("get_post", f"/blogs/{numeric_id(blog_id)}/posts/{numeric_id(post_id)}")


def numeric_id(value: str) -> str:
    if not value.isascii() or not value.isdecimal() or len(value) > 40:
        raise GoogleFailure("invalid_id")
    return value
