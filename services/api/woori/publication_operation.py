"""Persistent Blogger write suspension, independent of historical approvals."""

import psycopg

from .db import connection


def manual_requests_allowed() -> bool:
    """Only after the actual Google restriction and emergency stop are cleared."""
    try:
        with connection() as conn:
            row = conn.execute(
                "SELECT blogger_write_mode,blogger_api_restricted,emergency_stopped FROM publication_mode_settings "
                "WHERE scope_type='global' AND scope_key=''"
            ).fetchone()
            return bool(row and row['blogger_write_mode'] == 'manual_only'
                        and not row['blogger_api_restricted']
                        and not row['emergency_stopped'])
    except (psycopg.Error, OSError, RuntimeError):
        return False


def blogger_writes_allowed() -> bool:
    """A fresh persisted exact-version user request is required at the wire."""
    from .external_policy import _manual_publication_approval

    approval = _manual_publication_approval.get()
    if not approval or not manual_requests_allowed():
        return False
    try:
        with connection() as conn:
            return bool(conn.execute(
                """SELECT 1 FROM manual_publication_approval_events a
                JOIN publishing_jobs j ON j.id=a.job_id
                WHERE a.job_id=%s AND a.blog_id=%s AND a.content_version_id=%s
                AND a.title_sha256=%s AND a.body_sha256=%s AND a.html_sha256=%s
                AND j.publication_lane='manual' AND j.status='running'
                AND a.created_at>(SELECT max(created_at) FROM audit_events
                    WHERE event_type='publication.manual_only.activated')""", approval,
            ).fetchone())
    except (psycopg.Error, OSError, RuntimeError):
        return False
