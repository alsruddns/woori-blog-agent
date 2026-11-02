"""Group/blog manuscript disposal, independent of immutable content history."""

from __future__ import annotations

from typing import Any


def discarded(conn: Any, version_id: Any, blog_id: Any) -> bool:
    """A later version of a discarded manuscript stays blocked too."""
    return bool(conn.execute(
        """SELECT 1 FROM manuscript_discards d JOIN content_versions v ON v.group_id=d.group_id
        WHERE v.id=%s AND d.blog_id=%s AND d.status='discarded'""",
        (version_id, blog_id),
    ).fetchone())


def current(conn: Any, version_id: Any, blog_id: Any) -> dict[str, Any] | None:
    row = conn.execute(
        """SELECT v.group_id,v.id AS content_version_id,v.title,b.id AS blog_id,b.display_name AS blog_name,
          d.id AS discard_id,d.status AS discard_status,d.previous_view,d.reason,d.actor,d.discarded_at,d.restored_at
        FROM content_versions v JOIN content_localizations l ON l.id=v.localization_id
        JOIN blogger_blogs b ON b.id=%s AND b.language_code=l.language_code
        LEFT JOIN manuscript_discards d ON d.group_id=v.group_id AND d.blog_id=b.id
        WHERE v.id=%s""",
        (blog_id, version_id),
    ).fetchone()
    return dict(row) if row else None
