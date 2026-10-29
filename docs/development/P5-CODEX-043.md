# P5-CODEX-043 — Scheduled Blogger approval and duplicate preflight

- Work ID: P5-CODEX-043
- Started: 2026-10-29 KST
- Changed: append-only scheduled-publication approval, reservation-only live queue lane, OAuth read verification, and read-only scheduled duplicate preflight.
- Reason: normal scheduled manuscripts had no explicit approval path; duplicate checks treated failed intake files as if the manuscript were already imported.
- Before: operational schema 51; legacy `operations_auto_approved` remained false-only; live Blogger operations had no scheduled-only operator policy; no reusable endpoint classified DB imports, failed local files, and Blogger live posts.
- After: additive schema 52 provides append-only scheduled policy/first-publication events and a lane column; a bearer-authenticated operator can explicitly enable/stop scheduled-only publication (default remains OFF), with a separate first exact-version/hash/blog confirmation; reservation tasks can query a bounded duplicate preflight endpoint; OAuth A read-verified all four active blogs and remote URL hosts.
- Files: `scripts/052_scheduled_publication_approval.sql`, `scripts/migrate.py`, `scripts/provision-test-database.py`, `services/api/woori/publications.py`, `services/api/woori/publication_worker.py`, `services/api/woori/content_imports.py`, `services/api/woori/scheduled_duplicates.py`, `services/api/woori/external_policy.py`, `services/api/woori/google_oauth.py`, `services/api/woori/blogger_service.py`, related API tests, `scripts/publication-worker.py`, Dashboard proxy and existing publication manager.
- Tests: `compileall`, targeted Ruff, Dashboard `npm run typecheck`, Dashboard `npm run lint`, and 115 focused API tests passed. Operational backup `backups/20261029T084700Z.dump` archive catalog was verified before migration 052.
- Git: pending at document creation; final SHA is available from `git log` after commit.
- Related: P5-CODEX-041 import rules; P5-CODEX-042 scheduled publication request; AGENTS.md Phase 5-G and Phase 5-C policies.
- Runtime: schema 52 is active. Counts after migration: 1 existing import (`manual_codex_import`, Korean FOMC, `awaiting_human_review`), 0 scheduled-auto jobs, 0 scheduled-auto policy events, 0 first-publication approvals; legacy auto-approved remains false; 4 active blogs.
- OAuth/API: OAuth A's existing refresh token refreshed successfully (`oauth.refreshed` audit count +1) and it was read-verified against all four mapped blog IDs and URL hosts; Blogger POST/write count is 0. The real duplicate preflight for the existing FOMC import returned `already_imported`; the complete live Blogger listing found no matching title. A second real preflight over the two preserved 2026-10-29 Korean quarantine/rejected files returned `failed_only`, listed both content IDs, and allowed a new unique original ID. Both checks recorded audit events and did not change files. These application-function runs used the new code directly because the already-running API was not restarted; the authenticated HTTP route requires the operator's graceful API restart.
- Runtime processes: Dashboard 3100 and API 8100 are healthy; Research Worker and Publication Worker heartbeats are running, with 0 MockQueued/LiveQueued/LiveDue and idle reason `no_queued_job_in_enabled_lane`. Existing user-owned processes predate these changes and were not stopped; they require a graceful operator restart before the new routes/worker option can run.
- Remaining: no scheduled-export import exists in operations DB; the existing manual Codex FOMC manuscript is not eligible for this lane. Auto remains OFF. No first exact manuscript approval or Auto policy enable event has been recorded. No Blogger write or public post was made.

## Scheduled duplicate preflight

Endpoint (through the same-origin Dashboard proxy):

`POST http://127.0.0.1:3100/api/research/content-imports/duplicate-check`

Send `Origin: http://127.0.0.1:3100` and JSON:

