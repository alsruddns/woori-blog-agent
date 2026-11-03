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
    states={item['job_id']:item['state'] for item in data['items'] if item.get('job_id') in set(ids.values())}
    assert set(states)==set(ids.values())
    assert states[ids['succeeded']]=='published'
    assert states[ids['failed']]=='failed'
    assert states[ids['queued']] in {'queued','auto_paused'}
    assert states[ids['running']] in {'running','auto_paused'}
    job_states=('queued','running','published','draft_saved','failed','auto_paused','manual_action_required','resolved')
    assert sum(data['counts'][state]-baseline[state] for state in job_states)==4
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
    other_blog=conn.execute("INSERT INTO blogger_blogs(language_code,url,display_name,blog_id) VALUES(%s,%s,'Other blog','1234567891') RETURNING id",
        (row['language_code'],'https://test-'+uuid4().hex[:12]+'.blogspot.com')).fetchone()['id']
    other_policy=conn.execute('INSERT INTO publishing_policies(language_code,blog_id,profile_id,active) VALUES(%s,%s,%s,false) RETURNING id',
        (row['language_code'],other_blog,profile)).fetchone()['id']
    conn.execute("""INSERT INTO publishing_jobs(policy_id,blog_id,content_version_id,idempotency_key,scheduled_at,status,adapter_type,simulation_only,oauth_connection_id,live_stage)
       VALUES(%s,%s,%s,%s,now(),'queued','blogger_live',false,%s,'draft_needed')""",
       (other_policy,other_blog,row['content_version_id'],str(uuid4()),oauth))
    assert any(x['import_id']==payload['import_id'] and x['content_version_id']==payload['content_version_id'] for x in listed())
    job=conn.execute("""INSERT INTO publishing_jobs(policy_id,blog_id,content_version_id,idempotency_key,scheduled_at,status,adapter_type,simulation_only,oauth_connection_id,live_stage)
       VALUES(%s,%s,%s,%s,now(),'queued','blogger_live',false,%s,'draft_needed') RETURNING id""",
       (row['policy_id'],row['blog_id'],row['content_version_id'],str(uuid4()),oauth)).fetchone()['id']
    for status in ('queued','running','failed','blocked','uncertain'):
        conn.execute('UPDATE publishing_jobs SET status=%s WHERE id=%s',(status,job))
        assert not any(x['import_id']==payload['import_id'] and x['content_version_id']==payload['content_version_id'] for x in failures())
        assert not any(x['import_id']==payload['import_id'] and x['content_version_id']==payload['content_version_id'] for x in listed())
    assert conn.execute('SELECT count(*) n FROM audit_events WHERE id=%s',(event,)).fetchone()['n']==1


def test_archived_pre_job_failure_is_separated_and_summarized(lab,monkeypatch):
    conn,api,headers=lab

    @contextmanager
    def shared():
        with conn.transaction():
            yield conn

    monkeypatch.setattr(publication_monitor,'connection',shared)
    version=conn.execute('''SELECT v.id,v.group_id,l.import_id,loc.language_code,blog.id blog_id
        FROM external_content_import_content_links l JOIN content_versions v ON v.id=l.content_version_id
        JOIN content_localizations loc ON loc.id=v.localization_id
        JOIN blogger_blogs blog ON blog.language_code=loc.language_code AND blog.active
        ORDER BY v.created_at DESC LIMIT 1''').fetchone()
    assert version
    payload={'import_id':str(version['import_id']),'content_version_id':str(version['id']),
        'blog_record_id':str(version['blog_id']),'stage':'eligibility',
        'failure_reason_code':'global_publication_mode_mismatch','reason_codes':['global_publication_mode_mismatch']}
    event=conn.execute("INSERT INTO audit_events(event_type,payload) VALUES('publication.auto_failure.recorded',%s) RETURNING id",(Jsonb(payload),)).fetchone()['id']
    conn.execute("""INSERT INTO manuscript_discards(group_id,blog_id,content_version_id,status,previous_view,reason,actor)
        VALUES(%s,%s,%s,'discarded','auto_failure','archive test fixture reason','test')""",
        (version['group_id'],version['blog_id'],version['id']))
    before=conn.execute('SELECT count(*) n FROM publishing_jobs').fetchone()['n']
    active=api.get('/admin/publications/worker-jobs',headers=headers,params={'view':'pre_job_failure','page_size':100}).json()
    archived=api.get('/admin/publications/worker-jobs',headers=headers,params={'view':'archived_failure','page_size':100}).json()
    item=next(x for x in archived['items'] if x['failure_event_id']==event)
    assert not any(x.get('failure_event_id')==event for x in active['items'])
    assert item['state']=='archived_failure'
    assert item['manuscript_id']==str(version['group_id'])
    assert item['root_cause_classification']=='reevaluation_possible'
    assert item['safety_classification']=='publish_prohibited_discarded'
    assert active['pre_job_failure_summary']['archived_count']>=1
    assert conn.execute('SELECT count(*) n FROM publishing_jobs').fetchone()['n']==before


