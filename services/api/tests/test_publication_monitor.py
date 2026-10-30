from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from psycopg.types.json import Jsonb
from test_pipeline import lab as shared_lab
from woori import publication_monitor, publications

lab = shared_lab


@pytest.mark.parametrize(('row','expected'), [
    (None,'stopped'),({'status':'stopped','last_seen_at':datetime.now(UTC)},'stopped'),
    ({'status':'running','last_seen_at':datetime.now(UTC)-timedelta(minutes=2)},'stale'),
    ({'status':'running','last_seen_at':datetime.now(UTC)},'running'),
])
def test_heartbeat_is_not_a_running_job(row,expected):
    assert publication_monitor.heartbeat_state(row,datetime.now(UTC)) == expected


def test_real_job_states_and_pre_job_failures_are_distinct_and_read_only(lab,monkeypatch):
    conn,api,headers=lab

    @contextmanager
    def shared():
        with conn.transaction():
            yield conn

    monkeypatch.setattr(publication_monitor,'connection',shared)
    baseline=publication_monitor.snapshot('all',1,100)['counts']
    policy=conn.execute('SELECT p.*,l.target_country FROM publishing_policies p JOIN language_profiles l ON l.id=p.profile_id LIMIT 1').fetchone()
    oauth=conn.execute("INSERT INTO google_connections(label) VALUES ('isolated monitor fixture') RETURNING id").fetchone()['id']
    ids={}
    for status in ('queued','running','succeeded','failed'):
        group=conn.execute('INSERT INTO content_groups DEFAULT VALUES RETURNING id').fetchone()['id']
        locale=conn.execute('INSERT INTO content_localizations(group_id,language_code,target_country) VALUES (%s,%s,%s) RETURNING id',(group,policy['language_code'],policy['target_country'])).fetchone()['id']
        version=conn.execute("INSERT INTO content_versions(group_id,localization_id,language,version,title,body) VALUES (%s,%s,%s,1,'Isolated monitor fixture','Test only, never publish') RETURNING id",(group,locale,policy['language_code'])).fetchone()['id']
        job=conn.execute("""INSERT INTO publishing_jobs(policy_id,blog_id,content_version_id,idempotency_key,scheduled_at,
            status,adapter_type,simulation_only,oauth_connection_id,live_stage) VALUES (%s,%s,%s,%s,now(),%s,'blogger_live',false,%s,'draft_needed') RETURNING id""",
            (policy['id'],policy['blog_id'],version,str(uuid4()),status,oauth)).fetchone()['id']
        ids[status]=str(job)
        if status=='succeeded':
            conn.execute("""INSERT INTO publishing_records(job_id,blog_id,content_version_id,remote_post_id,published_at,remote_url,remote_status,remote_verified_at)
                VALUES (%s,%s,%s,%s,now(),'https://example.blogspot.com/test','LIVE',now())""",(job,policy['blog_id'],version,str(uuid4().int)))
    imported=conn.execute('SELECT import_id,content_version_id FROM external_content_import_content_links LIMIT 1').fetchone()
    conn.execute("INSERT INTO audit_events(event_type,payload) VALUES ('publication.auto_failure.recorded',%s)",
                 (Jsonb({'import_id':str(imported['import_id']),'content_version_id':str(imported['content_version_id']),
                         'blog_record_id':str(policy['blog_id']),'stage':'eligibility','failure_reason_code':'source_live_verification_missing'}),))
    before=conn.execute('SELECT count(*) n FROM audit_events').fetchone()['n']
    response=api.get('/admin/publications/worker-jobs',headers=headers)
    assert response.status_code==200,response.text
    data=response.json()
    assert data['period']=='all_time'
    for state,dbstate in [('queued','queued'),('running','running'),('published','succeeded'),('failed','failed')]:
        assert data['counts'][state]==baseline[state]+1
        filtered=api.get('/admin/publications/worker-jobs',headers=headers,params={'view':state}).json()
        assert any(item['job_id']==ids[dbstate] for item in filtered['items'])
    pre=api.get('/admin/publications/worker-jobs',headers=headers,params={'view':'pre_job_failure'}).json()
    assert any(item['import_id']==str(imported['import_id']) and item['job_id'] is None for item in pre['items'])
    assert conn.execute('SELECT count(*) n FROM audit_events').fetchone()['n']==before
    assert api.get('/admin/publications/worker-jobs').status_code==401
    assert api.get('/admin/publications/worker-jobs',headers=headers,params={'view':'invented'}).status_code==422


