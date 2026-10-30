from contextlib import contextmanager
from copy import deepcopy
from uuid import uuid4

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
    monkeypatch.setattr(scheduled_duplicates, "find_remote_duplicate", lambda *_: {"status": "clear"})
    assert enqueue_trends_auto_jobs() == {"created": 1, "held": 0}
    assert enqueue_trends_auto_jobs() == {"created": 0, "held": 0}
    assert fake.claims[0]["verification_status"] == "unverified"


def test_isolated_import_enqueue_worker_and_live_receipt(lab, monkeypatch):
    conn, api, headers = lab
    @contextmanager
    def shared():
        with conn.transaction():
            yield conn
    for module in (content_imports, publications, publication_worker, trends_publication):
        monkeypatch.setattr(module, "connection", shared)
    monkeypatch.setattr(external_policy, "_blogger_policy_approval", lambda: {"approved": True})
    monkeypatch.setattr(external_policy, "_blogger_operation_is_approved", lambda _: True)
    monkeypatch.setattr(scheduled_duplicates, "find_remote_duplicate", lambda *_: {"status": "clear"})
    monkeypatch.setattr(publication_worker, "find_remote_duplicate", lambda *_: {"status": "clear"})
    payload = item()
    payload['claims'] = [{"claim_id": "general", "claim": "Readers can compare organizational approaches.",
        "source_ids": [], "evidence_excerpt": "", "verification_status": "unverified", "factual_state": "unverified"}]
    response = api.post('/admin/research/content-imports', headers=headers, json={'submitted_by': 'isolated', 'item': payload})
    assert response.status_code == 201, response.text
    imported, version = response.json()['import_id'], response.json()['content_version_id']
    oauth = conn.execute("INSERT INTO google_connections(label,status,scopes) VALUES ('isolated','connected',%s) RETURNING id",
        (['https://www.googleapis.com/auth/blogger'],)).fetchone()['id']
    blog = conn.execute("""INSERT INTO blogger_blogs(language_code,url,display_name,blog_id,oauth_connection_id,
        connection_verified_at,test_publish_verified_at) VALUES ('en',%s,'isolated','1234567890',%s,now(),now()) RETURNING id""",
        ('https://isolated-'+uuid4().hex+'.blogspot.com', oauth)).fetchone()['id']
    profile = conn.execute("INSERT INTO language_profiles(language_code,target_country) VALUES ('en','US') ON CONFLICT(language_code,target_country) DO UPDATE SET search_intent=language_profiles.search_intent RETURNING id").fetchone()['id']
    conn.execute("INSERT INTO publishing_policies(language_code,blog_id,profile_id) VALUES ('en',%s,%s)", (blog,profile))
    conn.execute("UPDATE trend_blog_geo_authoring SET enabled=false WHERE geo='US'")
    conn.execute("INSERT INTO trend_blog_geo_authoring(blog_id,geo,enabled,processing_order) VALUES (%s,'US',true,1)",(blog,))
    conn.execute("INSERT INTO trends_publication_policy_events(blog_id,enabled,allowed_geos,daily_limit,actor_label,reason,idempotency_key,created_at) VALUES (%s,true,ARRAY['US'],NULL,'isolated','isolated scope approval',%s,now()-interval '1 minute')",(blog,uuid4().hex))
    topic=uuid4()
    conn.execute("INSERT INTO trend_topics(id,normalized_key,representative_geo,representative_query,grouping_method,grouping_confidence,grouping_status) VALUES (%s,%s,'US','organization','single_observation',1,'exact_query_cluster_not_event_confirmed')",(topic,uuid4().hex))
    job=conn.execute("""INSERT INTO codex_authoring_jobs(request_key,request_sha256,job_type,blog_id,language_code,target_country,
        category,keyword,options,state,model,import_id,content_version_id) VALUES (%s,%s,'google_trends',%s,'en','US',
        'technology','organization','{}','imported_review','isolated',%s,%s) RETURNING id""",(uuid4(),'a'*64,blog,imported,version)).fetchone()['id']
    slot=conn.execute('SELECT now() stamp').fetchone()['stamp'].isoformat()
    contract={'target_blog_id':str(blog),'target_language':'en','target_country':'US','source_country':'US','collection_slot':slot}
    conn.execute("INSERT INTO trend_generation_requests(topic_id,duplicate_key,contract,state,authoring_job_id) VALUES (%s,%s,%s,'imported',%s)",(topic,uuid4().hex,Jsonb(contract),job))
    conn.execute("UPDATE publication_mode_settings SET emergency_stopped=false WHERE scope_type='global' AND scope_key=''")
    assert enqueue_trends_auto_jobs()['created']==1
    assert enqueue_trends_auto_jobs()['created']==0
    class Publisher:
        def create_draft(self,*args,**kwargs):
            return {'post_id':'456','http_status':200,'post_verified':True}
        def publish_draft(self,*args,**kwargs):
            return {'post_id':'456','url':'https://isolated.blogspot.com/article.html','status':'LIVE',
                    'readback_verified':True,'http_status':200,'published_at':slot}
    monkeypatch.setattr(publication_worker,'BloggerLivePublisher',Publisher)
    result=publication_worker.process_next_live_job(trends_auto_only=True)
    assert result['status']=='draft_created', result
    conn.execute("UPDATE publishing_jobs SET available_at=now() WHERE blog_id=%s",(blog,))
    result=publication_worker.process_next_live_job(trends_auto_only=True)
    assert result['status']=='published', result
    assert conn.execute("SELECT remote_status FROM publishing_records WHERE blog_id=%s",(blog,)).fetchone()['remote_status']=='LIVE'
    assert conn.execute("SELECT claims->0->>'verification_status' status FROM external_content_imports WHERE id=%s",(imported,)).fetchone()['status']=='unverified'
