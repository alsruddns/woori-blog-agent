"""P107 discard and restore are isolated from operational manuscripts."""

from contextlib import contextmanager
from uuid import uuid4

from test_qwen_cleanup import owner as isolated_owner
from woori import publication_discards, publications

owner = isolated_owner


def _manuscript(conn):
    group, version = uuid4(), uuid4()
    conn.execute("INSERT INTO content_groups(id) VALUES (%s)", (group,))
    conn.execute(
        """INSERT INTO content_versions(id,group_id,language,version,title,body)
        VALUES (%s,%s,'ko',1,'P107 isolated manuscript','Isolated body for discard test')""",
        (version, group),
    )
    blog = conn.execute("SELECT id FROM blogger_blogs WHERE language_code='ko' LIMIT 1").fetchone()["id"]
    return version, blog


def _connection(conn):
    @contextmanager
    def shared():
        with conn.transaction():
            yield conn
    return shared


def test_discard_restore_preserves_versions_jobs_and_audit(owner, monkeypatch):
    version, blog = _manuscript(owner)
    monkeypatch.setattr(publications, "connection", _connection(owner))
    target = publications.DiscardTarget(content_version_id=version, blog_id=blog, previous_view="review")
    profile = owner.execute("SELECT id FROM language_profiles WHERE language_code='ko' AND target_country='' LIMIT 1").fetchone()["id"]
    policy = owner.execute("""INSERT INTO publishing_policies(language_code,blog_id,profile_id,active)
        VALUES ('ko',%s,%s,false) ON CONFLICT(blog_id,profile_id) DO UPDATE SET active=publishing_policies.active RETURNING id""", (blog, profile)).fetchone()["id"]
    job = owner.execute("""INSERT INTO publishing_jobs(policy_id,blog_id,content_version_id,idempotency_key,scheduled_at,status)
        VALUES (%s,%s,%s,%s,now(),'queued') RETURNING id""", (policy, blog, version, str(uuid4()))).fetchone()["id"]
    before = owner.execute("SELECT count(*) n FROM audit_events").fetchone()["n"]
    result = publications.discard_manuscripts(publications.DiscardRequest(
        targets=[target], actor="Test operator", reason="Isolated discard reason",
    ))
    assert (result["success_count"], result["failure_count"]) == (1, 0)
    assert publication_discards.discarded(owner, version, blog)
    assert owner.execute("SELECT status FROM publishing_jobs WHERE id=%s", (job,)).fetchone()["status"] == "blocked"
    assert owner.execute("SELECT 1 FROM content_versions WHERE id=%s", (version,)).fetchone()
    assert owner.execute("SELECT count(*) n FROM audit_events").fetchone()["n"] == before + 1
    listing = {"q": "P107 isolated", "language_code": "", "blog_id": "", "origin": "", "compact": True, "page": 1, "page_size": 25}
    archive = publications.list_publications(view="discarded", **listing)
    assert any(item["content_version_id"] == str(version) for item in archive["items"])
    assert not any(item["content_version_id"] == str(version) for item in
                   publications.list_publications(view="review", **listing)["items"])
    restored = publications.restore_manuscripts(publications.RestoreRequest(
        targets=[target], actor="Test operator", reason="Isolated restore reason",
    ))
    assert restored["success_count"] == 1
    assert not publication_discards.discarded(owner, version, blog)
    assert owner.execute("SELECT status FROM publishing_jobs WHERE id=%s", (job,)).fetchone()["status"] == "blocked"
    assert owner.execute("SELECT count(*) n FROM audit_events").fetchone()["n"] == before + 2


def test_published_manuscript_cannot_be_discarded(owner, monkeypatch):
    version, blog = _manuscript(owner)
    profile = owner.execute("SELECT id FROM language_profiles WHERE language_code='ko' AND target_country='' LIMIT 1").fetchone()["id"]
    policy = owner.execute("""INSERT INTO publishing_policies(language_code,blog_id,profile_id,active)
        VALUES ('ko',%s,%s,false) ON CONFLICT(blog_id,profile_id) DO UPDATE SET active=publishing_policies.active RETURNING id""", (blog, profile)).fetchone()["id"]
    job = owner.execute("""INSERT INTO publishing_jobs(policy_id,blog_id,content_version_id,idempotency_key,scheduled_at)
        VALUES (%s,%s,%s,%s,now()) RETURNING id""", (policy, blog, version, str(uuid4()))).fetchone()["id"]
    owner.execute("""INSERT INTO publishing_records(job_id,blog_id,content_version_id,remote_post_id,published_at,remote_url,remote_status,remote_verified_at)
        VALUES (%s,%s,%s,'p107',now(),'https://isolated.example/p107','LIVE',now())""", (job, blog, version))
    monkeypatch.setattr(publications, "connection", _connection(owner))
    result = publications.discard_manuscripts(publications.DiscardRequest(
        targets=[publications.DiscardTarget(content_version_id=version, blog_id=blog, previous_view="review")],
        actor="Test operator", reason="Do not discard published",
    ))
    assert result["success_count"] == 0
    assert result["failures"][0]["reason"] == "already_published"
    assert not publication_discards.discarded(owner, version, blog)
