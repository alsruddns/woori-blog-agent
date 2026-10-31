from contextlib import contextmanager
from copy import deepcopy
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_content_imports import valid_item
from test_pipeline import lab as shared_lab
from test_trends_publication import _Result, _TrendsEnqueueConnection
from woori import (
    content_imports,
    external_policy,
    publication_worker,
    publications,
    scheduled_duplicates,
    trends_publication,
)
from woori.editorial_taxonomy import suggested_labels
from woori.trends_publication import assess_trends_article, enqueue_trends_auto_jobs

lab = shared_lab
BODY = ("## Practical considerations\n\n"
        "A useful guide explains the options and their trade-offs. Readers can compare the steps against their own needs. "
        "The discussion offers general guidance rather than reporting an unconfirmed event. " * 3)


def item():
    return valid_item(content_id=str(uuid4()), generation_method="codex_trends_export",
        google_trends_based=True, category="technology", sources=[], source_ids=[], claims=[],
        fact_checked_at=None, body_markdown=BODY, title="A practical guide to organizing information",
        blogger_labels=suggested_labels("technology", "en", google_trends_based=True))


def test_source_free_trends_import_commits_only_inside_isolated_rollback(lab, monkeypatch):
    conn, api, headers = lab
    @contextmanager
    def shared():
        with conn.transaction():
            yield conn
    monkeypatch.setattr(content_imports, "connection", shared)
    payload = item()
    before = conn.execute("SELECT count(*) n FROM publishing_jobs").fetchone()["n"]
    response = api.post("/admin/research/content-imports", headers=headers,
        json={"submitted_by": "isolated test", "item": payload})
    assert response.status_code == 201, response.text
    assert response.json()["content_version_id"]
    stored = conn.execute("SELECT claims,sources,fact_checked_at FROM external_content_imports WHERE id=%s",
        (response.json()["import_id"],)).fetchone()
    assert stored == {"claims": [], "sources": [], "fact_checked_at": None}
    assert conn.execute("SELECT count(*) n FROM publishing_jobs").fetchone()["n"] == before
    with pytest.raises(ValueError, match="non_trends_evidence_required"):
        content_imports.ContentImport.model_validate({**payload, "generation_method": "manual_codex_import"})
    with pytest.raises(ValueError, match="insufficient_evidence"):
        content_imports.ContentImport.model_validate({**payload, "title": "Insufficient evidence for this topic"})


def test_unverified_claims_pass_basic_trends_check_without_mutation():
    payload = item()
    payload["claims"] = [{"verification_status": "unverified", "factual_state": "unverified"}]
    original = deepcopy(payload)
    assert assess_trends_article(payload, BODY)["reasons"] == []
    assert payload == original
    assert "article_title_or_body_insufficient" in assess_trends_article(payload, "short")["reasons"]
    assert "high_impact_topic_requires_review" in assess_trends_article({**payload, "title": "Unconfirmed death report"}, BODY)["reasons"]
    payload["claims"][0]["verification_status"] = "conflict"
    assert "known_conflicting_claim" in assess_trends_article(payload, BODY)["reasons"]


def test_unverified_trends_job_enqueue_and_duplicate_reuse(monkeypatch):
    class Fake(_TrendsEnqueueConnection):
        saved = None
        def execute(self, query, params=None):
            if "SELECT body FROM content_versions" in query:
                return _Result({"body": BODY})
            if "SELECT id,status FROM publishing_jobs" in query:
                return _Result({"id": self.saved, "status": "queued"} if self.saved else None)
            if "AS n" in query:
                return _Result({"n": 0})
            if "SELECT p.id FROM publishing_policies" in query:
                return _Result({"id": uuid4()})
            if "INSERT INTO publishing_jobs" in query:
                self.saved = uuid4()
                return _Result({"id": self.saved})
            result = super().execute(query, params)
            if "FROM trends_publication_policy_events p JOIN blogger_blogs" in query:
                result.rows[0]["id"] = 1
            if "FROM external_content_imports i" in query:
                result.rows[0].update(title="A practical guide to organizing information", category="technology")
            return result
    fake = Fake([{"claim_id": "c", "verification_status": "unverified", "factual_state": "unverified"}])
    @contextmanager
    def shared():
        yield fake
    monkeypatch.setattr("woori.trends_publication.connection", shared)
    monkeypatch.setattr(external_policy, "_blogger_policy_approval", lambda: {"approved": True})
    monkeypatch.setattr(external_policy, "_blogger_operation_is_approved", lambda _: True)
    monkeypatch.setattr(scheduled_duplicates, "find_remote_duplicate", lambda *_, **__: {"status": "clear"})
    assert enqueue_trends_auto_jobs() == {"created": 1, "held": 0}
    assert enqueue_trends_auto_jobs() == {"created": 0, "held": 0}
    assert fake.claims[0]["verification_status"] == "unverified"


