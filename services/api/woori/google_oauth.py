"""User-consented readonly OAuth with one-use state, browser binding and PKCE."""

import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

import httpx
import psycopg
from cryptography.fernet import Fernet, InvalidToken
from psycopg.types.json import Jsonb

from .config import settings
from .db import connection
from .external_policy import FreeQuotaExceeded
from .external_policy import client as external_client
from .google_http import READ_SCOPE, REVOKE_URL, TOKEN_URL, WRITE_SCOPE, GoogleFailure

ALLOWED_SCOPE_SETS = (frozenset({READ_SCOPE}), frozenset({WRITE_SCOPE}))


def client() -> httpx.Client:
    return external_client("google_oauth", "oauth")


def cipher() -> Fernet:
    try:
        return Fernet(settings().token_encryption_key.get_secret_value().encode())
    except (ValueError, TypeError):
        raise GoogleFailure("encryption_not_configured") from None


def encrypt(value: str) -> str:
    return cipher().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    try:
        return cipher().decrypt(value.encode()).decode()
    except (InvalidToken, UnicodeError):
        raise GoogleFailure("token_decryption_failed") from None


def configured() -> bool:
    return bool(
        settings().google_client_id
        and settings().google_client_secret.get_secret_value()
        and settings().token_encryption_key.get_secret_value()
    )


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def audit(
    conn: psycopg.Connection[dict[str, Any]],
    kind: str,
    connection_id: UUID,
    category: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO audit_events(event_type,payload) VALUES (%s,%s)",
        (kind, Jsonb({"connection_id": str(connection_id), "category": category})),
    )


def start(binding: str, label: str, permission: str = "read") -> dict[str, str]:
    if not configured():
        raise GoogleFailure("oauth_not_configured")
    if permission not in ("read", "write"):
        raise GoogleFailure("invalid_oauth_permission")
    requested_scopes = [READ_SCOPE] if permission == "read" else [WRITE_SCOPE]
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    with connection() as conn:
        row = conn.execute(
            "INSERT INTO google_connections(label) VALUES (%s) RETURNING id", (label,)
        ).fetchone()
        assert row is not None
        connection_id = row["id"]
        conn.execute(
            """INSERT INTO google_oauth_states(state_hash,binding_hash,connection_id,verifier_ciphertext,
            requested_scopes,expires_at) VALUES (%s,%s,%s,%s,%s,now()+interval '10 minutes')""",
            (digest(state), digest(binding), connection_id, encrypt(verifier), requested_scopes),
        )
        audit(conn, "oauth.started", connection_id, "write" if permission == "write" else "read")
    params = {
        "client_id": settings().google_client_id,
        "redirect_uri": settings().google_redirect_uri,
        "response_type": "code",
        "scope": " ".join(requested_scopes),
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "include_granted_scopes": "false",
    }
    return {
        "authorization_url": "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params),
        "connection_id": str(connection_id),
    }


def exchange(
    data: dict[str, str],
    transport: httpx.Client,
    expected_scopes: list[str] | tuple[str, ...] = (READ_SCOPE,),
    *,
    require_scope: bool = False,
) -> dict[str, Any]:
    data = {
        **data,
        "client_id": settings().google_client_id,
        "client_secret": settings().google_client_secret.get_secret_value(),
    }
    try:
        response = transport.post(TOKEN_URL, data=data)
    except FreeQuotaExceeded:
        raise GoogleFailure("free_quota_exceeded") from None
    except httpx.TransportError:
        raise GoogleFailure("oauth_network") from None
    try:
        body = response.json()
        if not isinstance(body, dict):
            raise TypeError
    except (ValueError, TypeError):
        raise GoogleFailure("oauth_invalid_response") from None
    if not response.is_success:
        category = "revoked" if body.get("error") == "invalid_grant" else "oauth_rejected"
        raise GoogleFailure(category, response.status_code)
    if not isinstance(body.get("access_token"), str) or not body["access_token"]:
        raise GoogleFailure("oauth_invalid_response")
    received_scope = body.get("scope")
    if received_scope is None and not require_scope:
        body["scope"] = " ".join(expected_scopes)
        received_scope = body["scope"]
    expected = frozenset(expected_scopes)
    if (
        not isinstance(received_scope, str)
        or frozenset(received_scope.split()) != expected
        or expected not in ALLOWED_SCOPE_SETS
    ):
        raise GoogleFailure("insufficient_or_excess_scope")
    try:
        lifetime = int(body["expires_in"])
        if not 60 <= lifetime <= 86400:
            raise TypeError
    except (KeyError, ValueError, TypeError):
        raise GoogleFailure("oauth_invalid_response") from None
    body["expires_at"] = datetime.now(UTC) + timedelta(seconds=lifetime)
    return body


def fail_connection(connection_id: UUID, category: str) -> None:
    with connection() as conn:
        conn.execute(
            """UPDATE google_connections SET status=%s,error_category=%s,
            access_ciphertext=NULL,refresh_ciphertext=NULL,updated_at=now() WHERE id=%s AND status!='disconnected'""",
            ("revoked" if category == "revoked" else "error", category, connection_id),
        )
        conn.execute(
            """UPDATE blogger_blogs SET connection_verified_at=NULL,test_publish_verified_at=NULL,
            connection_error=%s WHERE oauth_connection_id=%s""",
            (category, connection_id),
        )
        audit(conn, "oauth.failed", connection_id, category)


