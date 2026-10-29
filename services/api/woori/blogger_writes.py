"""Blogger write adapters.

``BloggerWriter`` is a simulation-only adapter. ``BloggerLivePublisher`` is the
guarded production transport; it remains fail-closed unless an exact OAuth
connection is mapped to the blog and the append-only external policy permits
the requested operation. No caller should treat a mock result as a live post.
"""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from psycopg.types.json import Jsonb

from . import external_policy, google_oauth
from .db import connection
from .external_policy import ExternalCallBlocked, FreeQuotaExceeded
from .google_http import BASE, WRITE_SCOPE, GoogleFailure, classify, numeric_id


def _live_response(
    *,
    connection_id: UUID,
    operation: str,
    method: str,
    path: str,
    params: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    transport: httpx.MockTransport | None = None,
) -> tuple[dict[str, Any], int]:
    """Send one guarded Google request; injected transports are test-only."""
    if not path.startswith("/blogs/") or ".." in path or "?" in path:
        raise GoogleFailure("invalid_path")
    if transport is not None and not isinstance(transport, httpx.MockTransport):
        raise GoogleFailure("custom_live_transport_forbidden")
    try:
        if transport is None:
            client = external_policy.client(
                "google_blogger_read", operation, timeout=15, follow_redirects=False
            )
        else:
            client = httpx.Client(
                transport=external_policy.guarded_transport(
                    "google_blogger_read", operation, transport
                ),
                timeout=15,
                follow_redirects=False,
                trust_env=False,
            )
        with client:
            response = client.request(
                method,
                BASE + path,
                params=params,
                json=body,
                headers={"Authorization": "Bearer " + google_oauth.access_token(connection_id)},
            )
    except FreeQuotaExceeded:
        raise GoogleFailure("free_quota_exceeded") from None
    except ExternalCallBlocked as exc:
        raise GoogleFailure(str(exc)) from None
    except GoogleFailure:
        raise
    except httpx.TransportError:
        raise GoogleFailure("uncertain_write") from None
    if not response.is_success:
        category = classify(response)
        if method != "GET" and (response.status_code >= 500 or category == "unavailable"):
            category = "uncertain_write"
        raise GoogleFailure(category, response.status_code)
    try:
        payload = response.json()
    except ValueError:
        raise GoogleFailure("invalid_response", response.status_code) from None
    if not isinstance(payload, dict):
        raise GoogleFailure("invalid_response", response.status_code)
    return payload, response.status_code


