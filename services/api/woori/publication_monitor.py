"""Read-only live Job monitoring; never dispatch or retry a publication."""
from datetime import UTC, datetime, timedelta
from typing import Any

from .db import connection


def heartbeat_state(row: dict[str, Any] | None, now: datetime) -> str:
    if not row or row.get('status') != 'running':
        return 'stopped'
    return 'running' if row.get('last_seen_at') and now-row['last_seen_at'] <= timedelta(seconds=45) else 'stale'


def snapshot(view: str, page: int, page_size: int) -> dict[str, Any]:
    with connection() as conn:
        jobs = conn.execute("""SELECT j.id,j.content_version_id,j.blog_id,j.status,j.publication_state,
            j.publication_lane,j.scheduled_at,j.available_at,j.updated_at,j.retry_count,j.max_retries,
            j.live_stage,j.last_error_category,j.block_reasons,j.lease_until,
            v.title,b.display_name AS blog_name,b.blog_id AS blogger_blog_id,
            imported.import_id,imported.generation_method,evaluation.id AS evaluation_id,
            attempt.operation AS failure_operation,
            registered.registered_at,started.started_at,progress.created_at AS progress_at,
            progress.event_type AS progress_event,
            remote.remote_url,remote.remote_post_id,remote.remote_verified_at,remote.remote_status
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
          WHERE j.adapter_type='blogger_live' AND NOT j.simulation_only
          ORDER BY j.updated_at DESC,j.id DESC""").fetchall()
        failures = conn.execute("""WITH latest AS (
            SELECT DISTINCT ON(payload->>'import_id',payload->>'blog_record_id') event_type,payload,created_at
            FROM audit_events WHERE event_type IN ('publication.auto_failure.recorded','publication.auto_failure.cleared')
            ORDER BY payload->>'import_id',payload->>'blog_record_id',id DESC)
          SELECT i.title,i.generation_method,i.id import_id,e.payload,e.created_at,
            b.display_name blog_name,b.blog_id blogger_blog_id
          FROM latest e JOIN external_content_imports i ON i.id::text=e.payload->>'import_id'
          LEFT JOIN blogger_blogs b ON b.id::text=e.payload->>'blog_record_id'
          WHERE e.event_type='publication.auto_failure.recorded' AND NOT EXISTS (
            SELECT 1 FROM publishing_jobs j WHERE j.blog_id=b.id
              AND (j.id::text=e.payload->>'job_id' OR j.content_version_id::text=e.payload->>'content_version_id')
              AND j.adapter_type='blogger_live' AND NOT j.simulation_only)
          ORDER BY e.created_at DESC""").fetchall()
        worker = conn.execute("SELECT * FROM worker_heartbeats WHERE service_name='publication_worker'").fetchone()
    items = []
    for raw in jobs:
        item = dict(raw)
        state = ('published' if item['remote_status']=='LIVE' and item['remote_verified_at']
                 else 'queued' if item['status']=='queued' else 'running' if item['status']=='running' else 'failed')
        item.update(kind='job',state=state,job_id=str(item['id']),
                    lease_overdue=bool(item['status']=='running' and item['lease_until'] and item['lease_until']<datetime.now(UTC)),
                    failure_stage='eligibility' if item['block_reasons'] else item['failure_operation'] or 'publication_worker',
                    failure_reason=item['last_error_category'] or next(iter(item['block_reasons'] or []),None),
                    retry_possible=state=='failed' and item['status'] in {'failed','blocked'} and item['retry_count']<item['max_retries'],
                    remote_url=item['remote_url'] if state=='published' else None)
        items.append(item)
    for failure in failures:
        p = failure['payload']
        items.append({**dict(failure), 'kind':'pre_job_failure','state':'pre_job_failure','job_id':None,
                      'content_version_id':p.get('content_version_id'),'publication_lane':'scheduled_auto',
                      'failure_stage':p.get('stage'),'failure_reason':p.get('failure_reason_code'),
                      'retry_count':p.get('retry_count',0),'retry_possible':False,
                      'updated_at':failure['created_at'],'registered_at':None})
    counts = {key:sum(item['state']==key for item in items) for key in ('queued','running','published','failed','pre_job_failure')}
    items.sort(key=lambda item:item.get('updated_at') or datetime.min.replace(tzinfo=UTC),reverse=True)
    selected = items if view=='all' else [item for item in items if item['state']==view]
    now = datetime.now(UTC)
    last_job = dict(jobs[0]) if jobs else None
    return {'period':'all_time','period_label':'전체 기간 등록 Job의 현재 상태 · 실제 Blogger · Mock 제외',
            'as_of':now,'counts':counts,'worker':dict(worker) if worker else None,
            'worker_state':heartbeat_state(dict(worker) if worker else None,now),
            'last_job':last_job,'items':selected[(page-1)*page_size:page*page_size],
            'total':len(selected),'page':page,'page_count':max(1,(len(selected)+page_size-1)//page_size)}