def test_pre_job_failure_recheck_only_records_review_no_job_or_blogger_write(lab,monkeypatch):
    conn,api,headers=lab

    @contextmanager
    def shared():
        with conn.transaction():
            yield conn

    monkeypatch.setattr(publication_monitor,'connection',shared)
    from woori import publication_failure_review
    monkeypatch.setattr(publication_failure_review,'connection',shared)
    version=conn.execute('''SELECT v.id,v.group_id,l.import_id,loc.language_code,blog.id blog_id
        FROM external_content_import_content_links l JOIN content_versions v ON v.id=l.content_version_id
        JOIN content_localizations loc ON loc.id=v.localization_id
        JOIN blogger_blogs blog ON blog.language_code=loc.language_code AND blog.active
        ORDER BY v.created_at DESC LIMIT 1''').fetchone()
    assert version
    payload={'import_id':str(version['import_id']),'content_version_id':str(version['id']),
        'blog_record_id':str(version['blog_id']),'stage':'eligibility',
        'failure_reason_code':'global_publication_mode_mismatch','reason_codes':['global_publication_mode_mismatch']}
    event=conn.execute("INSERT INTO audit_events(event_type,payload) VALUES('publication.auto_failure.recorded',%s) RETURNING id",(Jsonb(payload),)).fetchone()['id']
    before_jobs=conn.execute('SELECT count(*) n FROM publishing_jobs').fetchone()['n']
    before_attempts=conn.execute('SELECT count(*) n FROM live_publication_attempts').fetchone()['n']
    request={'targets':[{'event_id':event,'import_id':str(version['import_id']),
        'content_version_id':str(version['id']),'blog_id':str(version['blog_id'])}],
        'actor':'test-admin','reason':'수동으로 발행 가능 여부 재검사'}
    response=api.post('/admin/publications/worker-jobs/recheck',headers=headers,json=request)
    assert response.status_code==200,response.text
    data=response.json()
    assert data['job_created'] is False and data['blogger_write_performed'] is False
    assert data['results'][0]['event_id']==event
    assert data['results'][0]['status']=='blocked'
    assert conn.execute('SELECT count(*) n FROM publishing_jobs').fetchone()['n']==before_jobs
    assert conn.execute('SELECT count(*) n FROM live_publication_attempts').fetchone()['n']==before_attempts
    audit=conn.execute("SELECT payload FROM audit_events WHERE event_type='publication.pre_job_failure.rechecked' ORDER BY id DESC LIMIT 1").fetchone()
    assert audit and audit['payload']['job_created'] is False and audit['payload']['blogger_write_performed'] is False
    assert api.post('/admin/publications/worker-jobs/recheck',headers=headers,json={**request,'reason':'short'}).status_code==422


