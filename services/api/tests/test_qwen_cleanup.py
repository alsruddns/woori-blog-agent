from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from dotenv import dotenv_values
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from woori.qwen_cleanup import apply, plan


@pytest.fixture
def owner():
    values = dotenv_values(Path(__file__).resolve().parents[3] / '.env.test')
    with psycopg.connect(str(values['MIGRATION_DATABASE_URL']),row_factory=dict_row) as conn:
        assert conn.info.dbname == 'woori_blog_agent_test'
        assert conn.info.user == 'woori_test_owner'
        before = conn.execute('SELECT count(*) n FROM content_versions').fetchone()['n']
        with conn.transaction(force_rollback=True):
            yield conn
        assert conn.execute('SELECT count(*) n FROM content_versions').fetchone()['n'] == before


def seed(conn, *, generated=True):
    group, version = uuid4(), uuid4()
    conn.execute('INSERT INTO content_groups(id) VALUES (%s)',(group,))
    conn.execute("INSERT INTO content_versions(id,group_id,language,version,title,body) VALUES (%s,%s,'ko',1,'Synthetic Qwen comparison article','Synthetic test content only')",(version,group))
    conn.execute("""INSERT INTO article_quality_evaluations(batch_id,topic_key,topic,language_code,
        content_version_id,model,prompt_version,source_ids,fact_ids,metrics,checks,machine_passed,status,elapsed_ms,ai_calls)
        VALUES (%s,'isolated','isolated','ko',%s,'Qwen3-4B-Q4_K_M.gguf',%s,%s,%s,%s,'{}',false,'quality_held',1,%s)""",
        (uuid4(),version,'p3.8-c1-full-article-v1' if generated else 'deterministic-comparison-only',
         [uuid4()],[uuid4()],Jsonb({'engine':'llama.cpp test-only'}),1 if generated else 0))
    return version


def test_hard_delete_exact_provenance_not_comparison_and_keeps_audit(owner):
    removed, comparison = seed(owner), seed(owner,generated=False)
    audit = owner.execute('SELECT count(*) n FROM audit_events').fetchone()['n']
    manifest = plan(owner)
    assert str(removed) in [r['id'] for r in manifest['tables']['content_versions']]
    assert str(comparison) not in [r['id'] for r in manifest['tables']['content_versions']]
    deleted = apply(owner,manifest)
    assert deleted['content_versions'] == 1
    assert deleted['article_quality_evaluations'] == 1
    assert not owner.execute('SELECT 1 FROM content_versions WHERE id=%s',(removed,)).fetchone()
    assert owner.execute('SELECT 1 FROM content_versions WHERE id=%s',(comparison,)).fetchone()
    assert owner.execute('SELECT count(*) n FROM audit_events').fetchone()['n'] == audit+1
    assert not owner.execute("SELECT 1 FROM pg_trigger WHERE tgname='content_immutable' AND tgenabled='D'").fetchone()


def test_manifest_mismatch_rolls_back_without_disabling_guards(owner):
    seed(owner)
    manifest = plan(owner)
    manifest['tables']['content_versions'] = []
    with pytest.raises(ValueError,match='manifest_changed'):
        apply(owner,manifest)
    assert not owner.execute("SELECT 1 FROM pg_trigger WHERE tgname='content_immutable' AND tgenabled='D'").fetchone()


def test_any_publication_job_protects_qwen_identity(owner):
    version = seed(owner)
    blog = owner.execute("SELECT id FROM blogger_blogs WHERE language_code='ko' LIMIT 1").fetchone()['id']
    profile = owner.execute("SELECT id FROM language_profiles WHERE language_code='ko' AND target_country='' LIMIT 1").fetchone()['id']
    policy = owner.execute("""INSERT INTO publishing_policies(language_code,blog_id,profile_id,active)
        VALUES ('ko',%s,%s,false) ON CONFLICT(blog_id,profile_id) DO UPDATE SET active=publishing_policies.active RETURNING id""",(blog,profile)).fetchone()['id']
    owner.execute("""INSERT INTO publishing_jobs(policy_id,blog_id,content_version_id,idempotency_key,scheduled_at)
        VALUES (%s,%s,%s,%s,now())""",(policy,blog,version,str(uuid4())))
    manifest = plan(owner)
    assert str(version) in manifest['protected_collisions']
    assert str(version) not in [row['id'] for row in manifest['tables']['content_versions']]
