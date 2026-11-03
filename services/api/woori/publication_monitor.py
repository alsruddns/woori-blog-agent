"""Read-only live Job monitoring; never dispatch or retry a publication."""
from datetime import UTC, datetime, timedelta
from typing import Any

from .db import connection
from .publication_read_state import failure_resolved_clause, pending_state


def heartbeat_state(row: dict[str, Any] | None, now: datetime) -> str:
    if not row or row.get('status') != 'running':
        return 'stopped'
    return 'running' if row.get('last_seen_at') and now-row['last_seen_at'] <= timedelta(seconds=45) else 'stale'


def _pre_job_classification(item: dict[str, Any]) -> tuple[str, str]:
    """Return a source-backed root-cause bucket and a current safety decision."""
    payload = item.get('payload') or {}
    codes = set(payload.get('reason_codes') or [])
    if payload.get('failure_reason_code'):
        codes.add(str(payload['failure_reason_code']))
    revision_codes = {
        'quality_evaluation_missing', 'quality_not_passed', 'claim_source_verification_unavailable',
        'no_supported_body_after_sanitization', 'source_live_verification_missing',
        'source_live_verification_mismatch', 'scheduled_origin_target_mismatch',
        'scheduled_language_blog_mismatch', 'scheduled_sanitized_revision_required',
    }
    policy_codes = {
        'global_publication_mode_mismatch', 'automatic_publication_suspended',
        'automatic_publication_operator_approval_required', 'automatic_publication_policy_inactive',
        'global_auto_publish_disabled', 'trends_auto_publish_disabled', 'scheduled_auto_publish_disabled',
    }
    if codes & revision_codes:
        root_cause = 'manuscript_revision_required'
    elif codes & {'remote_duplicate_found', 'already_published'}:
        root_cause = 'publish_prohibited'
    elif 'collection_predates_policy_activation' in codes:
        root_cause = 'history'
    elif codes & policy_codes:
        root_cause = 'reevaluation_possible'
    else:
        root_cause = 'review_required'
    if item.get('remote_status') == 'LIVE' and item.get('remote_verified_at'):
        safety = 'publish_prohibited_already_live'
    elif not item.get('blog_active') or not item.get('language_active'):
        safety = 'publish_prohibited_inactive_target'
    elif item.get('discard_status') == 'discarded':
        safety = 'publish_prohibited_discarded'
    elif item.get('remote_status') in {'DRAFT', 'unknown'} or item.get('remote_check_required'):
        safety = 'remote_status_check_required'
    elif root_cause == 'history':
        safety = 'historical_policy_failure'
    elif root_cause == 'manuscript_revision_required':
        safety = 'manuscript_review_required'
    elif root_cause == 'reevaluation_possible':
        safety = 'blocked_by_current_or_historical_policy'
    elif root_cause == 'publish_prohibited':
        safety = 'publish_prohibited_duplicate_or_discarded'
    else:
        safety = 'manual_review_required'
    if item.get('failure_history_event') == 'publication.pre_job_failure.archived' and safety != 'publish_prohibited_discarded':
        safety = 'history_archived'
    return root_cause, safety