def test_pre_job_failure_yields_to_exact_real_job(lab,monkeypatch):
    conn,api,headers=lab
    @contextmanager
    def shared():
        with conn.transaction():yield conn
    monkeypatch.setattr(publication_monitor,'connection',shared)
    monkeypatch.setattr(publications,'connection',shared)
    row=conn.execute('''SELECT l.import_id,l.content_version_id,loc.language_code,loc.target_country
        FROM external_content_import_content_links l JOIN content_versions v ON v.id=l.content_version_id
        JOIN content_localizations loc ON loc.id=v.localization_id LIMIT 1''').fetchone()
    assert row
    profile=conn.execute('''INSERT INTO language_profiles(language_code,target_country) VALUES(%s,%s)
        ON CONFLICT(language_code,target_country) DO UPDATE SET search_intent=language_profiles.search_intent RETURNING id''',
        (row['language_code'],row['target_country'])).fetchone()['id']
    blog=conn.execute("INSERT INTO blogger_blogs(language_code,url,display_name,blog_id) VALUES(%s,%s,'Monitor fixture','1234567890') RETURNING id",
        (row['language_code'],'https://test-'+uuid4().hex[:12]+'.blogspot.com')).fetchone()['id']
    policy=conn.execute('INSERT INTO publishing_policies(language_code,blog_id,profile_id,active) VALUES(%s,%s,%s,false) RETURNING id',
        (row['language_code'],blog,profile)).fetchone()['id']
    row={**row,'policy_id':policy,'blog_id':blog}
    payload={'import_id':str(row['import_id']),'content_version_id':str(row['content_version_id']),
             'blog_record_id':str(row['blog_id']),'stage':'eligibility','failure_reason_code':'fixture'}
    event=conn.execute("INSERT INTO audit_events(event_type,payload) VALUES('publication.auto_failure.recorded',%s) RETURNING id",(Jsonb(payload),)).fetchone()['id']
    def failures():
        return api.get('/admin/publications/worker-jobs',headers=headers,params={'view':'pre_job_failure','page_size':100}).json()['items']
    def listed():
        return api.get('/admin/publications',headers=headers,params={'view':'auto_failure','page_size':100}).json()['items']
    assert any(x['import_id']==payload['import_id'] and x['content_version_id']==payload['content_version_id'] for x in failures())
    assert any(x['import_id']==payload['import_id'] and x['content_version_id']==payload['content_version_id'] for x in listed())
    oauth=conn.execute("INSERT INTO google_connections(label) VALUES('isolated retry fixture') RETURNING id").fetchone()['id']
    job=conn.execute("""INSERT INTO publishing_jobs(policy_id,blog_id,content_version_id,idempotency_key,scheduled_at,status,adapter_type,simulation_only,oauth_connection_id,live_stage)
       VALUES(%s,%s,%s,%s,now(),'queued','blogger_live',false,%s,'draft_needed') RETURNING id""",
       (row['policy_id'],row['blog_id'],row['content_version_id'],str(uuid4()),oauth)).fetchone()['id']
    for status in ('queued','running','failed','blocked','uncertain'):
        conn.execute('UPDATE publishing_jobs SET status=%s WHERE id=%s',(status,job))
        assert not any(x['import_id']==payload['import_id'] and x['content_version_id']==payload['content_version_id'] for x in failures())
        assert not any(x['import_id']==payload['import_id'] and x['content_version_id']==payload['content_version_id'] for x in listed())
    assert conn.execute('SELECT count(*) n FROM audit_events WHERE id=%s',(event,)).fetchone()['n']==1
