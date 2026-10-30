from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from psycopg.types.json import Jsonb
from test_pipeline import lab as shared_lab
from woori import keyword_jobs, trends
from woori import trend_editorial as editorial

lab=shared_lab


def bind(lab,monkeypatch):
    conn,api,headers=lab
    @contextmanager
    def shared():
        with conn.transaction():yield conn
    monkeypatch.setattr(editorial,'connection',shared)
    monkeypatch.setattr(trends,'connection',shared)
    monkeypatch.setattr(keyword_jobs,'connection',shared)
    return conn,api,headers


def observation(conn,query,geo='KR',payload=None,volume=1000):
    slot=conn.execute('SELECT run_id FROM trend_collection_slots WHERE geo=%s AND slot_at=%s',(geo,editorial.current_slot())).fetchone()
    if slot:run=slot['run_id']
    else:
        run=conn.execute("INSERT INTO trend_collection_runs(provider,geo,status,item_count) VALUES('google_trends_rss',%s,'succeeded',1) RETURNING id",(geo,)).fetchone()['id']
        conn.execute("INSERT INTO trend_collection_slots(geo,slot_at,run_id,result) VALUES(%s,%s,%s,%s)",(geo,editorial.current_slot(),run,Jsonb({'status':'succeeded'})))
    return conn.execute("""INSERT INTO trend_observations(run_id,geo,platform,query,source_url,response_sha256,raw_payload,source_volume_label,source_volume_lower_bound,trend_started_at)
        VALUES(%s,%s,'google_trends',%s,'https://trends.google.com/trending/rss',%s,%s,%s,%s,now()) RETURNING id""",
        (run,geo,query,'a'*64,Jsonb(payload or {}),f'{volume}+',volume)).fetchone()['id']


@pytest.mark.parametrize(('query','payload','expected'),[
    ('weather',{},('discarded','unclear_search_intent',None)),
    ('software launch',{'news_items':[{'title':'Software launch context'}]},('selected','specific_topic_requires_independent_research','technology')),
    ('software launch',{'news_items':[{'title':'Unrelated weather'}]},('selected','specific_topic_requires_independent_research','technology')),
    ('Private rumor',{},('discarded','unverifiable_rumor',None)),
    ('Some celebrity',{},('review_candidate','insufficient_context',None)),
    ('박현경',{'news_items':[{'title':'박현경 KLPGA 투어 대회 선두'}]},('selected','specific_topic_requires_independent_research','sports')),
    ('박현경',{'news_items':[{'title':'KBO 프로야구 플레이오프 경기 결과'}]},('review_candidate','insufficient_context',None)),
])
def test_rule_decisions_are_not_fabricated_scores(query,payload,expected):
    assert editorial.classify(query,payload)==expected


def test_feed_original_volume_category_and_news_context():
    raw=b'''<rss xmlns:ht="https://trends.google.com/trending/rss"><channel><language>en</language><item>
    <title>software launch</title><category>Source supplied only</category><ht:approx_traffic>20K+</ht:approx_traffic>
    <ht:news_item><ht:news_item_title>Official launch</ht:news_item_title><ht:news_item_url>https://example.gov/news</ht:news_item_url></ht:news_item></item>
    <item><title>Missing volume</title></item></channel></rss>'''
    one,two=trends.parse_feed(raw,'US')['items']
    assert one['source_volume_label']=='20K+' and one['source_volume_lower_bound']==20000
    assert one['source_categories']==['Source supplied only'] and one['source_language']=='en'
    assert one['raw_payload']['news_items'][0]['title']=='Official launch'
    assert two['source_volume_label'] is None and two['source_volume_lower_bound'] is None
    assert two['source_categories']==[]


