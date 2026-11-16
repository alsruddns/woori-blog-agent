import hashlib
from contextlib import contextmanager
from uuid import uuid4

import pytest
from test_qwen_cleanup import owner as isolated_owner
from test_qwen_cleanup import seed
from woori import publications
from woori.publication_read_state import failure_resolved_clause

owner = isolated_owner


@pytest.mark.parametrize(('case','unresolved'),[
    ('replacement_live',False),('other_blog',True),('other_import',True),
    ('older_version',True),('not_verified',True),('draft',True)])
def test_failure_resolution_requires_exact_lineage_target_and_live(owner,case,unresolved,monkeypatch):
    first=seed(owner,generated=False)
    group=owner.execute('SELECT group_id FROM content_versions WHERE id=%s',(first,)).fetchone()['group_id']
    second=uuid4()
    owner.execute("INSERT INTO content_versions(id,group_id,language,version,title,body) VALUES (%s,%s,'ko',2,'Current exact manuscript title','Revised isolated body')",(second,group))
    import_id, import_version = uuid4(),uuid4()
    digest=hashlib.sha256(str(import_id).encode()).hexdigest()
    owner.execute("""INSERT INTO external_content_imports(id,external_content_id,event_group_id,relation,
        source_region,language_code,target_audiences,category,title,body_markdown,source_ids,sources,claims,
        fact_checked_at,seo_metadata,blogger_labels,generation_method,generated_at,submitted_by,content_sha256,idempotency_key)
        VALUES (%s,%s,%s,'original','KR','ko','[]','finance','Old exact manuscript title','Old isolated body','[]','[]','[]',
        now(),'{}','[]','manual_codex_import',now(),'isolated',%s,%s)""",(import_id,str(import_id),str(import_id),digest,digest))
    owner.execute("""INSERT INTO external_content_import_versions(id,import_id,version_number,title,body_markdown,
        seo_metadata,blogger_labels,content_sha256,author_label,change_reason)
        VALUES (%s,%s,1,'Old exact manuscript title','Old isolated body','{}','[]',%s,'isolated','test history')""",(import_version,import_id,digest))
    owner.execute('INSERT INTO external_content_import_content_links(import_id,import_version_id,content_version_id) VALUES (%s,%s,%s)',(import_id,import_version,first))
    replacement_import=uuid4() if case=='other_import' else import_id
    # An unlinked replacement cannot resolve the failed import.
    if replacement_import==import_id:
        next_import_version=uuid4()
        owner.execute("""INSERT INTO external_content_import_versions(id,import_id,version_number,title,body_markdown,
            seo_metadata,blogger_labels,content_sha256,author_label,change_reason)
            VALUES (%s,%s,2,'Current exact manuscript title','Revised isolated body','{}','[]',%s,'isolated','test revision')""",(next_import_version,import_id,'a'*64))
        owner.execute('INSERT INTO external_content_import_content_links(import_id,import_version_id,content_version_id) VALUES (%s,%s,%s)',(import_id,next_import_version,second))
    blog=owner.execute("SELECT id FROM blogger_blogs WHERE language_code='ko' LIMIT 1").fetchone()['id']
    other=owner.execute("INSERT INTO blogger_blogs(language_code,url,display_name) VALUES ('ko',%s,'Isolated other target') RETURNING id",("https://isolated-"+uuid4().hex+".blogspot.com",)).fetchone()['id']
    target=other if case=='other_blog' else blog
    profile=owner.execute("SELECT id FROM language_profiles WHERE language_code=(SELECT language_code FROM blogger_blogs WHERE id=%s) AND target_country=''",(target,)).fetchone()['id']
    policy=owner.execute("INSERT INTO publishing_policies(language_code,blog_id,profile_id,active) SELECT language_code,id,%s,false FROM blogger_blogs WHERE id=%s ON CONFLICT(blog_id,profile_id) DO UPDATE SET active=publishing_policies.active RETURNING id",(profile,target)).fetchone()['id']
    posted=first if case=='older_version' else second
    job=owner.execute("INSERT INTO publishing_jobs(policy_id,blog_id,content_version_id,idempotency_key,scheduled_at) VALUES (%s,%s,%s,%s,now()) RETURNING id",(policy,target,posted,str(uuid4()))).fetchone()['id']
    owner.execute("""INSERT INTO publishing_records(job_id,blog_id,content_version_id,remote_post_id,published_at,remote_url,remote_status,remote_verified_at)
        VALUES (%s,%s,%s,'123456',now(),'https://isolated.blogspot.com/example',%s,CASE WHEN %s THEN NULL ELSE now() END)""",
        (job,target,posted,'DRAFT' if case=='draft' else 'LIVE',case=='not_verified'))
    failed=second if case=='older_version' else first
    clause=failure_resolved_clause('v','b.id','i.id')
    found=owner.execute(f"SELECT 1 FROM content_versions v CROSS JOIN blogger_blogs b CROSS JOIN external_content_imports i WHERE v.id=%s AND b.id=%s AND i.id=%s AND {clause}",(failed,blog,import_id)).fetchone()
    assert bool(found)==unresolved
    if case=='replacement_live':
        @contextmanager
        def shared():
            with owner.transaction():
                yield owner
        monkeypatch.setattr(publications,'connection',shared)
        result=publications.list_publications(view='published',q='Current exact manuscript',language_code='ko',blog_id=str(blog),page=99,page_size=1)
        assert result['summary']['published']==result['total_count']==1
        assert result['page']==1
        assert result['items'][0]['title']=='Current exact manuscript title'
        assert result['items'][0]['content_version_id']==str(second)
        owner.execute("UPDATE publishing_jobs SET status='failed',publication_state='publication_failed' WHERE id=%s",(job,))
        held=publications.list_publications(view='held',q='',language_code='',blog_id='',page=1,page_size=100)
        assert not any(item['id']==str(job) for item in held['items'])