@pytest.mark.parametrize("mode,recover,language", [("draft",False,"en"),("publish",False,"en"),("draft",True,"en"),("draft",False,"ja"),("draft",False,"ko")])
def test_isolated_import_enqueue_worker_and_live_receipt(lab, monkeypatch, mode, recover, language):
    conn, api, headers = lab
    geo={"en":"US","ja":"JP","ko":"KR"}[language]
    @contextmanager
    def shared():
        with conn.transaction():
            yield conn
    for module in (content_imports, publications, publication_worker, trends_publication):
        monkeypatch.setattr(module, "connection", shared)
    monkeypatch.setattr(external_policy, "_blogger_policy_approval", lambda: {"approved": True})
    monkeypatch.setattr(external_policy, "_blogger_operation_is_approved", lambda op: mode != "draft" or op != "blogger_public_publish")
    monkeypatch.setattr(scheduled_duplicates, "find_remote_duplicate", lambda *_, **__: {"status": "clear"})
    monkeypatch.setattr(publication_worker, "find_remote_duplicate", lambda *_, **__: {"status": "clear"})
    payload = item()
    if language != 'en':
        payload.update(language_code=language,source_region=geo,
            target_audiences=[{'language_code':language,'target_region':geo,'reader_relevance_reason':'Localized isolated contract test'}],
            title='資料整理の進め方と比較のポイント' if language=='ja' else '자료 정리 방법과 비교 기준을 살펴보는 안내',
            body_markdown=('資料を整理する際は、目的と読み手を確認し、情報を比較しやすい形にまとめます。手順と選択肢を区別し、必要な情報を見つけやすくすることが大切です。' if language=='ja' else '자료를 정리할 때는 목적과 독자를 확인하고 정보를 비교하기 쉬운 형태로 구성합니다. 절차와 선택지를 구분하고 필요한 정보를 찾기 쉽게 정리하는 방법을 설명합니다.')*8,
            blogger_labels=suggested_labels('technology',language,google_trends_based=True))
    payload['claims'] = [{"claim_id": "general", "claim": "Readers can compare organizational approaches.",
        "source_ids": [], "evidence_excerpt": "", "verification_status": "unverified", "factual_state": "unverified"}]
    response = api.post('/admin/research/content-imports', headers=headers, json={'submitted_by': 'isolated', 'item': payload})
    assert response.status_code == 201, response.text
    imported, version = response.json()['import_id'], response.json()['content_version_id']
    oauth = conn.execute("INSERT INTO google_connections(label,status,scopes) VALUES ('isolated','connected',%s) RETURNING id",
        (['https://www.googleapis.com/auth/blogger'],)).fetchone()['id']
    blog = conn.execute("""INSERT INTO blogger_blogs(language_code,url,display_name,blog_id,oauth_connection_id,
        connection_verified_at,test_publish_verified_at) VALUES (%s,%s,'isolated','1234567890',%s,now(),now()) RETURNING id""",
        (language,'https://isolated-'+uuid4().hex+'.blogspot.com', oauth)).fetchone()['id']
    profile = conn.execute("INSERT INTO language_profiles(language_code,target_country) VALUES (%s,%s) ON CONFLICT(language_code,target_country) DO UPDATE SET search_intent=language_profiles.search_intent RETURNING id",(language,geo)).fetchone()['id']
    conn.execute("INSERT INTO publishing_policies(language_code,blog_id,profile_id) VALUES (%s,%s,%s)", (language,blog,profile))
    conn.execute("UPDATE trend_blog_geo_authoring SET enabled=false WHERE geo=%s",(geo,))
    conn.execute("INSERT INTO trend_blog_geo_authoring(blog_id,geo,enabled,processing_order) VALUES (%s,%s,true,1)",(blog,geo))
    if mode == 'draft':
        conn.execute("UPDATE blogger_blogs SET test_publish_verified_at=NULL WHERE id=%s",(blog,))
    conn.execute("INSERT INTO audit_events(event_type,payload) VALUES ('publication.trends_auto.connection_check',%s)",
        (Jsonb({'results':[{'blog_record_id':str(blog),'remote_blog_id':'1234567890','verified':True}]}),))
    approvals_before=conn.execute("SELECT count(*) n FROM audit_events WHERE event_type='publication.trends_public_write.approved'").fetchone()['n']
    policy_response=api.post('/admin/publications/trends-auto-policy',headers=headers,json={
        'blog_id':str(blog),'enabled':True,'allowed_geos':[geo],'publication_mode':mode,'daily_limit':None,
        'actor_label':'isolated manager','reason':'Isolated policy lifecycle test','idempotency_key':uuid4().hex,
        'confirmation':'ENABLE TRENDS AUTO PUBLICATION' if mode=='publish' else ''})
    assert policy_response.status_code==201, policy_response.text
    approvals_after=conn.execute("SELECT count(*) n FROM audit_events WHERE event_type='publication.trends_public_write.approved'").fetchone()['n']
    assert approvals_after-approvals_before == (1 if mode=='publish' else 0)
    topic=uuid4()
    conn.execute("INSERT INTO trend_topics(id,normalized_key,representative_geo,representative_query,grouping_method,grouping_confidence,grouping_status) VALUES (%s,%s,%s,'organization','single_observation',1,'exact_query_cluster_not_event_confirmed')",(topic,uuid4().hex,geo))
    job=conn.execute("""INSERT INTO codex_authoring_jobs(request_key,request_sha256,job_type,blog_id,language_code,target_country,
        category,keyword,options,state,model,import_id,content_version_id) VALUES (%s,%s,'google_trends',%s,%s,%s,
        'technology','organization','{}','imported_review','isolated',%s,%s) RETURNING id""",(uuid4(),'a'*64,blog,language,geo,imported,version)).fetchone()['id']
    slot=conn.execute('SELECT now() stamp').fetchone()['stamp'].isoformat()
    contract={'target_blog_id':str(blog),'target_language':language,'target_country':geo,'source_country':geo,'collection_slot':slot}
    conn.execute("INSERT INTO trend_generation_requests(topic_id,duplicate_key,contract,state,authoring_job_id) VALUES (%s,%s,%s,'imported',%s)",(topic,uuid4().hex,Jsonb(contract),job))
    conn.execute("UPDATE publication_mode_settings SET emergency_stopped=false WHERE scope_type='global' AND scope_key=''")
    assert enqueue_trends_auto_jobs()['created']==1
    assert enqueue_trends_auto_jobs()['created']==0
    bound=conn.execute("SELECT id,publication_mode,trends_policy_event_id FROM publishing_jobs WHERE blog_id=%s",(blog,)).fetchone()
    assert bound['publication_mode']==mode and bound['trends_policy_event_id']
    with pytest.raises(psycopg.errors.RaiseException, match='snapshot_immutable'), conn.transaction():
        conn.execute("UPDATE publishing_jobs SET publication_mode=%s WHERE id=%s",('publish' if mode=='draft' else 'draft',bound['id']))
    if not recover:
        # A later policy mode must not upgrade a queued private draft or rewrite
        # an already-confirmed public Job. All records are inside lab rollback.
        conn.execute('UPDATE blogger_blogs SET test_publish_verified_at=now() WHERE id=%s',(blog,))
        changed=api.post('/admin/publications/trends-auto-policy',headers=headers,json={
            'blog_id':str(blog),'enabled':True,'allowed_geos':[geo],
            'publication_mode':'publish' if mode=='draft' else 'draft','daily_limit':None,
            'actor_label':'isolated manager','reason':'Isolated later policy mode switch',
            'idempotency_key':uuid4().hex,
            'confirmation':'ENABLE TRENDS AUTO PUBLICATION' if mode=='draft' else ''})
        assert changed.status_code==201, changed.text
        assert conn.execute('SELECT publication_mode FROM publishing_jobs WHERE id=%s',(bound['id'],)).fetchone()['publication_mode']==mode
    if recover:
        from woori import blogger_service
        ledger={'post_id':'456','blog_id':'1234567890','status':'DRAFT','post_verified':True}
        conn.execute("INSERT INTO blogger_write_operations(idempotency_key,request_fingerprint,operation,status,result) VALUES (%s,%s,'create_draft','succeeded',%s)",
            ('live:pubjob-'+str(bound['id'])+'-draft','a'*64,Jsonb(ledger)))
        conn.execute("UPDATE publishing_jobs SET status='running',lease_until=now()-interval '1 second' WHERE id=%s",(bound['id'],))
        monkeypatch.setattr(blogger_service,'post',lambda *_:{'id':'456','blog':{'id':'1234567890'},'status':'DRAFT','content':'User edited this draft'})
    class Publisher:
        def create_draft(self,*args,**kwargs):
            assert not recover, 'recovery must never POST again'
            return {'post_id':'456','http_status':200,'post_verified':True,'status':'DRAFT'}
        def publish_draft(self,*args,**kwargs):
            assert mode == 'publish', 'a later public policy must never publish an existing Draft Job'
            return {'post_id':'456','url':'https://isolated.blogspot.com/article.html','status':'LIVE',
                    'readback_verified':True,'http_status':200,'published_at':slot}
    monkeypatch.setattr(publication_worker,'BloggerLivePublisher',Publisher)
    result=publication_worker.process_next_live_job(trends_auto_only=True)
    if mode == 'draft':
        assert result['status']=='draft_saved', result
        assert conn.execute("SELECT remote_status FROM blogger_draft_receipts WHERE blog_id=%s",(blog,)).fetchone()['remote_status']=='DRAFT'
        assert conn.execute("SELECT count(*) n FROM publishing_records WHERE blog_id=%s",(blog,)).fetchone()['n']==0
        assert publication_worker.process_next_live_job(trends_auto_only=True) is None
        from woori import blogger_service, publication_monitor
        monkeypatch.setattr(publication_monitor,'connection',shared)
        monkeypatch.setattr(blogger_service,'post',lambda *_:{'id':'456','blog':{'id':'1234567890'},'status':'LIVE','url':'https://isolated.blogspot.com/edited.html','updated':slot,'published':slot,'content':'User edited content'})
        synced=api.post('/admin/publications/jobs/'+str(bound['id'])+'/sync-draft',headers=headers)
        assert synced.status_code==200 and synced.json()['remote_status']=='LIVE'
        assert synced.json()['remote_updated_at']==slot and synced.json()['remote_published_at']==slot
        assert api.post('/admin/publications/jobs/'+str(bound['id'])+'/sync-draft',headers=headers).status_code==200
        assert conn.execute("SELECT count(*) n FROM audit_events WHERE event_type='publication.trends_draft.manual_published' AND payload->>'job_id'=%s",(str(bound['id']),)).fetchone()['n']==1
        monitor=publication_monitor.snapshot('all',1,50)
        tracked=next(j for j in monitor['items'] if j['job_id']==str(bound['id']))
        assert tracked['state']=='published' and tracked['publication_mode']=='draft'
        reviewed=api.patch('/admin/publications/jobs/'+str(bound['id'])+'/draft-review',headers=headers,
            json={'review_status':'completed','review_notes':'User manually reviewed the Blogger draft.'})
        assert reviewed.status_code==200 and reviewed.json()['remote_edit_verified'] is False
        assert conn.execute("SELECT publication_mode FROM publishing_jobs WHERE id=%s",(bound['id'],)).fetchone()['publication_mode']=='draft'
        from woori.google_http import GoogleFailure
        original_body=conn.execute('SELECT body FROM content_versions WHERE id=%s',(version,)).fetchone()['body']
        for category,status in [('not_found',404),('permission_denied',403),('network',None),('free_quota_exceeded',429)]:
            calls=[]
            def unavailable(*_,_calls=calls,_category=category,_status=status):
                _calls.append(True)
                raise GoogleFailure(_category,_status)
            monkeypatch.setattr(blogger_service,'post',unavailable)
            unavailable_result=api.post('/admin/publications/jobs/'+str(bound['id'])+'/sync-draft',headers=headers)
            assert unavailable_result.status_code==200
            assert unavailable_result.json()['remote_status']==('NOT_FOUND' if status==404 else 'LOOKUP_FAILED')
            assert calls==[True]
            failed_item=next(j for j in publication_monitor.snapshot('all',1,50)['items'] if j['job_id']==str(bound['id']))
            assert failed_item['state']=='failed' and failed_item['remote_url'] is None
            assert conn.execute('SELECT body FROM content_versions WHERE id=%s',(version,)).fetchone()['body']==original_body
            assert conn.execute('SELECT remote_status FROM blogger_draft_receipts WHERE job_id=%s',(bound['id'],)).fetchone()['remote_status']=='DRAFT'
        return
    assert result['status']=='draft_created', result
    conn.execute("UPDATE publishing_jobs SET available_at=now() WHERE blog_id=%s",(blog,))
    result=publication_worker.process_next_live_job(trends_auto_only=True)
    assert result['status']=='published', result
    assert conn.execute("SELECT remote_status FROM publishing_records WHERE blog_id=%s",(blog,)).fetchone()['remote_status']=='LIVE'
    assert conn.execute("SELECT claims->0->>'verification_status' status FROM external_content_imports WHERE id=%s",(imported,)).fetchone()['status']=='unverified'