def test_grouping_filters_discard_history_and_queue_contract(lab,monkeypatch):
    conn,api,h=bind(lab,monkeypatch)
    before=conn.execute('SELECT count(*) n FROM publishing_jobs').fetchone()['n']
    name='software technology '+uuid4().hex
    first=observation(conn,name,payload={'news_items':[{'title':name+' news context'}]})
    second=observation(conn,name.upper(),payload={'news_items':[{'title':name+' news context'}]})
    unrelated=observation(conn,name+' separate event')
    editorial.reconcile()
    detail=api.get('/admin/research/trend-editorial/'+str(first),headers=h).json()
    assert len(detail['related'])==2
    assert detail['history'][0]['state']=='selected'
    assert detail['history'][0]['evidence']['score'] is None
    topic=detail['topic_id']
    base='/admin/research/trend-editorial/topics/'+topic+'/decision'
    request={'request_key':str(uuid4()),'action':'discard','reason':'Explicit isolated test reason'}
    assert api.post(base,headers=h,json=request).status_code==200
    assert api.post(base,headers=h,json=request).status_code==200
    result=api.get('/admin/research/trend-editorial',params={'q':name,'status':'discarded'},headers=h).json()
    assert result['total']==2
    assert conn.execute('SELECT count(*) n FROM trend_observations WHERE id=ANY(%s)',([first,second,unrelated],)).fetchone()['n']==3
    request.update(request_key=str(uuid4()),action='reevaluate')
    assert api.post(base,headers=h,json=request).json()['state']=='selected'
    # A registered active Blogger is required; country mapping remains explicit.
    assert api.post(base,headers=h,json={**request,'request_key':str(uuid4()),'action':'queue','blog_id':str(uuid4())}).status_code==409
    assert conn.execute('SELECT count(*) n FROM publishing_jobs').fetchone()['n']==before


def test_same_slot_never_fetches_success_again(lab,monkeypatch):
    conn,_api,_h=bind(lab,monkeypatch)
    observation(conn,'slot test','KR')
    monkeypatch.setattr(trends,'_collect_geo',lambda _geo:pytest.fail('duplicate collection'))
    result=trends.collect_geo('KR')
    assert result['status']=='already_collected' and result['new_items']==0
    now=datetime(2026,10,30,2,0,tzinfo=UTC)
    assert trends.choose_hourly_geo({}, {}, None,now)[0] is not None
    reboot=datetime(2026,10,30,2,30,tzinfo=UTC)
    assert trends.choose_hourly_geo({}, {}, None,reboot)[0] is None
    assert trends.choose_hourly_geo({}, {}, None,reboot,allow_late=True)[0] is not None


def test_old_slot_candidate_expires_without_deleting_observation(lab,monkeypatch):
    conn,api,h=bind(lab,monkeypatch)
    name='software launch '+uuid4().hex
    observed=observation(conn,name,payload={'news_items':[{'title':name,'url':'https://example.gov/news'}]},volume=1000)
    editorial.reconcile()
    detail=api.get('/admin/research/trend-editorial/'+str(observed),headers=h).json()
    assert detail['history'][0]['state']=='selected'
    prior_slot=editorial.current_slot()
    assert editorial.slot_is_current(prior_slot.astimezone(trends.SCHEDULE_TIMEZONE).isoformat())
    monkeypatch.setattr(editorial,'current_slot',lambda:prior_slot+timedelta(hours=1))
    editorial.reconcile()
    result=api.get('/admin/research/trend-editorial/'+str(observed),headers=h).json()
    assert result['history'][0]['reason_code']=='expired_collection_slot'
    assert result['history'][0]['state']=='discarded'
    assert conn.execute('SELECT count(*) n FROM trend_observations WHERE id=%s',(observed,)).fetchone()['n']==1
    assert not editorial.slot_is_current(prior_slot.isoformat())


def test_selected_current_slot_queues_once_for_unambiguous_blog(lab,monkeypatch):
    conn,api,h=bind(lab,monkeypatch)
    name='software launch '+uuid4().hex
    low='software launch '+uuid4().hex
    observation(conn,low,payload={'news_items':[]},volume=100)
    observed=observation(conn,name,payload={'news_items':[{'title':name,'url':'https://example.gov/news'}]},volume=1000)
    editorial.reconcile()
    topic=api.get('/admin/research/trend-editorial/'+str(observed),headers=h).json()['topic_id']
    profile=conn.execute("INSERT INTO language_profiles(language_code,target_country) VALUES('ko','KR') ON CONFLICT(language_code,target_country) DO UPDATE SET search_intent=language_profiles.search_intent RETURNING id").fetchone()['id']
    blog=conn.execute("INSERT INTO blogger_blogs(language_code,url,display_name,blog_id) VALUES('ko',%s,'Slot fixture','1234567892') RETURNING id",('https://slot-'+uuid4().hex[:8]+'.blogspot.com',)).fetchone()['id']
    conn.execute("INSERT INTO publishing_policies(language_code,blog_id,profile_id,active) VALUES('ko',%s,%s,false)",(blog,profile))
    conn.execute("INSERT INTO trend_blog_geo_authoring(blog_id,geo,enabled,processing_order) VALUES(%s,'KR',true,1)",(blog,))
    monkeypatch.setattr(keyword_jobs,'targets',lambda _:[{'id':blog,'target_country':'KR','language_code':'ko'}])
    assert editorial.queue_selected()['created']==1
    assert editorial.queue_selected()['created']==0
    row=conn.execute('SELECT * FROM trend_generation_requests WHERE topic_id=%s',(topic,)).fetchone()
    assert row['contract']['selection_rank']==1 and row['contract']['source_country']=='KR'
    assert editorial.slot_is_current(row['contract']['collection_slot'])
    assert editorial.dispatch()['created']==1


