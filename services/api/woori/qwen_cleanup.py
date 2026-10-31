"""P098 owner-only maintenance plan. No application API or automatic execution."""
from __future__ import annotations

import hashlib
import json
from typing import Any, cast

from psycopg import sql
from psycopg.types.json import Jsonb

MODELS = ('Qwen3-4B-Q4_K_M.gguf', 'Qwen3-1.7B-Q8_0.gguf')
KEYS = {
    'research_experiment_evaluations': ('id',), 'seo_audits': ('id',),
    'model_failure_artifacts': ('id',), 'article_quality_evaluations': ('id',),
    'generation_stage_runs': ('id',), 'generation_attempts': ('id',),
    'generation_results': ('id',), 'generation_targets': ('run_id', 'profile_id'),
    'generation_jobs': ('run_id',), 'content_versions': ('id',),
}


def plan(conn: Any) -> dict[str, Any]:
    origins = conn.execute("""WITH RECURSIVE roots AS (
        SELECT content_version_id id FROM generation_results WHERE provider='local' AND model=ANY(%s)
        UNION SELECT content_version_id FROM article_quality_evaluations
        WHERE model=ANY(%s) AND ai_calls>0 AND prompt_version='p3.8-c1-full-article-v1'
          AND metrics->>'engine' LIKE 'llama.cpp%%' AND content_version_id IS NOT NULL
    ), descendants AS (SELECT id FROM roots UNION SELECT v.id FROM content_versions v
        JOIN descendants d ON v.source_version_id=d.id)
    SELECT v.id,v.group_id,v.source_version_id FROM descendants d JOIN content_versions v ON v.id=d.id
    ORDER BY v.id""", (list(MODELS), list(MODELS))).fetchall()
    candidates = [r['id'] for r in origins]
    protected: set[Any] = set()
    # Human approvals and every real remote/job/import identity take precedence.
    for table, column in [('external_content_import_content_links','content_version_id'),
        ('codex_authoring_jobs','content_version_id'), ('publishing_records','content_version_id'),
        ('blogger_draft_receipts','content_version_id'), ('publication_approval_events','content_version_id'),
        ('manual_publication_approval_events','content_version_id'), ('scheduled_first_publication_events','content_version_id'),
        ('post_publication_reviews','content_version_id'), ('article_human_reviews','content_version_id'),
        ('article_editorial_versions','base_content_version_id'), ('article_review_events','content_version_id'),
        ('localized_publication_requests','source_content_version_id'),
        ('localized_publication_requests','existing_target_content_version_id')]:
        rows = conn.execute(sql.SQL('SELECT {} AS id FROM {} WHERE {}=ANY(%s)').format(
            sql.Identifier(column),sql.Identifier(table),sql.Identifier(column)), (candidates,)).fetchall()
        protected.update(r['id'] for r in rows)
    # Publishing Jobs are preserved even if they failed or were only simulations.
    protected.update(r['content_version_id'] for r in conn.execute(
        'SELECT content_version_id FROM publishing_jobs WHERE content_version_id=ANY(%s)', (candidates,)).fetchall())
    protected.update(r['source_version_id'] for r in conn.execute(
        'SELECT source_version_id FROM content_versions WHERE source_version_id=ANY(%s) AND NOT(id=ANY(%s))',
        (candidates,candidates)).fetchall())
    # Preserve an entire lineage when one member is protected.
    protected_groups = {r['group_id'] for r in origins if r['id'] in protected}
    ids = [r['id'] for r in origins if r['group_id'] not in protected_groups]
    # Only original Qwen generation attempts or their explicit deterministic rechecks.
    evaluations = conn.execute("""WITH RECURSIVE q AS (
        SELECT id,content_version_id,batch_id FROM article_quality_evaluations
        WHERE model=ANY(%s) AND ai_calls>0 AND prompt_version='p3.8-c1-full-article-v1'
        AND (metrics->>'engine' LIKE 'llama.cpp%%' OR (content_version_id IS NULL
          AND metrics->>'model'=model AND error_category IN ('invalid_local_model_response','local_model_response_invalid_type','local_model_output_schema_invalid')))
        UNION SELECT e.id,e.content_version_id,e.batch_id FROM article_quality_evaluations e JOIN q
        ON e.metrics->>'source_evaluation_id'=q.id::text WHERE e.ai_calls=0 AND e.model=ANY(%s))
        SELECT * FROM q ORDER BY id""", (list(MODELS),list(MODELS))).fetchall()
    eval_ids = [r['id'] for r in evaluations if r['content_version_id'] is None or r['content_version_id'] in ids]
    batches = [r['batch_id'] for r in evaluations if r['id'] in eval_ids]
    runs = [r['run_id'] for r in conn.execute("""SELECT DISTINCT g.run_id FROM generation_results g
        WHERE g.content_version_id=ANY(%s) AND g.provider='local' AND g.model=ANY(%s)
        AND NOT EXISTS(SELECT 1 FROM generation_results other WHERE other.run_id=g.run_id
            AND (other.provider<>'local' OR NOT(other.model=ANY(%s)) OR NOT(other.content_version_id=ANY(%s))))
        AND NOT EXISTS(SELECT 1 FROM generation_stage_runs s WHERE s.run_id=g.run_id
            AND s.model IS NOT NULL AND NOT(s.model=ANY(%s)))""",
        (ids,list(MODELS),list(MODELS),ids,list(MODELS))).fetchall()]
    selectors = {
        'content_versions': ('id=ANY(%s)', [ids]),
        'article_quality_evaluations': ('id=ANY(%s)', [eval_ids]),
        'model_failure_artifacts': ('batch_id=ANY(%s) AND model=ANY(%s)', [batches,list(MODELS)]),
        'generation_results': ('content_version_id=ANY(%s)', [ids]),
        'research_experiment_evaluations': ('content_version_id=ANY(%s)', [ids]),
        'seo_audits': ('content_version_id=ANY(%s)', [ids]),
    }
    for table in ('generation_jobs','generation_targets','generation_attempts','generation_stage_runs'):
        selectors[table] = ('run_id=ANY(%s)', [runs])
    tables = {}
    for table, keys in KEYS.items():
        where, args = selectors[table]
        fields = sql.SQL(',').join(map(sql.Identifier, keys))
        tables[table] = [dict(row) for row in conn.execute(sql.SQL('SELECT {} FROM {} WHERE {} ORDER BY {}').format(
            fields,sql.Identifier(table),sql.SQL(where),fields), args).fetchall()]
    return cast(dict[str, Any], json.loads(json.dumps({'task':'P5-CODEX-098','models':MODELS,'tables':tables,
        'manuscripts':len({r['group_id'] for r in origins if r['id'] in ids}),
        'protected_collisions':sorted(map(str,protected)), 'source_tables_deleted':False}, default=str)))


