"""Persistent Blogger write suspension, independent of historical approvals."""

import psycopg

from .db import connection


def manual_requests_allowed() -> bool:
    """Only after the actual Google restriction and emergency stop are cleared."""
    try:
        with connection() as conn:
            from .automation_controls import read
            if not read(conn)['manual_publishing_enabled']:
                return False
            row = conn.execute(
                "SELECT blogger_write_mode,blogger_api_restricted,emergency_stopped FROM publication_mode_settings "
                "WHERE scope_type='global' AND scope_key=''"
            ).fetchone()
            if not row or row['blogger_api_restricted'] or row['emergency_stopped']:
                return False
            if row['blogger_write_mode'] == 'manual_only':
                return True
            if row['blogger_write_mode'] != 'public_write_approved':
                return False
            from .automation_controls import read
            controls = read(conn)
            from .external_policy import _blogger_public_publish_approval
            approval = _blogger_public_publish_approval()
            return bool(
                controls['auto_publishing_enabled']
                and controls['automatic_publication_operator_approved']
                and controls['auto_mode'] == 'publish'
                and approval
                and sorted(approval['approved_blog_ids'])
                    == sorted(str(value) for value in controls['auto_blog_ids'])
            )
    except (psycopg.Error, OSError, RuntimeError):
        return False


def blogger_writes_allowed() -> bool:
    """A fresh persisted exact-version user request is required at the wire."""
    from .external_policy import _manual_publication_approval

    approval = _manual_publication_approval.get()
    from .automation_auto import AUTO_JOB, context_allowed
    if AUTO_JOB.get():
        try:
            return context_allowed()
        except (psycopg.Error,OSError,RuntimeError):
            return False
    if not approval or not manual_requests_allowed():
        return False
    try:
        with connection() as conn:
            from .automation_controls import job_permitted
            if not job_permitted(conn,approval[0],running=True):
                return False
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