def test_blog_geo_mapping_supports_multiple_countries_with_audit(lab,monkeypatch):
    conn,api,h=bind(lab,monkeypatch)
    profile=conn.execute("INSERT INTO language_profiles(language_code,target_country) VALUES('en','US') ON CONFLICT(language_code,target_country) DO UPDATE SET search_intent=language_profiles.search_intent RETURNING id").fetchone()['id']
    blog=conn.execute("INSERT INTO blogger_blogs(language_code,url,display_name,blog_id) VALUES('en',%s,'English mapping fixture','1234567897') RETURNING id",('https://map-'+uuid4().hex[:8]+'.blogspot.com',)).fetchone()['id']
    conn.execute("INSERT INTO publishing_policies(language_code,blog_id,profile_id,active) VALUES('en',%s,%s,false)",(blog,profile))
    before=conn.execute("SELECT count(*) n FROM audit_events WHERE event_type='trend.authoring.geo_mappings_changed'").fetchone()['n']
    result=api.put('/admin/research/trend-editorial/blog-geos',headers=h,json={'mappings':[
        {'blog_id':str(blog),'geo':'US','enabled':True,'processing_order':1},
        {'blog_id':str(blog),'geo':'GB','enabled':True,'processing_order':2}]})
    assert result.status_code==200
    rows=[m for m in result.json()['mappings'] if m['blog_id']==str(blog)]
    assert [(m['geo'],m['processing_order']) for m in rows]==[('US',1),('GB',2)]
    assert conn.execute("SELECT count(*) n FROM audit_events WHERE event_type='trend.authoring.geo_mappings_changed'").fetchone()['n']==before+1
    duplicate=api.put('/admin/research/trend-editorial/blog-geos',headers=h,json={'mappings':[
        {'blog_id':str(blog),'geo':'US','enabled':True,'processing_order':1},
        {'blog_id':str(blog),'geo':'GB','enabled':True,'processing_order':1}]})
    assert duplicate.status_code==422


def test_country_rank_queue_creates_distinct_jobs_for_one_multicountry_blog(lab,monkeypatch):
    conn,_api,_h=bind(lab,monkeypatch)
    profile=conn.execute("INSERT INTO language_profiles(language_code,target_country) VALUES('en','US') ON CONFLICT(language_code,target_country) DO UPDATE SET search_intent=language_profiles.search_intent RETURNING id").fetchone()['id']
    blog=conn.execute("INSERT INTO blogger_blogs(language_code,url,display_name,blog_id) VALUES('en',%s,'Multi-country fixture','1234567901') RETURNING id",('https://multi-'+uuid4().hex[:8]+'.blogspot.com',)).fetchone()['id']
    conn.execute("INSERT INTO publishing_policies(language_code,blog_id,profile_id,active) VALUES('en',%s,%s,false)",(blog,profile))
    conn.execute("INSERT INTO trend_blog_geo_authoring(blog_id,geo,enabled,processing_order) VALUES(%s,'US',true,1),(%s,'GB',true,2)",(blog,blog))
    us=observation(conn,'technology launch united states','US',payload={},volume=9000)
    gb=observation(conn,'technology launch united kingdom','GB',payload={},volume=1200)
    editorial.reconcile()
    monkeypatch.setattr(keyword_jobs,'targets',lambda _:[{'id':blog,'target_country':'US','language_code':'en'}])
    queued=editorial.queue_selected()
    assert queued['created']==2
    contracts=conn.execute("SELECT contract->>'source_country' country,contract->>'target_language' language FROM trend_generation_requests WHERE contract->>'target_blog_id'=%s ORDER BY contract->>'source_country'",(str(blog),)).fetchall()
    assert [(r['country'],r['language']) for r in contracts]==[('GB','en'),('US','en')]
    assert {r['id'] for r in conn.execute("SELECT * FROM trend_observations WHERE id=ANY(%s)",([us,gb],)).fetchall()}=={us,gb}