def snapshot(view: str, page: int, page_size: int) -> dict[str, Any]:
    from .publication_operation import manual_requests_allowed
    permitted = manual_requests_allowed()
    with connection() as conn:
        cutoff_row = conn.execute("SELECT max(created_at) cutoff FROM audit_events WHERE event_type='publication.manual_only.activated'").fetchone()
        cutoff = cutoff_row["cutoff"] if cutoff_row else None
        jobs = conn.execute(f"""SELECT j.id,j.content_version_id,j.blog_id,j.status,j.publication_state,
            j.publication_lane,j.publication_mode,j.scheduled_at,j.available_at,j.updated_at,j.retry_count,j.max_retries,
            j.live_stage,j.last_error_category,j.block_reasons,j.lease_until,
            (SELECT max(a.created_at) FROM manual_publication_approval_events a WHERE a.job_id=j.id) approval_at,
            v.title,b.display_name AS blog_name,b.blog_id AS blogger_blog_id,
            (EXISTS(SELECT 1 FROM publishing_records rr WHERE rr.blog_id=j.blog_id AND rr.content_version_id=j.content_version_id AND rr.remote_status='LIVE' AND rr.remote_verified_at IS NOT NULL)
              OR NOT ({failure_resolved_clause('v','j.blog_id','imported.import_id')})) AS resolved_by_live,
            imported.import_id,imported.generation_method,evaluation.id AS evaluation_id,
            attempt.operation AS failure_operation,
            registered.registered_at,started.started_at,progress.created_at AS progress_at,
            progress.event_type AS progress_event,
            COALESCE(remote.remote_url,sync.payload->>'remote_url') remote_url,COALESCE(remote.remote_post_id,d.remote_post_id,j.remote_post_id) remote_post_id,
            COALESCE(remote.remote_verified_at,CASE WHEN sync.payload->>'remote_status' IN ('DRAFT','LIVE') THEN sync.created_at END,d.verified_at) remote_verified_at,
            sync.created_at remote_checked_at,sync.payload->>'error_code' remote_check_error,
            COALESCE(remote.remote_status,sync.payload->>'remote_status',d.remote_status) remote_status
          FROM publishing_jobs j JOIN content_versions v ON v.id=j.content_version_id
          JOIN blogger_blogs b ON b.id=j.blog_id
          LEFT JOIN LATERAL (SELECT i.id import_id,i.generation_method
            FROM external_content_import_content_links l JOIN external_content_imports i ON i.id=l.import_id
            WHERE l.content_version_id=j.content_version_id LIMIT 1) imported ON true
          LEFT JOIN LATERAL (SELECT id FROM article_quality_evaluations WHERE content_version_id=j.content_version_id
            ORDER BY created_at DESC,id DESC LIMIT 1) evaluation ON true
          LEFT JOIN LATERAL (SELECT operation FROM live_publication_attempts WHERE job_id=j.id
            ORDER BY created_at DESC,id DESC LIMIT 1) attempt ON true
          LEFT JOIN LATERAL (SELECT min(created_at) registered_at FROM audit_events
            WHERE payload->>'job_id'=j.id::text) registered ON true
          LEFT JOIN LATERAL (SELECT max(created_at) started_at FROM audit_events
            WHERE payload->>'job_id'=j.id::text AND event_type='publication.live_job.started') started ON true
          LEFT JOIN LATERAL (SELECT created_at,event_type FROM audit_events
            WHERE payload->>'job_id'=j.id::text ORDER BY id DESC LIMIT 1) progress ON true
          LEFT JOIN publishing_records remote ON remote.job_id=j.id
          LEFT JOIN blogger_draft_receipts d ON d.job_id=j.id
          LEFT JOIN LATERAL (SELECT payload,created_at FROM audit_events WHERE event_type='publication.trends_draft.synced'
            AND payload->>'job_id'=j.id::text ORDER BY id DESC LIMIT 1) sync ON true
          WHERE j.adapter_type='blogger_live' AND NOT j.simulation_only
          ORDER BY j.updated_at DESC,j.id DESC""").fetchall()
        failures = conn.execute(f"""WITH latest AS (
            SELECT DISTINCT ON(payload->>'import_id',payload->>'content_version_id',payload->>'blog_record_id') id,event_type,payload,created_at
            FROM audit_events WHERE event_type IN ('publication.auto_failure.recorded','publication.auto_failure.cleared')
            ORDER BY payload->>'import_id',payload->>'content_version_id',payload->>'blog_record_id',id DESC)
          SELECT i.title AS import_title,i.generation_method,i.language_code,i.id import_id,
            i.received_at AS imported_at,e.id AS failure_event_id,e.payload,e.created_at AS failure_at,
            b.id AS blog_record_id,b.display_name blog_name,b.blog_id blogger_blog_id,b.url AS blog_url,
            b.active AS blog_active,lang.active AS language_active,
            failed_v.id AS failure_content_version_id,failed_v.group_id AS manuscript_id,
            failed_v.title AS failure_title,failed_v.version AS failure_version,failed_v.created_at AS authored_at,
            current_v.id AS current_content_version_id,current_v.title AS current_title,
            current_v.version AS current_version,current_v.created_at AS current_version_at,
            d.status AS discard_status,d.reason AS discard_reason,d.actor AS discard_actor,d.discarded_at,
             history.event_type AS failure_history_event,
            evaluation.created_at AS evaluation_at,evaluation.status AS evaluation_status,
            evaluation.publish_ready,
            repeat_count.recorded_event_count,
            related_job.job_count,related_job.retry_count,related_job.latest_status AS related_job_status,
            remote.remote_status,remote.remote_post_id,remote.remote_url,remote.remote_verified_at,
            remote.published_at AS remote_published_at,
            (COALESCE(failed_v.created_at, e.created_at) < now()-interval '24 hours') AS older_than_24h,
            (COALESCE(failed_v.created_at, e.created_at) < now()-interval '72 hours') AS older_than_72h,
            (e.payload->>'failure_reason_code'='remote_duplicate_check_unknown'
              OR e.payload->'reason_codes' ? 'remote_duplicate_check_unknown') AS remote_check_required
          FROM latest e JOIN external_content_imports i ON i.id::text=e.payload->>'import_id'
          LEFT JOIN content_versions failed_v ON failed_v.id::text=e.payload->>'content_version_id'
          LEFT JOIN blogger_blogs b ON b.id::text=e.payload->>'blog_record_id'
          LEFT JOIN languages lang ON lang.code=i.language_code
          LEFT JOIN manuscript_discards d ON d.group_id=failed_v.group_id AND d.blog_id=b.id
           LEFT JOIN LATERAL (SELECT h.event_type FROM audit_events h
             WHERE h.event_type IN ('publication.pre_job_failure.archived','publication.pre_job_failure.restored')
               AND h.payload->>'failure_event_id'=e.id::text
             ORDER BY h.id DESC LIMIT 1) history ON true
          LEFT JOIN LATERAL (SELECT cv.id,cv.title,cv.version,cv.created_at
            FROM external_content_import_content_links link JOIN content_versions cv ON cv.id=link.content_version_id
            WHERE link.import_id=i.id AND cv.localization_id IS NOT DISTINCT FROM failed_v.localization_id
            ORDER BY cv.version DESC,cv.created_at DESC,cv.id DESC LIMIT 1) current_v ON true
          LEFT JOIN LATERAL (SELECT created_at,status,publish_ready FROM article_quality_evaluations
            WHERE content_version_id=current_v.id ORDER BY created_at DESC,id DESC LIMIT 1) evaluation ON true
          LEFT JOIN LATERAL (SELECT count(*)::int AS recorded_event_count FROM audit_events repeated
            WHERE repeated.event_type='publication.auto_failure.recorded'
              AND repeated.payload->>'import_id'=e.payload->>'import_id'
              AND repeated.payload->>'content_version_id'=e.payload->>'content_version_id'
              AND repeated.payload->>'blog_record_id'=e.payload->>'blog_record_id') repeat_count ON true
          LEFT JOIN LATERAL (SELECT count(*)::int AS job_count,max(j.retry_count)::int AS retry_count,
              (array_agg(j.status ORDER BY j.updated_at DESC,j.id DESC))[1] AS latest_status
            FROM publishing_jobs j WHERE j.blog_id=b.id AND j.content_version_id=failed_v.id
              AND j.adapter_type='blogger_live' AND NOT j.simulation_only) related_job ON true
          LEFT JOIN LATERAL (SELECT r.remote_status,r.remote_post_id,r.remote_url,r.remote_verified_at,r.published_at
            FROM publishing_records r JOIN content_versions rv ON rv.id=r.content_version_id
            WHERE r.blog_id=b.id AND rv.group_id=failed_v.group_id
            ORDER BY r.published_at DESC NULLS LAST,r.id DESC LIMIT 1) remote ON true
          WHERE e.event_type='publication.auto_failure.recorded' AND NOT EXISTS (
            SELECT 1 FROM publishing_jobs j JOIN external_content_import_content_links l
              ON l.content_version_id=j.content_version_id AND l.import_id=i.id
            WHERE j.blog_id=b.id AND j.content_version_id::text=e.payload->>'content_version_id'
              AND j.adapter_type='blogger_live' AND NOT j.simulation_only
              AND (j.status IN ('queued','running','failed','blocked','uncertain') OR j.publication_state='draft_saved'))
          AND {failure_resolved_clause('failed_v','b.id','i.id')}
          ORDER BY e.created_at DESC""").fetchall()
        worker = conn.execute("SELECT * FROM worker_heartbeats WHERE service_name='publication_worker'").fetchone()
        interval_row = conn.execute(
            "SELECT global_publish_min_interval_minutes FROM automation_controls WHERE id=1"
        ).fetchone()
    permitted = permitted and heartbeat_state(dict(worker) if worker else None,datetime.now(UTC)) == "running"
    items = []
    for raw in jobs:
        item = dict(raw)
        state = ('published' if item['remote_status']=='LIVE' and item['remote_verified_at']
                 else 'draft_saved' if item['remote_status']=='DRAFT' and item['publication_state']=='draft_saved' else 'queued' if item['status']=='queued' else 'running' if item['status']=='running' else 'failed')
        if state=='failed' and item.get('resolved_by_live'):
            state = 'resolved'
        if item['status'] in {'queued','running'} and state not in {'published','draft_saved'}:
            current = pending_state(item['publication_lane'],item.get('approval_at'),cutoff,permitted)
            if current != 'queued':
                state = current
        item.update(kind='job',state=state,job_id=str(item['id']),
                    lease_overdue=bool(item['status']=='running' and item['lease_until'] and item['lease_until']<datetime.now(UTC)),
                    failure_stage='eligibility' if item['block_reasons'] else item['failure_operation'] or 'publication_worker',
                    failure_reason=item['last_error_category'] or item.get('remote_check_error') or next(iter(item['block_reasons'] or []),None),
                    retry_possible=state=='failed' and item['status'] in {'failed','blocked'} and item['retry_count']<item['max_retries'],
                    remote_url=item['remote_url'] if state=='published' else None)
        items.append(item)
    failure_summary: dict[str, Any] = {
        'current_record_count': 0, 'unique_import_count': 0, 'unique_manuscript_count': 0, 'unique_content_version_count': 0,
        'repeated_failure_event_count': 0, 'active_unarchived_count': 0, 'archived_count': 0,
        'root_cause_counts': {}, 'safety_classification_counts': {}, 'failure_reason_code_counts': {},
        'older_than_24h_count': 0, 'older_than_72h_count': 0,
    }
    failure_items: list[dict[str, Any]] = []
    root_causes: dict[str, int] = {}
    safety_counts: dict[str, int] = {}
    reason_counts: dict[str, int] = {}
    all_reason_counts: dict[str, int] = {}
    manuscript_ids: set[str] = set()
    import_ids: set[str] = set()
    version_ids: set[str] = set()
    repeated_events = 0
    for failure in failures:
        p = failure['payload']
        item = dict(failure)
        item.update({
            'kind': 'pre_job_failure',
             'state': 'archived_failure' if item.get('discard_status') == 'discarded' or item.get('failure_history_event') == 'publication.pre_job_failure.archived' else 'pre_job_failure',
            'job_id': None,
            'content_version_id': p.get('content_version_id'),
            'title': item.get('current_title') or item.get('failure_title') or item.get('import_title') or '제목 없음',
            'publication_lane': 'scheduled_auto',
            'failure_stage': p.get('stage'),
            'failure_reason': p.get('failure_reason_code'),
            'failure_reason_codes': p.get('reason_codes') or [],
            'retry_count': item.get('retry_count') or 0,
            'retry_possible': False,
            'updated_at': item.get('failure_at'),
            'registered_at': None,
            'remote_post_id': item.get('remote_post_id') or p.get('remote_post_id'),
            'manuscript_id': str(item['manuscript_id']) if item.get('manuscript_id') else None,
            'blog_id': str(item['blog_record_id']) if item.get('blog_record_id') else None,
            'import_id': str(item['import_id']) if item.get('import_id') else None,
            'failure_content_version_id': str(item['failure_content_version_id']) if item.get('failure_content_version_id') else None,
            'current_content_version_id': str(item['current_content_version_id']) if item.get('current_content_version_id') else None,
            'origin': item.get('generation_method'),
            'remote_check_required': bool(item.get('remote_check_required')),
            'history_archived': item.get('failure_history_event') == 'publication.pre_job_failure.archived',
        })
        root_cause, safety_classification = _pre_job_classification(item)
        item['root_cause_classification'] = root_cause
        item['safety_classification'] = safety_classification
        item['recheck_allowed'] = item.get('state') == 'pre_job_failure' and item.get('blog_active') and item.get('language_active')
        item['manual_request_requires_preflight'] = True
        failure_items.append(item)
        root_causes[root_cause] = root_causes.get(root_cause, 0) + 1
        safety_counts[safety_classification] = safety_counts.get(safety_classification, 0) + 1
        primary_reason = str(p.get('failure_reason_code') or 'unknown')
        reason_counts[primary_reason] = reason_counts.get(primary_reason, 0) + 1
        for code in set(p.get('reason_codes') or [primary_reason]):
            all_reason_counts[str(code)] = all_reason_counts.get(str(code), 0) + 1
        if item.get('manuscript_id'):
            manuscript_ids.add(str(item['manuscript_id']))
        if item.get('import_id'):
            import_ids.add(str(item['import_id']))
        if item.get('content_version_id'):
            version_ids.add(str(item['content_version_id']))
        repeated_events += max(0, int(item.get('recorded_event_count') or 0) - 1)
    failure_summary.update({
        'current_record_count': len(failure_items),
        'unique_import_count': len(import_ids),
        'unique_manuscript_count': len(manuscript_ids),
        'unique_content_version_count': len(version_ids),
        'repeated_failure_event_count': repeated_events,
        'active_unarchived_count': sum(item.get('state') == 'pre_job_failure' for item in failure_items),
        'archived_count': sum(item.get('state') == 'archived_failure' for item in failure_items),
        'root_cause_counts': root_causes,
        'safety_classification_counts': safety_counts,
        'failure_reason_code_counts': reason_counts,
        'all_reason_code_counts': all_reason_counts,
        'older_than_24h_count': sum(bool(item.get('older_than_24h')) for item in failure_items),
        'older_than_72h_count': sum(bool(item.get('older_than_72h')) for item in failure_items),
    })
    items.extend(failure_items)
    counts = {key:sum(item['state']==key for item in items) for key in ('queued','running','published','draft_saved','failed','pre_job_failure','archived_failure','auto_paused','manual_action_required','resolved')}
    items.sort(key=lambda item:item.get('updated_at') or datetime.min.replace(tzinfo=UTC),reverse=True)
    selected = items if view=='all' else [item for item in items if item['state']==view]
    now = datetime.now(UTC)
    last_job = dict(jobs[0]) if jobs else None
    return {'period':'all_time','global_publish_min_interval_minutes': int(interval_row['global_publish_min_interval_minutes']) if interval_row else None,'period_label':'전체 기간 등록 Job의 현재 상태 · 사전 실패는 보관 상태와 분리 표시 · Mock 제외',
            'as_of':now,'counts':counts,'pre_job_failure_summary':failure_summary,'worker':dict(worker) if worker else None,
            'worker_state':heartbeat_state(dict(worker) if worker else None,now),
            'last_job':last_job,'items':selected[(page-1)*page_size:page*page_size],
            'total':len(selected),'page':page,'page_count':max(1,(len(selected)+page_size-1)//page_size)}