def digest(manifest: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(manifest,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def apply(conn: Any, manifest: dict[str, Any]) -> dict[str,int]:
    """Caller supplies an owner transaction; any mismatch raises and rolls it back."""
    for table in sorted(KEYS):
        conn.execute(sql.SQL('LOCK TABLE {} IN EXCLUSIVE MODE').format(sql.Identifier(table)))
    if plan(conn) != manifest:
        raise ValueError('cleanup_manifest_changed_rollback')
    ids = [r['id'] for r in manifest['tables']['content_versions']]
    protected_versions = conn.execute('SELECT id FROM content_versions WHERE NOT(id=ANY(%s::uuid[])) ORDER BY id', (ids,)).fetchall()
    protected_tables = ('audit_events','external_content_imports','external_content_import_content_links',
        'codex_authoring_jobs','publishing_jobs','publishing_records','blogger_draft_receipts',
        'manual_publication_approval_events','publication_approval_events','research_sources','collection_sources','trend_research_packages')
    before = {table:conn.execute(sql.SQL('SELECT count(*) n FROM {}').format(sql.Identifier(table))).fetchone()['n'] for table in protected_tables}
    # Disable only mutation-denial triggers, transactionally. FK and audit triggers stay enabled.
    disabled = conn.execute("""SELECT c.relname,t.tgname FROM pg_trigger t
        JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_proc p ON p.oid=t.tgfoid
        WHERE NOT t.tgisinternal AND c.relname=ANY(%s) AND p.proname='deny_mutation'""",
        (list(KEYS),)).fetchall()
    for row in disabled:
        conn.execute(sql.SQL('ALTER TABLE {} DISABLE TRIGGER {}').format(sql.Identifier(row['relname']),sql.Identifier(row['tgname'])))
    deleted = {}
    # Child versions first for both source-version foreign keys.
    version_order = conn.execute("""WITH RECURSIVE d AS (
        SELECT id,source_version_id,0 depth FROM content_versions WHERE id=ANY(%s)
        UNION ALL SELECT v.id,v.source_version_id,d.depth+1 FROM content_versions v
        JOIN d ON v.source_version_id=d.id WHERE v.id=ANY(%s))
        SELECT id,max(depth) depth FROM d GROUP BY id ORDER BY max(depth) DESC,id""",
        ([r['id'] for r in manifest['tables']['content_versions']],)*2).fetchall()
    for table, keys in KEYS.items():
        rows = manifest['tables'][table]
        if table == 'content_versions':
            rows = [{'id':str(r['id'])} for r in version_order]
        count = 0
        for row in rows:
            query = sql.SQL('DELETE FROM {} WHERE {}').format(sql.Identifier(table),
                sql.SQL(' AND ').join(sql.SQL('{}=%s').format(sql.Identifier(k)) for k in keys))
            count += conn.execute(query, [row[k] for k in keys]).rowcount
        if count != len(rows):
            raise ValueError('cleanup_count_mismatch_rollback')
        deleted[table] = count
    for row in disabled:
        conn.execute(sql.SQL('ALTER TABLE {} ENABLE TRIGGER {}').format(sql.Identifier(row['relname']),sql.Identifier(row['tgname'])))
    if conn.execute('SELECT id FROM content_versions ORDER BY id').fetchall() != protected_versions:
        raise ValueError('protected_versions_changed_rollback')
    for table, count in before.items():
        if conn.execute(sql.SQL('SELECT count(*) n FROM {}').format(sql.Identifier(table))).fetchone()['n'] < count:
            raise ValueError('protected_table_count_changed_rollback')
    conn.execute("INSERT INTO audit_events(event_type,payload) VALUES ('maintenance.qwen_articles.hard_deleted',%s)",
        (Jsonb({'task':'P5-CODEX-098','manifest_sha256':digest(manifest),'deleted':deleted,
                'manifest':manifest,'sources_preserved':True,'operational_approvals_preserved':True}),))
    return deleted
