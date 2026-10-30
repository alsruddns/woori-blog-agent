import json
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from test_content_imports import valid_item
from test_pipeline import lab as shared_lab
from woori import codex_runner, content_imports, external_policy, keyword_jobs
from woori.content_imports import ImportSubmission

lab=shared_lab


def setup_job(lab,monkeypatch):
    conn,api,headers=lab
    @contextmanager
    def shared():
        with conn.transaction():yield conn
    monkeypatch.setattr(keyword_jobs,'connection',shared)
    monkeypatch.setattr(content_imports,'connection',shared)
    profile=conn.execute("INSERT INTO language_profiles(language_code,target_country) VALUES('ko','KR') ON CONFLICT(language_code,target_country) DO UPDATE SET search_intent=language_profiles.search_intent RETURNING id").fetchone()['id']
    blog=conn.execute("INSERT INTO blogger_blogs(language_code,url,display_name,blog_id) VALUES('ko',%s,'Isolated keyword target','9876543210012345') RETURNING id",('https://keyword-'+uuid4().hex[:10]+'.blogspot.com',)).fetchone()['id']
    conn.execute("INSERT INTO publishing_policies(language_code,blog_id,profile_id,active) VALUES('ko',%s,%s,false)",(blog,profile))
    payload={'request_key':str(uuid4()),'blog_id':str(blog),'keyword':'격리 테스트 원고','category':'technology'}
    return conn,api,headers,payload


def test_idempotency_country_validation_cancel_and_retry(lab,monkeypatch):
    _conn,api,headers,payload=setup_job(lab,monkeypatch)
    assert api.post('/admin/keyword-authoring',json=payload).status_code==401
    first=api.post('/admin/keyword-authoring',headers=headers,json=payload)
    assert first.status_code==201,first.text
    again=api.post('/admin/keyword-authoring',headers=headers,json=payload)
    assert again.json()['id']==first.json()['id']
    changed={**payload,'keyword':'다른 원고'}
    assert api.post('/admin/keyword-authoring',headers=headers,json=changed).status_code==409
    assert api.post('/admin/keyword-authoring',headers=headers,json={**payload,'category':'unknown'}).status_code==422
    assert api.post('/admin/keyword-authoring',headers=headers,json={**payload,'research_range':'custom'}).status_code==422
    assert api.post('/admin/keyword-authoring',headers=headers,json={**payload,'request_key':str(uuid4()),'blog_id':str(uuid4())}).status_code==409
    job=first.json()['id']
    assert api.post(f'/admin/keyword-authoring/{job}/cancel',headers=headers).status_code==200
    retry={'request_key':str(uuid4())}
    child=api.post(f'/admin/keyword-authoring/{job}/retry',headers=headers,json=retry)
    assert child.status_code==201,child.text
    assert child.json()['parent_job_id']==job
    assert api.post(f'/admin/keyword-authoring/{job}/retry',headers=headers,json=retry).json()['id']==child.json()['id']
    assert api.post(f'/admin/keyword-authoring/{job}/retry',headers=headers,json={'request_key':str(uuid4())}).status_code==409


def test_manual_ready_import_and_no_publication_job(lab,monkeypatch,tmp_path):
    conn,api,headers,payload=setup_job(lab,monkeypatch)
    monkeypatch.setattr(keyword_jobs,'ROOT',tmp_path/'project')
    monkeypatch.setattr(keyword_jobs,'INBOX',tmp_path/'project/.local/keyword-import')
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path/'local'))
    response=api.post('/admin/keyword-authoring',headers=headers,json=payload)
    job=conn.execute('SELECT * FROM codex_authoring_jobs WHERE id=%s',(response.json()['id'],)).fetchone()
    item=valid_item()
    article={k:item[k] for k in ('title','body_markdown','sources','claims','seo')}
    article['source_region']='ZZ'
    evidence={'opened_urls':{'https://example.gov/policy':datetime.now(UTC).isoformat()},'web_search_count':1,'execution_id':str(uuid4())}
    def fixture_execute(work,prompt,schema,callback,cancelled):
        assert 'untrusted editorial input' in prompt
        callback('researching',{'execution_id':evidence['execution_id']})
        callback('writing',{})
        return article,evidence
    monkeypatch.setattr(codex_runner,'execute',fixture_execute)
    before=conn.execute('SELECT count(*) n FROM publishing_jobs').fetchone()['n']
    keyword_jobs.generate(dict(job))
    current=conn.execute('SELECT * FROM codex_authoring_jobs WHERE id=%s',(job['id'],)).fetchone()
    assert current['state']=='import_pending'
    ready=keyword_jobs.ROOT/current['result_path']
    envelope=ImportSubmission.model_validate_json(ready.read_bytes())
    assert envelope.item.generation_method=='manual_codex_import'
    assert envelope.item.claims[0].verification_status=='unverified'
    assert envelope.item.source_region=='ZZ' and envelope.item.language_code=='ko'
    def transport(request):
        result=api.request(request.method,request.url.path,headers=dict(request.headers),content=request.content)
        return httpx.Response(result.status_code,content=result.content)
    keyword_jobs.import_pending(transport=httpx.MockTransport(transport),api_url='http://127.0.0.1:18100')
    imported=conn.execute('SELECT * FROM codex_authoring_jobs WHERE id=%s',(job['id'],)).fetchone()
    assert imported['state']=='imported_review',imported['error_code']
    assert imported['import_id'] and imported['content_version_id']
    assert conn.execute('SELECT count(*) n FROM publishing_jobs').fetchone()['n']==before
    assert conn.execute('SELECT count(*) n FROM manual_publication_approval_events WHERE content_version_id=%s',(imported['content_version_id'],)).fetchone()['n']==0
    assert api.post(f"/admin/keyword-authoring/{job['id']}/retry",headers=headers,json={'request_key':str(uuid4())}).json()['id']==str(job['id'])


