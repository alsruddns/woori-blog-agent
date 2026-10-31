"""Current dispatch state is distinct from preserved historical Job status."""
from typing import Any


def pending_state(lane: str | None, approval_at: Any, cutoff: Any, permitted: bool) -> str:
    if lane != 'manual' or not approval_at or not cutoff or approval_at <= cutoff:
        return 'auto_paused'
    return 'queued' if permitted else 'manual_action_required'


def failure_resolved_clause(version: str, blog: str, imported: str) -> str:
    """Only a verified LIVE replacement in the same explicit import/localization resolves it."""
    return f"""NOT EXISTS (SELECT 1 FROM publishing_records resolved
        JOIN content_versions rv ON rv.id=resolved.content_version_id
        JOIN external_content_import_content_links rl ON rl.content_version_id=rv.id
        WHERE resolved.blog_id={blog} AND rl.import_id={imported}
        AND rv.group_id={version}.group_id
        AND rv.localization_id IS NOT DISTINCT FROM {version}.localization_id
        AND rv.version>={version}.version AND resolved.remote_status='LIVE'
        AND resolved.remote_verified_at IS NOT NULL)"""