class BloggerLivePublisher:
    """Guarded Blogger v3 draft/publication calls with durable idempotency.

    The registered blog must already be mapped to the exact connected write
    OAuth connection. Draft creation is governed by the existing private-draft
    approval. Publishing a draft requires a separate policy scope that is not
    present in the current owner attestation, so the current environment blocks
    it before any network request.
    """

    def __init__(self, transport: httpx.MockTransport | None = None) -> None:
        if transport is not None and not isinstance(transport, httpx.MockTransport):
            raise GoogleFailure("custom_live_transport_forbidden")
        self._transport = transport

    @staticmethod
    def _target(blog_record_id: UUID) -> dict[str, Any]:
        with connection() as conn:
            row = conn.execute(
                """SELECT b.id,b.language_code,b.url,b.blog_id,b.active,
                    b.oauth_connection_id,g.status AS oauth_status,g.scopes
                FROM blogger_blogs b LEFT JOIN google_connections g
                  ON g.id=b.oauth_connection_id WHERE b.id=%s""",
                (blog_record_id,),
            ).fetchone()
        if row is None or not row["active"]:
            raise GoogleFailure("blog_not_active")
        if not row["blog_id"] or not row["oauth_connection_id"]:
            raise GoogleFailure("write_oauth_not_mapped_to_blog")
        if row["oauth_status"] != "connected":
            raise GoogleFailure("oauth_not_connected")
        if list(row["scopes"] or []) != [WRITE_SCOPE]:
            raise GoogleFailure("write_scope_required")
        return {**dict(row), "blog_id": numeric_id(str(row["blog_id"]))}

    @staticmethod
    def _fingerprint(operation: str, blog_id: str, payload: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps([operation, blog_id, payload], ensure_ascii=False, sort_keys=True).encode(
                "utf-8"
            )
        ).hexdigest()

    @staticmethod
    def _claim(key: str, operation: str, fingerprint: str) -> dict[str, Any] | None:
        if not key or len(key) > 128:
            raise GoogleFailure("invalid_idempotency_key")
        durable_key = "live:" + key
        with connection() as conn:
            inserted = conn.execute(
                """INSERT INTO blogger_write_operations
                    (idempotency_key,request_fingerprint,operation,status)
                VALUES (%s,%s,%s,'pending') ON CONFLICT DO NOTHING
                RETURNING idempotency_key""",
                (durable_key, fingerprint, operation),
            ).fetchone()
            if inserted is None:
                existing = conn.execute(
                    "SELECT request_fingerprint,status,result FROM blogger_write_operations WHERE idempotency_key=%s FOR UPDATE",
                    (durable_key,),
                ).fetchone()
                if existing is None:
                    raise GoogleFailure("idempotency_ledger_unavailable")
                if existing["request_fingerprint"] != fingerprint:
                    raise GoogleFailure("idempotency_key_payload_conflict")
                if existing["status"] == "succeeded":
                    result = existing["result"] or {}
                    return dict(result)
                raise GoogleFailure("previous_write_pending_or_uncertain")
            conn.execute(
                "INSERT INTO audit_events(event_type,payload) VALUES ('blogger.write.requested',%s)",
                (Jsonb({"operation": operation, "mode": "live", "idempotency_key_hash": hashlib.sha256(durable_key.encode()).hexdigest()}),),
            )
        return None

    @staticmethod
    def _finish(
        key: str, operation: str, outcome: str, result: dict[str, Any] | None,
        category: str | None, http_status: int | None,
    ) -> None:
        durable_key = "live:" + key
        with connection() as conn:
            conn.execute(
                "UPDATE blogger_write_operations SET status=%s,result=%s WHERE idempotency_key=%s AND status='pending'",
                (outcome, Jsonb(result) if result else None, durable_key),
            )
            conn.execute(
                "INSERT INTO audit_events(event_type,payload) VALUES (%s,%s)",
                (
                    "blogger.write." + ("succeeded" if outcome == "succeeded" else outcome),
                    Jsonb({"operation": operation, "mode": "live", "category": category,
                           "http_status": http_status,
                           "post_id": result.get("post_id") if result else None,
                           "blog_id": result.get("blog_id") if result else None}),
                ),
            )

    def _verify_target(self, target: dict[str, Any]) -> None:
        blog, status = _live_response(
            connection_id=target["oauth_connection_id"], operation="blogger_read",
            method="GET", path=f"/blogs/{target['blog_id']}", transport=self._transport,
        )
        expected_host = (urlsplit(str(target["url"])).hostname or "").casefold()
        actual_host = (urlsplit(str(blog.get("url", ""))).hostname or "").casefold()
        if (str(blog.get("id")) != target["blog_id"] or not expected_host
                or actual_host != expected_host):
            raise GoogleFailure("blog_identity_mismatch", status)

    def create_draft(
        self, key: str, blog_record_id: UUID, title: str, html: str,
        labels: list[str] | None = None,
    ) -> dict[str, Any]:
        target = self._target(blog_record_id)
        if not title.strip() or not html.strip() or len(title) > 300 or len(html) > 200_000:
            raise GoogleFailure("invalid_post_payload")
        payload: dict[str, Any] = {"title": title, "content": html}
        if labels:
            if len(labels) > 10 or any(not label.strip() or len(label) > 100 for label in labels):
                raise GoogleFailure("invalid_labels")
            payload["labels"] = labels
        fingerprint = self._fingerprint("create_draft", target["blog_id"], payload)
        previous = self._claim(key, "create_draft", fingerprint)
        if previous is not None:
            return previous
        try:
            self._verify_target(target)
            data, status = _live_response(
                connection_id=target["oauth_connection_id"], operation="blogger_draft_create",
                method="POST", path=f"/blogs/{target['blog_id']}/posts",
                params={"isDraft": "true"}, body=payload, transport=self._transport,
            )
            post_id = numeric_id(str(data.get("id", "")))
            if str((data.get("blog") or {}).get("id", "")) != target["blog_id"]:
                raise GoogleFailure("blogger_response_blog_mismatch", status)
            if data.get("status") not in (None, "DRAFT"):
                raise GoogleFailure("draft_status_mismatch", status)
            result = {"post_id": post_id, "blog_id": target["blog_id"],
                      "url": None, "status": "DRAFT", "created_at": data.get("published"),
                      "http_status": status, "live": True, "simulation_only": False,
                      "post_verified": False}
            verified, verify_status = _live_response(
                connection_id=target["oauth_connection_id"], operation="blogger_read",
                method="GET", path=f"/blogs/{target['blog_id']}/posts/{post_id}",
                transport=self._transport,
            )
            if (numeric_id(str(verified.get("id", ""))) != post_id
                    or str((verified.get("blog") or {}).get("id", "")) != target["blog_id"]
                    or verified.get("status") != "DRAFT"):
                raise GoogleFailure("draft_readback_mismatch", verify_status)
            result["post_verified"] = True
            result["readback_http_status"] = verify_status
            self._finish(key, "create_draft", "succeeded", result, None, status)
            return result
        except GoogleFailure as exc:
            uncertain = exc.category in {"uncertain_write", "audit_unavailable_after_call"}
            self._finish(key, "create_draft", "uncertain" if uncertain else "failed",
                         None, exc.category, exc.status)
            raise

    def publish_draft(
        self, key: str, blog_record_id: UUID, post_id: str, *,
        source_draft_key: str,
    ) -> dict[str, Any]:
        target = self._target(blog_record_id)
        post_id = numeric_id(post_id)
        with connection() as conn:
            prior = conn.execute(
                """SELECT 1 FROM blogger_write_operations
                WHERE idempotency_key=%s AND operation='create_draft' AND status='succeeded'
                  AND result->>'post_id'=%s AND result->>'blog_id'=%s""",
                ("live:" + source_draft_key, post_id, target["blog_id"]),
            ).fetchone()
        if prior is None:
            raise GoogleFailure("verified_local_draft_required")
        fingerprint = self._fingerprint("publish_draft", target["blog_id"], {"post_id": post_id})
        previous = self._claim(key, "publish_draft", fingerprint)
        if previous is not None:
            return previous
        try:
            self._verify_target(target)
            data, status = _live_response(
                connection_id=target["oauth_connection_id"], operation="blogger_public_publish",
                method="POST", path=f"/blogs/{target['blog_id']}/posts/{post_id}/publish",
                transport=self._transport,
            )
            if str((data.get("blog") or {}).get("id", "")) != target["blog_id"]:
                raise GoogleFailure("blogger_response_blog_mismatch", status)
            url = str(data.get("url", ""))
            if (urlsplit(url).scheme != "https"
                    or (urlsplit(url).hostname or "").casefold()
                    != (urlsplit(str(target["url"])).hostname or "").casefold()):
                raise GoogleFailure("published_url_invalid", status)
            result = {"post_id": post_id, "blog_id": target["blog_id"], "url": url,
                      "status": str(data.get("status") or "LIVE"),
                      "published_at": data.get("published"), "http_status": status,
                      "live": True, "simulation_only": False}
            self._finish(key, "publish_draft", "succeeded", result, None, status)
            return result
        except GoogleFailure as exc:
            uncertain = exc.category in {"uncertain_write", "audit_unavailable_after_call"}
            self._finish(key, "publish_draft", "uncertain" if uncertain else "failed",
                         None, exc.category, exc.status)
            raise