def callback(state: str, binding: str, code: str, denied: bool = False) -> UUID:
    with connection() as conn:
        row = conn.execute(
            """UPDATE google_oauth_states SET consumed=true
            WHERE state_hash=%s AND binding_hash=%s AND NOT consumed AND expires_at>now()
            RETURNING connection_id,verifier_ciphertext,requested_scopes""",
            (digest(state), digest(binding)),
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO audit_events(event_type,payload) VALUES ('oauth.state.rejected','{}')"
            )
    if row is None:
        raise GoogleFailure("invalid_oauth_state")
    connection_id = UUID(str(row["connection_id"]))
    if denied or not code:
        fail_connection(connection_id, "consent_denied")
        raise GoogleFailure("consent_denied")
    try:
        with client() as transport:
            body = exchange(
                {
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": settings().google_redirect_uri,
                    "code_verifier": decrypt(row["verifier_ciphertext"]),
                },
                transport,
                tuple(row["requested_scopes"]),
                require_scope=True,
            )
        if not isinstance(body.get("refresh_token"), str) or not body["refresh_token"]:
            raise GoogleFailure("refresh_token_missing")
        access, refresh = encrypt(body["access_token"]), encrypt(body["refresh_token"])
        with connection() as conn:
            saved = conn.execute(
                """UPDATE google_connections SET status='connected',access_ciphertext=%s,
                refresh_ciphertext=%s,expires_at=%s,scopes=%s,error_category=NULL,updated_at=now() WHERE id=%s AND status='pending' RETURNING id""",
                (access, refresh, body["expires_at"], body["scope"].split(), connection_id),
            )
            saved_row = saved.fetchone()
            audit(conn, "oauth.connected" if saved_row else "oauth.cancelled", connection_id)
        if not saved_row:
            with client() as transport:
                transport.post(REVOKE_URL, data={"token": body["refresh_token"]})
            raise GoogleFailure("oauth_flow_cancelled")
        return connection_id
    except GoogleFailure as exc:
        if exc.category != "oauth_flow_cancelled":
            fail_connection(connection_id, exc.category)
        raise


def access_token(connection_id: UUID, force: bool = False) -> str:
    failure: GoogleFailure | None = None
    token = ""
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM google_connections WHERE id=%s FOR UPDATE", (connection_id,)
        ).fetchone()
        if row is None or row["status"] != "connected":
            raise GoogleFailure("oauth_not_connected")
        try:
            if not force and row["expires_at"] > datetime.now(UTC) + timedelta(seconds=60):
                return decrypt(row["access_ciphertext"])
            with client() as transport:
                body = exchange(
                    {
                        "grant_type": "refresh_token",
                        "refresh_token": decrypt(row["refresh_ciphertext"]),
                    },
                    transport,
                    tuple(row["scopes"]),
                )
            token = body["access_token"]
            refresh = (
                encrypt(body["refresh_token"])
                if body.get("refresh_token")
                else row["refresh_ciphertext"]
            )
            conn.execute(
                """UPDATE google_connections SET access_ciphertext=%s,refresh_ciphertext=%s,
                expires_at=%s,error_category=NULL,updated_at=now() WHERE id=%s""",
                (encrypt(token), refresh, body["expires_at"], connection_id),
            )
            audit(conn, "oauth.refreshed", connection_id)
        except GoogleFailure as exc:
            failure = exc
            audit(conn, "oauth.refresh.failed", connection_id, exc.category)
    if failure:
        if failure.category in (
            "revoked",
            "oauth_rejected",
            "token_decryption_failed",
            "insufficient_or_excess_scope",
        ):
            fail_connection(connection_id, failure.category)
        raise failure
    return token


def disconnect(connection_id: UUID) -> dict[str, bool]:
    # Serialize revocation against refresh so a late refresh cannot reconnect a disconnected account.
    revoked = False
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM google_connections WHERE id=%s FOR UPDATE", (connection_id,)
        ).fetchone()
        if row is None:
            raise GoogleFailure("connection_not_found")
        try:
            token = row["refresh_ciphertext"] or row["access_ciphertext"]
            if token:
                with client() as transport:
                    response = transport.post(REVOKE_URL, data={"token": decrypt(token)})
                    revoked = response.is_success
            else:
                revoked = True
        except (httpx.TransportError, GoogleFailure):
            revoked = False
        conn.execute(
            """UPDATE google_connections SET status='disconnected',access_ciphertext=NULL,
            refresh_ciphertext=NULL,expires_at=NULL,error_category=%s,updated_at=now() WHERE id=%s""",
            (None if revoked else "remote_revocation_failed", connection_id),
        )
        conn.execute(
            """UPDATE blogger_blogs SET oauth_connection_id=NULL,connection_verified_at=NULL,
            test_publish_verified_at=NULL,connection_error=NULL WHERE oauth_connection_id=%s""",
            (connection_id,),
        )
        conn.execute(
            "UPDATE google_oauth_states SET consumed=true WHERE connection_id=%s", (connection_id,)
        )
        audit(
            conn,
            "oauth.disconnected",
            connection_id,
            None if revoked else "remote_revocation_failed",
        )
    return {"disconnected": True, "remote_revoked": revoked}