def test_country_rank_queue_falls_through_after_insufficient_evidence(lab,monkeypatch):
    conn,_api,_h=bind(lab,monkeypatch)
    profile=conn.execute("INSERT INTO language_profiles(language_code,target_country) VALUES('ko','KR') ON CONFLICT(language_code,target_country) DO UPDATE SET search_intent=language_profiles.search_intent RETURNING id").fetchone()['id']
    blog=conn.execute("INSERT INTO blogger_blogs(language_code,url,display_name,blog_id) VALUES('ko',%s,'Rank fallback fixture','1234567902') RETURNING id",('https://fallback-'+uuid4().hex[:8]+'.blogspot.com',)).fetchone()['id']
    conn.execute("INSERT INTO publishing_policies(language_code,blog_id,profile_id,active) VALUES('ko',%s,%s,false)",(blog,profile))
    conn.execute("INSERT INTO trend_blog_geo_authoring(blog_id,geo,enabled,processing_order) VALUES(%s,'KR',true,1)",(blog,))
    observation(conn,'technology launch highest rank','KR',payload={},volume=9000)
    observation(conn,'software platform product update','KR',payload={},volume=1200)
    editorial.reconcile()
    monkeypatch.setattr(keyword_jobs,'targets',lambda _:[{'id':blog,'target_country':'KR','language_code':'ko'}])
    assert editorial.queue_selected()['created']==1
    assert editorial.dispatch()['created']==1
    first=conn.execute("SELECT id,keyword FROM codex_authoring_jobs WHERE job_type='google_trends'").fetchone()
    assert first['keyword']=='technology launch highest rank'
    keyword_jobs.state(first['id'],'failed',error_code='insufficient_evidence',completed_at=datetime.now(UTC))
    assert editorial.queue_selected()['created']==1
    assert editorial.dispatch()['created']==1
    second=conn.execute("SELECT id,keyword FROM codex_authoring_jobs WHERE job_type='google_trends' AND id<>%s",(first['id'],)).fetchone()
    assert second['keyword']=='software platform product update'


def test_trends_insufficient_evidence_is_failed_without_ready_import_or_publication(lab,monkeypatch,tmp_path):
    conn,api,h=bind(lab,monkeypatch)
    name='technology launch '+uuid4().hex
    observed=observation(conn,name,payload={})
    editorial.reconcile()
    topic=api.get('/admin/research/trend-editorial/'+str(observed),headers=h).json()['topic_id']
    profile=conn.execute("INSERT INTO language_profiles(language_code,target_country) VALUES('ko','KR') ON CONFLICT(language_code,target_country) DO UPDATE SET search_intent=language_profiles.search_intent RETURNING id").fetchone()['id']
    blog=conn.execute("INSERT INTO blogger_blogs(language_code,url,display_name,blog_id) VALUES('ko',%s,'Evidence refusal fixture','1234567903') RETURNING id",('https://refusal-'+uuid4().hex[:8]+'.blogspot.com',)).fetchone()['id']
    conn.execute("INSERT INTO publishing_policies(language_code,blog_id,profile_id,active) VALUES('ko',%s,%s,false)",(blog,profile))
    conn.execute("INSERT INTO trend_blog_geo_authoring(blog_id,geo,enabled,processing_order) VALUES(%s,'KR',true,1)",(blog,))
    editorial.decision(topic,editorial.Decision(request_key=uuid4(),action='queue',reason='isolated test',blog_id=blog))
    assert editorial.dispatch()['created']==1
    job=conn.execute("SELECT * FROM codex_authoring_jobs WHERE job_type='google_trends' AND trend_request_id IS NOT NULL ORDER BY created_at DESC LIMIT 1").fetchone()
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path/'local'))
    monkeypatch.setattr(keyword_jobs,'ROOT',tmp_path/'project')
    monkeypatch.setattr(keyword_jobs,'INBOX',tmp_path/'project'/'inbox')
    def decline(work,prompt,schema,callback,cancelled):
        assert schema['required']==['status','article','reason']
        assert 'source country KR' in prompt
        assert 'insufficient_evidence' in prompt
        callback('researching',{'execution_id':'isolated-refusal'})
        return {'status':'insufficient_evidence','article':None,'reason':'No current event was supported by opened sources.'}, {'opened_urls':{},'web_search_count':1,'execution_id':'isolated-refusal'}
    monkeypatch.setattr(keyword_jobs.codex_runner,'execute',decline)
    before=conn.execute('SELECT count(*) n FROM publishing_jobs').fetchone()['n']
    keyword_jobs.generate(dict(job))
    result=conn.execute('SELECT state,error_code,import_id,content_version_id FROM codex_authoring_jobs WHERE id=%s',(job['id'],)).fetchone()
    request=conn.execute('SELECT state FROM trend_generation_requests WHERE authoring_job_id=%s',(job['id'],)).fetchone()
    assert result['state']=='failed' and result['error_code']=='insufficient_evidence'
    assert result['import_id'] is None and result['content_version_id'] is None
    assert request['state']=='failed'
    assert not (keyword_jobs.INBOX/'ready'/f"{job['id']}.ready.json").exists()
    assert conn.execute('SELECT count(*) n FROM publishing_jobs').fetchone()['n']==before