class BloggerWriter:
    def __init__(self, transport: httpx.MockTransport | None = None) -> None:
        if not isinstance(transport, httpx.MockTransport):
            raise GoogleFailure("production_writes_disabled")
        self.transport = transport

    def mutate(
        self,
        key: str,
        operation: str,
        blog_id: str,
        post_id: str = "",
        body: dict[str, Any] | None = None,
        publish_date: str = "",
    ) -> dict[str, Any]:
        blog_id = numeric_id(blog_id)
        path = f"/blogs/{blog_id}/posts"
        params: dict[str, str] = {}
        if operation == "create_draft":
            method = "POST"
            params = {"isDraft": "true"}
        elif operation in ("publish", "schedule"):
            method = "POST"
            path += f"/{numeric_id(post_id)}/publish"
            if operation == "schedule":
                try:
                    date = datetime.fromisoformat(publish_date)
                except ValueError:
                    raise GoogleFailure("invalid_schedule") from None
                if date.tzinfo is None or date <= datetime.now(UTC):
                    raise GoogleFailure("invalid_schedule")
                params = {"publishDate": date.isoformat()}
        elif operation == "update":
            method = "PATCH"
            path += f"/{numeric_id(post_id)}"
        elif operation == "delete":
            method = "DELETE"
            path += f"/{numeric_id(post_id)}"
        else:
            raise GoogleFailure("invalid_operation")
        if not key or len(key) > 128:
            raise GoogleFailure("invalid_idempotency_key")
        fingerprint = hashlib.sha256(
            json.dumps([method, path, params, body], sort_keys=True).encode()
        ).hexdigest()
        blocked = False
        previous: dict[str, Any] | None = None
        ledger_key = "mock:" + key
        with connection() as conn:
            row = conn.execute(
                "INSERT INTO blogger_write_operations(idempotency_key,request_fingerprint,operation,status) VALUES (%s,%s,%s,'pending') ON CONFLICT DO NOTHING RETURNING idempotency_key",
                (ledger_key, fingerprint, operation),
            ).fetchone()
            if row is None:
                row = conn.execute(
                    "SELECT * FROM blogger_write_operations WHERE idempotency_key=%s", (ledger_key,)
                ).fetchone()
                assert row is not None
                if row["request_fingerprint"] == fingerprint and row["status"] == "succeeded":
                    previous = row["result"]
                blocked = True
                conn.execute(
                    "INSERT INTO audit_events(event_type,payload) VALUES ('blogger.write.duplicate_blocked',%s)",
                    (Jsonb({"operation": operation, "mode": "mock"}),),
                )
            else:
                conn.execute(
                    "INSERT INTO audit_events(event_type,payload) VALUES ('blogger.write.requested',%s)",
                    (Jsonb({"operation": operation, "mode": "mock"}),),
                )
        if blocked:
            if previous is not None:
                return previous
            raise GoogleFailure("duplicate_or_uncertain_write_blocked")
        failure: GoogleFailure | None = None
        result: dict[str, Any] = {}
        try:
            with httpx.Client(transport=self.transport, follow_redirects=False) as mock:
                response = mock.request(method, BASE + path, params=params, json=body)
            if not response.is_success:
                raise GoogleFailure(classify(response), response.status_code)
            result = {} if response.status_code == 204 else response.json()
            if not isinstance(result, dict):
                raise TypeError
        except httpx.TransportError:
            failure = GoogleFailure("uncertain_write")
        except (ValueError, TypeError, GoogleFailure) as exc:
            failure = exc if isinstance(exc, GoogleFailure) else GoogleFailure("uncertain_write")
        with connection() as conn:
            conn.execute(
                "UPDATE blogger_write_operations SET status=%s,result=%s WHERE idempotency_key=%s",
                (
                    "uncertain" if failure else "succeeded",
                    Jsonb(result) if not failure else None,
                    ledger_key,
                ),
            )
            conn.execute(
                "INSERT INTO audit_events(event_type,payload) VALUES (%s,%s)",
                (
                    "blogger.write.failed" if failure else "blogger.write.succeeded",
                    Jsonb(
                        {
                            "operation": operation,
                            "mode": "mock",
                            "category": failure.category if failure else None,
                        }
                    ),
                ),
            )
        if failure:
            raise failure
        return result

    def create_draft(self, key: str, blog_id: str, title: str, content: str) -> dict[str, Any]:
        return self.mutate(key, "create_draft", blog_id, body={"title": title, "content": content})

    def publish(self, key: str, blog_id: str, post_id: str) -> dict[str, Any]:
        return self.mutate(key, "publish", blog_id, post_id)

    def schedule(self, key: str, blog_id: str, post_id: str, publish_date: str) -> dict[str, Any]:
        return self.mutate(key, "schedule", blog_id, post_id, publish_date=publish_date)

    def update(
        self, key: str, blog_id: str, post_id: str, title: str, content: str
    ) -> dict[str, Any]:
        return self.mutate(key, "update", blog_id, post_id, {"title": title, "content": content})

    def delete(self, key: str, blog_id: str, post_id: str) -> dict[str, Any]:
        return self.mutate(key, "delete", blog_id, post_id)