def test_no_unopened_sources_or_scheduled_provenance():
    item=valid_item()
    with pytest.raises(codex_runner.CodexFailure,match='source_not_opened'):
        keyword_jobs.make_envelope({'id':uuid4(),'category':'technology','language_code':'ko','target_country':'KR','model':'gpt-6-luna'},
            {**{k:item[k] for k in ('title','body_markdown','sources','claims','seo')},'source_region':'ZZ'},{'opened_urls':{}})


def test_process_cost_and_permission_boundaries(monkeypatch):
    monkeypatch.setattr(external_policy,'billing_credential_names',list)
    external_policy.authorize_codex_chatgpt_process('Logged in using ChatGPT')
    with pytest.raises(external_policy.ExternalCallBlocked):external_policy.authorize_codex_chatgpt_process('Logged in using API key')
    monkeypatch.setattr(external_policy,'billing_credential_names',lambda:['OPENAI_API_KEY'])
    with pytest.raises(external_policy.ExternalCallBlocked):external_policy.authorize_codex_chatgpt_process('Logged in using ChatGPT')
    monkeypatch.setenv('OPENAI_API_KEY','test-secret');monkeypatch.setenv('DATABASE_URL','test-secret')
    assert 'OPENAI_API_KEY' not in codex_runner.clean_environment() and 'DATABASE_URL' not in codex_runner.clean_environment()
    assert 'features.shell_tool=false' in codex_runner.CONFIG and 'features.view_image=false' in codex_runner.CONFIG
    assert 'features.image_generation=false' in codex_runner.CONFIG


def test_source_date_precision_and_unopened_blocks_are_preserved_as_evidence():
    item=valid_item()
    article={**{k:item[k] for k in ('title','body_markdown','sources','claims','seo')},'source_region':'ZZ'}
    article['sources'][0]['published_at']='2026-10-28'
    missing={**article['sources'][0],'source_id':'unopened','url':'https://example.gov/not-opened'}
    article['sources'].append(missing)
    original=article['body_markdown']
    article['body_markdown']+='\n\nUnsupported standalone paragraph. [source:unopened]'
    proof={'opened_urls':{'https://example.gov/policy':datetime.now(UTC).isoformat()}}
    envelope=keyword_jobs.make_envelope({'id':uuid4(),'category':'technology','language_code':'ko','target_country':'KR','model':'gpt-6-luna'},article,proof)
    assert envelope.item.body_markdown==original.strip()
    assert envelope.item.sources[0].published_at is None
    assert article['sources'][0]['published_at']=='2026-10-28'
    assert proof['source_date_metadata'][0]['precision']=='day'
    assert proof['draft_curation']['semantic_approval'] is False
    assert envelope.item.claims[0].verification_status=='unverified'


@pytest.mark.parametrize('mode',['success','cancel','timeout','limit'])
def test_runner_bounded_execution_no_shell_or_api_key(monkeypatch,tmp_path,mode):
    import io
    from pathlib import Path
    monkeypatch.setattr(codex_runner,'engine_status',lambda:{'available':True})
    monkeypatch.setattr(codex_runner,'executable',lambda:Path('test-only-codex'))
    events=[{'type':'thread.started','thread_id':'test-thread'},
            {'type':'item.completed','item':{'type':'web_search','results':[{'ref_id':'turn0view0','url':'https://example.gov/report','snippet':'Total lines: 10'}]}}]
    if mode=='limit':events=[{'type':'turn.failed','error':{'message':'usage limit reached'}}]
    class Proc:
        pid=123
        def __init__(self,args,**kwargs):
            self.stdin=io.StringIO();self.stdout=io.StringIO('\n'.join(json.dumps(e) for e in events)+'\n');self.done=False
            assert '--ignore-user-config' in args and '--sandbox' in args
            assert args[args.index('--sandbox')+1]=='read-only'
            assert '--dangerously-bypass-approvals-and-sandbox' not in args
            assert kwargs.get('shell') is not True
            if mode=='success':(tmp_path/'work/article.json').write_text('{"test":true}',encoding='utf-8')
        def poll(self):return 0 if self.done else None
        def wait(self,timeout):self.done=True;return 1 if mode=='limit' else 0
        def terminate(self):self.done=True
    closed=[]
    class Boundary:
        def __init__(self,proc):pass
        def close(self):closed.append(True)
    monkeypatch.setattr(codex_runner.subprocess,'Popen',Proc)
    monkeypatch.setattr(codex_runner,'ProcessBoundary',Boundary)
    if mode=='success':
        data,evidence=codex_runner.execute(tmp_path/'work','untrusted task',{},lambda *_:None,lambda:False)
        assert data['test'] and evidence['execution_id']=='test-thread'
    else:
        expected={'cancel':'cancelled','timeout':'codex_timeout','limit':'codex_usage_limit'}[mode]
        with pytest.raises(codex_runner.CodexFailure,match=expected):
            codex_runner.execute(tmp_path/'work','untrusted task',{},lambda *_:None,lambda:mode=='cancel',timeout=0 if mode=='timeout' else 10)
    assert closed or mode=='cancel'


def test_windows_process_boundary_terminates_only_owned_child():
    import os
    import subprocess
    import sys
    if os.name!='nt':pytest.skip('Windows process containment test')
    proc=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],creationflags=subprocess.CREATE_NO_WINDOW)
    boundary=codex_runner.ProcessBoundary(proc)
    boundary.close()
    proc.wait(timeout=5)
    assert proc.poll() is not None