def test_trends_queue_dispatch_has_distinct_provenance_and_no_publication(lab,monkeypatch):
    conn,api,h=bind(lab,monkeypatch)
    name='software technology '+uuid4().hex
    observation_id=observation(conn,name,payload={'news_items':[{'title':name+' news context','url':'https://example.gov/news'}]})
    editorial.reconcile()
    topic=api.get('/admin/research/trend-editorial/'+str(observation_id),headers=h).json()['topic_id']
    profile=conn.execute("INSERT INTO language_profiles(language_code,target_country) VALUES('ko','KR') ON CONFLICT(language_code,target_country) DO UPDATE SET search_intent=language_profiles.search_intent RETURNING id").fetchone()['id']
    blog=conn.execute("INSERT INTO blogger_blogs(language_code,url,display_name,blog_id) VALUES('ko',%s,'Trends test blog','1234567890') RETURNING id",('https://trend-'+uuid4().hex[:8]+'.blogspot.com',)).fetchone()['id']
    conn.execute("INSERT INTO publishing_policies(language_code,blog_id,profile_id,active) VALUES('ko',%s,%s,false)",(blog,profile))
    conn.execute("INSERT INTO trend_blog_geo_authoring(blog_id,geo,enabled,processing_order) VALUES(%s,'KR',true,1)",(blog,))
    request={'request_key':str(uuid4()),'action':'queue','reason':'Exact region research queue for isolated test','blog_id':str(blog)}
    path=f'/admin/research/trend-editorial/topics/{topic}/decision'
    assert api.post(path,headers=h,json=request).status_code==200
    before=conn.execute('SELECT count(*) n FROM publishing_jobs').fetchone()['n']
    result=editorial.dispatch()
    assert result['created']==1
    job=conn.execute("SELECT * FROM codex_authoring_jobs WHERE job_type='google_trends' ORDER BY created_at DESC LIMIT 1").fetchone()
    assert job['trend_request_id'] and job['state']=='queued'
    assert editorial.dispatch()['created']==0
    assert conn.execute('SELECT count(*) n FROM publishing_jobs').fetchone()['n']==before
    conn.execute("UPDATE codex_authoring_jobs SET state='failed',error_code='codex_execution_failed' WHERE id=%s",(job['id'],))
    retry=api.post(f"/admin/keyword-authoring/{job['id']}/retry",headers=h,json={'request_key':str(uuid4())})
    assert retry.status_code==409 and retry.json()['detail']=='trend_retry_requires_saved_result_or_reconciliation'
    assert conn.execute('SELECT count(*) n FROM codex_authoring_jobs WHERE parent_job_id=%s',(job['id'],)).fetchone()['n']==0
    conn.execute("UPDATE codex_authoring_jobs SET state='queued' WHERE id=%s",(job['id'],))
    old_slot=editorial.current_slot()
    monkeypatch.setattr(editorial,'current_slot',lambda:old_slot+timedelta(hours=1))
    conn.execute("UPDATE codex_authoring_jobs SET state='researching',execution_id='already-started' WHERE id=%s",(job['id'],))
    assert editorial.expire_pending()==0
    conn.execute("UPDATE codex_authoring_jobs SET state='queued',execution_id=NULL WHERE id=%s",(job['id'],))
    assert editorial.expire_pending()==1
    expired=conn.execute('SELECT state,error_code FROM codex_authoring_jobs WHERE id=%s',(job['id'],)).fetchone()
    assert expired['state']=='cancelled' and expired['error_code']=='expired_collection_slot'
    assert conn.execute('SELECT count(*) n FROM trend_observations WHERE id=%s',(observation_id,)).fetchone()['n']==1
