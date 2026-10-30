# P5-CODEX-073 — Existing manual Job recovery and scheduled evidence diagnosis

Date: 2026-10-30 KST. Branch: develop. Prior approval and all versions/audits preserved.

## Manual publication

- Approved Job a6775a86-53e9-4102-ac8b-12b8c39e1cfd failed at 13:45:20 with Blogger HTTP 404 / not_found. This was not a local DB 404. Draft creation POST succeeded; the subsequent GET /blogger/v3/blogs/3321654108096579717/posts/8758150505870748115 omitted view=AUTHOR. The default reader view could not read the private draft.
- Read-only AUTHOR draft listing found that exact FOMC draft, and live listing was empty. Full draft GET confirmed exact approved title, HTML, labels, body hash and target. No extra draft POST was sent. Existing failed ledger/Job were reconciled to the verified draft, with a new append-only recovery event. No new approval or Job was created.
- Worker published the existing draft at 13:52:15; Google POST returned 200 and AUTHOR GET returned LIVE with exact content. A second defect then prevented local finalization: woori_app had SELECT but no INSERT on publishing_records. Worker reported InsufficientPrivilege; successful remote-write ledger remained durable.
- Backup created and pg_dump catalog verified before migration 059. Migration grants INSERT only on publishing_records, preserving the immutable trigger and no UPDATE/DELETE/TRUNCATE. Schema/test provisioning updated to 59. Rollback of the permission is REVOKE INSERT (without removing any records or migration audit).
- Remote LIVE content and successful publish ledger were reverified; reconcile_published_manual_job inserted the missing record, linked the existing six follow-up items through their review, and completed the existing Job without another POST.
- postId: 8758150505870748115. URL: https://trend-ko.blogspot.com/2026/10/2026-10-28-fomc-375400-10-2.html . Blogger API confirms LIVE/readback 200. The web browsing tool could not load the public Blogspot URL, so independent unauthenticated public-page HTTP verification is not claimed.
- Future drafts use AUTHOR readback. If a POST succeeds but readback fails, preserve the returned postId in an uncertain ledger, preventing blind recreation. Recovery helpers recheck approval hashes, remote title/HTML/labels/blog and existing ledger, serialize DB updates and retain failure events.

## Scheduled manuscripts

- Current failure inventory is 8 (all chatgpt_scheduled_export; no Trends imports in this failure set). Full per-import/version/title/target/source/claim/length/job inventory: P5-CODEX-073-auto-failures.md.
- The source collector previously supported two exact URLs and additionally required the manuscript-local source ID to equal its catalog label. Other sources had no application capture, but the evaluator incorrectly described claims as absent from a source it had never retrieved. Capture absence is now reported separately as claim_source_verification_unavailable; unsupported resources get explicit permanent capture-failure audit records with http_attempted=false. Unknown providers remain blocked by the shared outbound policy.
- Resource approval is now URL-based rather than tied to an import-local source ID. Existing reviewed federal_reserve provider supports bounded FOMC statement pages; collected the English Fed import's actual release, HTTP 200, SHA256 a7c37b4823527d2bd20996e8ab453edbaa3fd01ff1b966c4a8125787859dcead. Existing catalog sources remain supported; arbitrary hosts/query/redirects remain blocked.
- This does not approve the English article: all seven stored evidence excerpts are abbreviated/composite paraphrases (several contain ellipses), and none is a literal source excerpt. The whole-source sanitizer also rejects paragraphs citing a source if any attached claim is unverified. Rebuilding a reliable claim-to-paragraph map requires evidence-contract work; this change does not fabricate such mappings or pass claims based on link existence.
- No scheduled article was newly promoted, revised or queued. Automatic recovery remains incomplete: 8 held imports, 0 newly eligible, 0 new automatic Jobs, 0 automatic public posts. These are unresolved source-adapter/evidence-mapping limits, not Blogger API failures. Original prose and failed claims remain available for explicit revision; no empty sanitized body was published.

## Validation

- Four-language isolated DB transactions test manual approval/Job/follow-up insertion, draft reconciliation, published-ledger finalization, repeated recovery with one publishing record, and mismatched-language blocking. External transport is MockTransport; operational recovery used actual Google reads and the existing approved Worker job.
- AUTHOR query assertion, uncertain postId retention, source catalog constraints, missing-capture diagnosis, migration safety and existing scheduled publish-first regression suites run. Exact tests/runtime/Git results are appended after final verification.
