"""Test-only OAuth provider harness. Run only via smoke.py --mock-oauth."""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx
import psycopg
from cryptography.fernet import Fernet

os.environ["GOOGLE_CLIENT_ID"] = "mock-client"
os.environ["GOOGLE_CLIENT_SECRET"] = "mock-client-secret"
os.environ["TOKEN_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
from woori.config import settings

settings.cache_clear()
from woori import blogger_routes, blogger_service, google_oauth, main, multilingual
from woori.db import connection
from woori.google_http import READ_SCOPE
from woori.main import app

__all__ = ["app"]

_original = connection()
_conn = _original.__enter__()
_rollback = _conn.transaction(force_rollback=True)
_rollback.__enter__()


@contextmanager
def shared() -> Iterator[psycopg.Connection[dict[str, Any]]]:
    with _conn.transaction():
        yield _conn


for module in [google_oauth, blogger_service, blogger_routes, multilingual, main]:
    module.connection = shared


def provider(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/token":
        return httpx.Response(
            200,
            json={
                "access_token": "mock-smoke-access",
                "refresh_token": "mock-smoke-refresh",
                "scope": READ_SCOPE,
                "expires_in": 3600,
            },
        )
    return httpx.Response(200)


google_oauth.client = lambda: httpx.Client(transport=httpx.MockTransport(provider))
blogger_service.client = google_oauth.client