def test_failure_history_archive_and_restore_are_append_only_and_do_not_discard_manuscript(lab,monkeypatch):
    conn,api,headers=lab

    @contextmanager
    def shared():
        with conn.transaction():
            yield conn

    monkeypatch.setattr(publication_monitor,'connection',shared)
    from woori import publication_failure_review
    monkeypatch.setattr(publication_failure_review,'connection',shared)
    version=conn.execute("""SELECT v.id,v.group_id,l.import_id,loc.language_code,blog.id blog_id
        FROM external_content_import_content_links l JOIN content_versions v ON v.id=l.content_version_id
        JOIN content_localizations loc ON loc.id=v.localization_id
        JOIN blogger_blogs blog ON blog.language_code=loc.language_code AND blog.active
        WHERE NOT EXISTS(SELECT 1 FROM manuscript_discards d WHERE d.group_id=v.group_id AND d.blog_id=blog.id)
        ORDER BY v.created_at DESC LIMIT 1""").fetchone()
    assert version
    payload={'import_id':str(version['import_id']),'content_version_id':str(version['id']),
        'blog_record_id':str(version['blog_id']),'stage':'eligibility',
        'failure_reason_code':'global_publication_mode_mismatch'}
    event=conn.execute("INSERT INTO audit_events(event_type,payload) VALUES('publication.auto_failure.recorded',%s) RETURNING id",(Jsonb(payload),)).fetchone()['id']
    before_discards=conn.execute('SELECT count(*) n FROM manuscript_discards').fetchone()['n']
    request={'action':'archive','targets':[{'event_id':event,'import_id':str(version['import_id']),
        'content_version_id':str(version['id']),'blog_id':str(version['blog_id'])}],
        'actor':'test-admin','reason':'\uC624\uB958 \uC774\uB825 \uBCF4\uAD00 \uD655\uC778'}
    archived=api.post('/admin/publications/worker-jobs/history',headers=headers,json=request)
    assert archived.status_code==200,archived.text
    assert archived.json()['results'][0]['status']=='archived'
    archived_view=api.get('/admin/publications/worker-jobs',headers=headers,params={'view':'archived_failure','page_size':100}).json()
    assert any(item.get('failure_event_id')==event for item in archived_view['items'])
    restore=api.post('/admin/publications/worker-jobs/history',headers=headers,json={**request,'action':'restore'})
    assert restore.status_code==200,restore.text
    active_view=api.get('/admin/publications/worker-jobs',headers=headers,params={'view':'pre_job_failure','page_size':100}).json()
    assert any(item.get('failure_event_id')==event for item in active_view['items'])
    assert conn.execute('SELECT count(*) n FROM manuscript_discards').fetchone()['n']==before_discards
    events=conn.execute("SELECT event_type FROM audit_events WHERE payload->>'failure_event_id'=%s ORDER BY id",(str(event),)).fetchall()
    assert [row['event_type'] for row in events]==['publication.pre_job_failure.archived','publication.pre_job_failure.restored']


def test_pre_job_root_cause_and_current_safety_are_classified_separately():
    classify=publication_monitor._pre_job_classification
    root,safety=classify({'payload':{'failure_reason_code':'global_publication_mode_mismatch'},'discard_status':'discarded','blog_active':True,'language_active':True})
    assert root=='reevaluation_possible' and safety=='publish_prohibited_discarded'
    root,safety=classify({'payload':{'failure_reason_code':'source_live_verification_missing'},'blog_active':True,'language_active':True})
    assert root=='manuscript_revision_required' and safety=='manuscript_review_required'
    root,safety=classify({'payload':{'failure_reason_code':'collection_predates_policy_activation'},'blog_active':True,'language_active':True})
    assert root=='history' and safety=='historical_policy_failure'
    root,safety=classify({'payload':{'failure_reason_code':'remote_duplicate_found'},'blog_active':True,'language_active':True})
    assert root=='publish_prohibited' and safety=='publish_prohibited_duplicate_or_discarded'
