"""Mutation protocol tested ONLY through an in-memory MockTransport; no live write path."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

import httpx
from psycopg.types.json import Jsonb

from .db import connection
from .google_http import BASE, GoogleFailure, classify, numeric_id


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
