import os
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import psycopg
import pytest
from fastapi import HTTPException
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from test_keyword_authoring import setup_job
from test_pipeline import lab as shared_lab
from woori import google_oauth, keyword_jobs, trend_editorial

lab=shared_lab


def test_token_refresh_lock_is_compatible_with_callers_job_foreign_key(monkeypatch):
    # Dedicated disposable test schema, never an operational connection/table.
    url=os.environ['MIGRATION_DATABASE_URL']
    schema='woori_test_p096_'+uuid4().hex
    with psycopg.connect(url,autocommit=True,row_factory=dict_row) as owner:
        identity=owner.execute('SELECT current_database() db,current_user role').fetchone()
        assert identity=={'db':'woori_blog_agent_test','role':'woori_test_owner'}
        owner.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        try:
            owner.execute(sql.SQL('CREATE TABLE {}.google_connections(id uuid PRIMARY KEY,status text,expires_at timestamptz,access_ciphertext text)').format(sql.Identifier(schema)))
            owner.execute(sql.SQL('CREATE TABLE {}.jobs(id uuid PRIMARY KEY,oauth_id uuid REFERENCES {}.google_connections(id))').format(sql.Identifier(schema),sql.Identifier(schema)))
            key=uuid4()
            owner.execute(sql.SQL("INSERT INTO {}.google_connections VALUES (%s,'connected',now()+interval '1 hour','test-cipher')").format(sql.Identifier(schema)),(key,))
            @contextmanager
            def separate():
                with psycopg.connect(url,row_factory=dict_row) as token:
                    token.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(schema)))
                    token.execute("SET LOCAL lock_timeout='300ms'")
                    yield token
            monkeypatch.setattr(google_oauth,'connection',separate)
            monkeypatch.setattr(google_oauth,'decrypt',lambda _: 'isolated-token')
            with psycopg.connect(url) as parent:
                parent.execute(sql.SQL('INSERT INTO {}.jobs VALUES (%s,%s)').format(sql.Identifier(schema)),(uuid4(),key))
                with pytest.raises(psycopg.errors.LockNotAvailable), separate() as token:
                    token.execute('SELECT * FROM google_connections WHERE id=%s FOR UPDATE',(key,))
                assert google_oauth.access_token(key)=='isolated-token'
                parent.rollback()
        finally:
            assert schema.startswith('woori_test_p096_')
            owner.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


@pytest.mark.parametrize('expired',[False,True])
def test_usage_recovery_preserves_job_and_requires_current_slot(lab,monkeypatch,tmp_path,expired):
    conn,api,headers,payload=setup_job(lab,monkeypatch)
    @contextmanager
    def shared():
        with conn.transaction():yield conn
    monkeypatch.setattr(trend_editorial,'connection',shared)
    monkeypatch.setattr(trend_editorial,'slot_is_current',lambda _:not expired)
    monkeypatch.setattr(trend_editorial,'current_observations',lambda *_:[{'id':uuid4()}])
    response=api.post('/admin/keyword-authoring',headers=headers,json=payload)
    job=response.json()['id'];topic=uuid4()
    conn.execute("INSERT INTO trend_topics(id,normalized_key,representative_geo,representative_query,grouping_method,grouping_confidence,grouping_status) VALUES (%s,%s,'KR','test topic','single_observation',1,'exact_query_cluster_not_event_confirmed')",(topic,uuid4().hex))
    request=conn.execute("INSERT INTO trend_generation_requests(topic_id,duplicate_key,contract,state,authoring_job_id) VALUES (%s,%s,%s,'failed',%s) RETURNING id",
        (topic,uuid4().hex,Jsonb({'collection_slot':datetime.now(UTC).isoformat()}),job)).fetchone()['id']
    conn.execute("UPDATE codex_authoring_jobs SET job_type='google_trends',trend_request_id=%s,state='failed',error_code='codex_usage_limit' WHERE id=%s",(request,job))
    retry={'request_key':str(uuid4())}
    monkeypatch.setattr(keyword_jobs,'authoring_backoff',lambda _:{'active':True,'provider_reset_at':None})
    result=api.post(f'/admin/keyword-authoring/{job}/retry',headers=headers,json=retry)
    assert result.status_code==(409 if expired else 429)
    monkeypatch.setattr(keyword_jobs,'authoring_backoff',lambda _:None)
    result=api.post(f'/admin/keyword-authoring/{job}/retry',headers=headers,json=retry)
    if expired:
        assert result.status_code==409 and 'expired_collection_slot' in result.text
        return
    assert result.status_code==201,result.text
    assert result.json()['id']==job and result.json()['state']=='queued'
    assert api.post(f'/admin/keyword-authoring/{job}/retry',headers=headers,json=retry).json()['id']==job
    assert conn.execute('SELECT count(*) n FROM codex_authoring_jobs WHERE id=%s',(job,)).fetchone()['n']==1
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path))
    assert keyword_jobs.job_workdir(result.json()).name=='attempt-'+retry['request_key']


