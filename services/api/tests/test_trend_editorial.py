from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from psycopg.types.json import Jsonb
from test_pipeline import lab as shared_lab
from woori import trend_editorial as editorial
from woori import trends

lab=shared_lab


def bind(lab,monkeypatch):
    conn,api,headers=lab
    @contextmanager
    def shared():
        with conn.transaction():yield conn
    monkeypatch.setattr(editorial,'connection',shared)
    monkeypatch.setattr(trends,'connection',shared)
    return conn,api,headers


def observation(conn,query,geo='KR',payload=None):
    run=conn.execute("INSERT INTO trend_collection_runs(provider,geo,status,item_count) VALUES('google_trends_rss',%s,'succeeded',1) RETURNING id",(geo,)).fetchone()['id']
    return conn.execute("""INSERT INTO trend_observations(run_id,geo,platform,query,source_url,response_sha256,raw_payload)
        VALUES(%s,%s,'google_trends',%s,'https://trends.google.com/trending/rss',%s,%s) RETURNING id""",
        (run,geo,query,'a'*64,Jsonb(payload or {}))).fetchone()['id']


@pytest.mark.parametrize(('query','payload','expected'),[
    ('weather',{},('discarded','unclear_search_intent',None)),
    ('software launch',{'news_items':[{'title':'Software launch context'}]},('selected','specific_topic_with_news_context','technology')),
    ('software launch',{'news_items':[{'title':'Unrelated weather'}]},('review_candidate','news_context_mismatch','technology')),
    ('Private rumor',{},('discarded','unverifiable_rumor',None)),
    ('Some celebrity',{},('review_candidate','insufficient_context',None)),
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
    # An exact registered region/language policy is required; no cross-country fallback.
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


def test_trends_queue_dispatch_has_distinct_provenance_and_no_publication(lab,monkeypatch):
    conn,api,h=bind(lab,monkeypatch)
    name='software technology '+uuid4().hex
    observation_id=observation(conn,name,payload={'news_items':[{'title':name+' news context'}]})
    editorial.reconcile()
    topic=api.get('/admin/research/trend-editorial/'+str(observation_id),headers=h).json()['topic_id']
    profile=conn.execute("INSERT INTO language_profiles(language_code,target_country) VALUES('ko','KR') ON CONFLICT(language_code,target_country) DO UPDATE SET search_intent=language_profiles.search_intent RETURNING id").fetchone()['id']
    blog=conn.execute("INSERT INTO blogger_blogs(language_code,url,display_name,blog_id) VALUES('ko',%s,'Trends test blog','1234567890') RETURNING id",('https://trend-'+uuid4().hex[:8]+'.blogspot.com',)).fetchone()['id']
    conn.execute("INSERT INTO publishing_policies(language_code,blog_id,profile_id,active) VALUES('ko',%s,%s,false)",(blog,profile))
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
