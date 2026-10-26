"""Enqueue an explicit real-model evaluation and wait for the existing Worker."""

import sys
import time
from uuid import uuid4

from woori import pipeline
from woori.db import connection
from woori.local_inference import runtime

if "--evaluation-only" not in sys.argv:
    raise SystemExit("Pass --evaluation-only; this does not approve model language quality.")
info = runtime()
with connection() as conn:
    keyword = conn.execute("""SELECT DISTINCT k.id,k.collected_at FROM keyword_candidates k
        JOIN collection_items i ON i.keyword_id=k.id JOIN collection_sources s ON s.id=i.source_id
        WHERE s.adapter='fed_rss' AND k.status='selected' AND k.expires_at>now()
        ORDER BY k.collected_at LIMIT 1""").fetchone()
    targets = conn.execute("""SELECT g.* FROM generation_settings g JOIN language_profiles p ON p.id=g.profile_id
        JOIN languages l ON l.code=p.language_code WHERE l.active AND g.enabled""").fetchall()
if (
    not keyword
    or not targets
    or any(
        t["provider"] != "local" or t["engine"] != "llamacpp" or t["model"] != info["model"]
        for t in targets
    )
):
    raise SystemExit("Real source or matching local-model settings missing; no fallback attempted.")
job = pipeline.enqueue(keyword["id"], "live-eval-" + uuid4().hex, evaluation_only=True)
print("Real evaluation queued:", job["id"], flush=True)
for _ in range(300):
    with connection() as conn:
        current = conn.execute(
            "SELECT id,status,error_type FROM job_runs WHERE id=%s", (job["id"],)
        ).fetchone()
        results = conn.execute(
            "SELECT v.language,g.state,g.content_version_id,g.result_metadata FROM generation_results g JOIN content_versions v ON v.id=g.content_version_id WHERE g.run_id=%s",
            (job["id"],),
        ).fetchall()
    if current and current["status"] in ("succeeded", "failed"):
        print("Real evaluation:", current, "stored drafts", len(results), flush=True)
        if current["status"] != "succeeded" or len(results) != len(targets):
            raise SystemExit(1)
        assert all(
            r["state"] == "quality_held" and not r["result_metadata"]["quality"]["publish_ready"]
            for r in results
        )
        for result in results:
            print(
                result["language"],
                result["state"],
                result["content_version_id"],
                result["result_metadata"].get("metrics"),
                flush=True,
            )
        break
    time.sleep(3)
else:
    raise SystemExit("Worker did not complete in 15 minutes; job remains durable.")