def test_usage_backoff_does_not_invent_provider_reset(lab):
    conn,_,_=lab
    conn.execute("INSERT INTO audit_events(event_type,payload) VALUES ('codex.authoring.state','{\"error_code\":\"codex_usage_limit\"}')")
    result=keyword_jobs.authoring_backoff(conn)
    assert result['active'] and result['provider_reset_at'] is None
    assert result['basis']=='local_backoff_not_provider_reset'
    assert datetime.fromisoformat(result['not_before'])<=datetime.now(UTC)+timedelta(minutes=15)


def test_settings_repr_never_exposes_connection_or_admin_credentials():
    from woori.config import Settings
    value=Settings(_env_file=None,database_url='postgresql://test:private-db-value@localhost/test',
        evaluation_database_url='postgresql://test:private-eval-value@localhost/test',admin_token='private-admin-value-'*3)
    rendered=repr(value)
    assert 'private-db-value' not in rendered and 'private-eval-value' not in rendered and 'private-admin-value' not in rendered


@pytest.mark.parametrize('message,expected',[
    ('Blog has exceeded rate limit or quota','free_quota_exceeded'),
    ('User does not have permission to perform the requested action','permission_denied'),
])
def test_google_forbidden_quota_is_distinct_from_permission(message,expected):
    from woori.google_http import classify, safe_error_reason
    response=httpx.Response(403,json={'error':{'message':message,'errors':[{'reason':'forbidden'}]}})
    assert classify(response)==expected
    assert safe_error_reason(response)=='forbidden'


def test_blogger_backoff_preserves_jobs_and_does_not_dispatch(lab,monkeypatch):
    from woori import publication_worker, trends_publication
    conn,_,_=lab
    @contextmanager
    def shared():
        with conn.transaction():yield conn
    monkeypatch.setattr(publication_worker,'connection',shared)
    monkeypatch.setattr(publication_worker,'recover_verified_trends_draft',lambda:None)
    monkeypatch.setattr(publication_worker,'enqueue_scheduled_auto_jobs',lambda:pytest.fail('no new dispatch during provider backoff'))
    conn.execute("INSERT INTO audit_events(event_type,payload) VALUES ('blogger.api.error_classified','{\"category\":\"permission_denied\",\"operation\":\"blogger_draft_create\"}')")
    pause=trends_publication.trends_write_backoff(conn)
    assert pause['active'] and pause['provider_reset_at'] is None
    assert publication_worker.process_next_live_job(trends_auto_only=True)['status']=='external_backoff'
    assert publication_worker.process_next_live_job(trends_auto_only=True)['job_id'] is None
    assert conn.execute("SELECT count(*) n FROM audit_events WHERE event_type='publication.trends_auto.external_backoff' AND payload->>'source_event_id'=%s",(str(pause['event_id']),)).fetchone()['n']==1