```json
{
  "language_code": "ko",
  "target_country": "KR",
  "target_blog_id": "3321654108096579717",
  "trade_date": "2026-10-29",
  "event_group_id": "kr-market-close-2026-10-29",
  "topic": "Korean market close analysis",
  "content_id": "optional-existing-id-to-check"
}
```

The proxy injects the configured local admin credential; scheduled prompts must not read `.env`, query PostgreSQL directly, or call Blogger write methods. The API checks operational imports, related content/publication records, matching local files, then performs a bounded Blogger live-post GET scan. The read call records service/audit metadata, but it does not mutate manuscripts, import state, Blogger, or publish queues.

Interpret statuses strictly:

- `already_published`: verified publication record or matching remote live title; stop generation/publication for that event.
- `already_imported`: use the existing imported manuscript/version and continue its existing review path; do not create another original.
- `failed_only`: only matching quarantine/rejected files exist, with no database import or remote post. Preserve those files and a new unique `content_id` may be submitted as `relation: "original"` with no `parent_content_id`.
- `not_found`: DB and a complete remote live listing had no match; use a new unique original ID.
- `unknown`: a matching incoming/ready/processing/completed file exists, Blogger scanning is partial, credentials/permissions are unavailable, or a local inbox safety check failed. Stop; never interpret unknown as absence.

The endpoint is deliberately conservative and title-based for remote Blogger comparison. If Blogger has more than the scan cap, it returns `unknown`, never `not_found`. Final auto-publication independently repeats database and remote duplicate gates.

## Scheduled-publication operator procedure

1. Restart API and Dashboard from their original terminals so schema 52 routes/proxies load; do not terminate them by PID. Current processes were not restarted in this task.
2. In Dashboard > 발행 관리, select only the intended active blogs and click `선택 블로그 읽기 연결 확인`. Policy enable requires a successful check for every selected blog from the last 24 hours. On 2026-10-29 OAuth A read-checked all four registered blog IDs and matching URL hosts. This was GET-only; no Blogger write occurred.
3. Enter the operator label/reason and exact enable confirmation. This records a scoped, append-only scheduled-only policy event; it does not modify the legacy manual/Trends approval flag. A schedule-scoped external write context prevents that approval from authorizing manual/Trends publication.
4. For the first scheduled manuscript only, inspect its exact imported version and body hash, then record the separate first-publication approval. That is the one-time initial operator gate. Later eligible scheduled manuscripts in the enabled scope do not require per-manuscript publication clicks.
5. Start the scheduled-only worker from an operator-controlled terminal after safely stopping the prior worker from its owning terminal:

```powershell
.\.venv\Scripts\python.exe .\scripts\publication-worker.py --operations-scheduled-auto --continuous
```

Do not run this alongside an existing publication worker. Auto policy remains disabled until the operator completes steps 2–4. A successful exact first publication allows later jobs under the same scoped policy, subject to each manuscript's evidence, rights, dedupe, language, HTML, and quota gates.

The first-post record is available through the same-origin Dashboard proxy at `POST http://127.0.0.1:3100/api/publications/scheduled-auto-first-post`. It requires the exact `blog_id`, `import_id`, `import_version_id`, linked `content_version_id`, current `body_sha256`, operator label, reason, unique idempotency key, and exact confirmation text `APPROVE THIS SCHEDULED MANUSCRIPT FOR FIRST PUBLICATION`. Obtain identifiers and hash from the reviewed current imported version; never guess them. Stopping Scheduled Auto from the Dashboard appends a disable event and revokes outstanding first-publication approvals in scope. Neither setting endpoint itself publishes a post.

## Migration and rollback

Migration 052 is additive; existing jobs receive the `manual` lane and the legacy false-only CHECK remains intact. The operational database was backed up and the custom-format archive catalog validated before applying it. Disable scheduled publication by appending a `disabled` policy event. Do not drop immutable event tables or rewrite migration history; schema rollback requires a separately reviewed forward migration, not destructive rollback.
