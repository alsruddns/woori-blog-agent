"""Current dispatch state is distinct from preserved historical Job status."""
from datetime import UTC, datetime, timedelta
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


def dispatch_queue_counts(conn: Any) -> dict[str, int]:
    """One read-only definition for API, CLI and operations dashboard counts."""
    now = datetime.now(UTC)
    mode = conn.execute("SELECT blogger_write_mode,blogger_api_restricted,emergency_stopped FROM publication_mode_settings WHERE scope_type='global' AND scope_key=''").fetchone()
    worker = conn.execute("SELECT status,last_seen_at,execution_mode FROM worker_heartbeats WHERE service_name='publication_worker'").fetchone()
    permitted = bool(mode and mode['blogger_write_mode']=='manual_only'
        and not mode['blogger_api_restricted'] and not mode['emergency_stopped']
        and worker and worker['status']=='running' and worker['last_seen_at']
        and now-worker['last_seen_at']<=timedelta(seconds=45)
        and worker['execution_mode'] in {'operations-manual-confirmed','operations-scheduled-auto-and-manual','operations-scheduled-auto-and-manual-and-trends'})
    cutoff_row = conn.execute("SELECT max(created_at) cutoff FROM audit_events WHERE event_type='publication.manual_only.activated'").fetchone()
    cutoff = cutoff_row['cutoff'] if cutoff_row else None
    jobs = conn.execute("""SELECT j.publication_lane,j.scheduled_at,j.available_at,
        (SELECT max(a.created_at) FROM manual_publication_approval_events a WHERE a.job_id=j.id) approval_at
        FROM publishing_jobs j WHERE j.status='queued' AND j.adapter_type='blogger_live' AND NOT j.simulation_only""").fetchall()
    result = {'live_queued': 0,'live_due': 0,'auto_paused': 0,'manual_action_required': 0,'preserved_live_queued': len(jobs)}
    for row in jobs:
        state = pending_state(row['publication_lane'],row['approval_at'],cutoff,permitted)
        if state=='queued':
            result['live_queued'] += 1
            result['live_due'] += int(row['scheduled_at']<=now and row['available_at']<=now)
        else:
            result[state] += 1
    return result