@pytest.mark.parametrize('lane',['scheduled_auto','manual'])
def test_trends_backoff_never_starves_existing_publication_lanes(monkeypatch,lane):
    from woori import publication_worker
    def process(**flags):
        if flags.get('trends_auto_only'):return {'status':'external_backoff','job_id':None}
        return {'status':'isolated_other_lane','job_id':str(uuid4())}
    monkeypatch.setattr(publication_worker,'process_next_live_job',process)
    result=publication_worker.tick(allow_trends_auto_publications=True,
        allow_scheduled_auto_publications=lane=='scheduled_auto',allow_manual_confirmed_publications=lane=='manual')
    assert result['status']=='isolated_other_lane'


def test_expired_usage_failure_can_recover_only_from_new_collection(lab,monkeypatch):
    conn,api,headers,payload=setup_job(lab,monkeypatch)
    @contextmanager
    def shared():
        with conn.transaction():yield conn
    monkeypatch.setattr(trend_editorial,'connection',shared)
    now=datetime.now(UTC).replace(second=0,microsecond=0)
    slot=now.replace(minute=now.minute//10*10)
    monkeypatch.setattr(trend_editorial,'current_slot',lambda:slot)
    original=api.post('/admin/keyword-authoring',headers=headers,json=payload).json()['id']
    blog=conn.execute('SELECT blog_id FROM codex_authoring_jobs WHERE id=%s',(original,)).fetchone()['blog_id']
    conn.execute("UPDATE trend_blog_geo_authoring SET enabled=false WHERE geo='KR'")
    conn.execute("INSERT INTO trend_blog_geo_authoring(blog_id,geo,enabled,processing_order) VALUES (%s,'KR',true,1)",(blog,))
    topic=uuid4();key='p096 ai glasses '+uuid4().hex
    conn.execute("INSERT INTO trend_topics(id,normalized_key,representative_geo,representative_query,grouping_method,grouping_confidence,grouping_status) VALUES (%s,%s,'KR',%s,'single_observation',1,'exact_query_cluster_not_event_confirmed')",(topic,key,key))
    old_contract={'target_blog_id':str(blog),'collection_slot':(slot-timedelta(minutes=10)).isoformat()}
    request=conn.execute("INSERT INTO trend_generation_requests(topic_id,duplicate_key,contract,state,authoring_job_id) VALUES (%s,%s,%s,'failed',%s) RETURNING id",(topic,uuid4().hex,Jsonb(old_contract),original)).fetchone()['id']
    conn.execute("UPDATE codex_authoring_jobs SET job_type='google_trends',trend_request_id=%s,state='failed',error_code='codex_usage_limit' WHERE id=%s",(request,original))
    observation={'id':uuid4(),'slot_at':slot,'collected_at':now,'trend_started_at':slot,
        'query':key,'source_volume_label':'1000+','raw_payload':{}}
    trend_editorial.transition(conn,topic,'selected','fresh_reassessment','New collection independently reassessed','isolated',category='technology')
    monkeypatch.setattr(trend_editorial,'current_observations',lambda *_:[])
    with pytest.raises(HTTPException,match='expired_collection_slot'):
        trend_editorial.queue_topic(conn,topic,blog)
    monkeypatch.setattr(trend_editorial,'current_observations',lambda *_:[observation])
    queued=trend_editorial.queue_topic(conn,topic,blog)
    assert queued['id']!=request and queued['contract']['collection_slot']==slot.isoformat()
    assert queued['contract']['recovery_of_job_id']==original
    assert queued['contract']['source_observation_ids']==[str(observation['id'])]
    assert trend_editorial.queue_topic(conn,topic,blog)['id']==queued['id']
    trend_editorial.transition(conn,topic,'generation_queued','fresh_recovery','New current slot','isolated',category='technology')
    assert trend_editorial.dispatch()['created']==1
    child=conn.execute('SELECT * FROM codex_authoring_jobs WHERE trend_request_id=%s',(queued['id'],)).fetchone()
    assert child['job_type']=='google_trends' and str(child['parent_job_id'])==original
    assert conn.execute('SELECT contract FROM trend_generation_requests WHERE id=%s',(request,)).fetchone()['contract']==old_contract
    assert conn.execute('SELECT error_code FROM codex_authoring_jobs WHERE id=%s',(original,)).fetchone()['error_code']=='codex_usage_limit'
