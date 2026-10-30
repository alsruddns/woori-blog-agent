# P5-CODEX-071 — Duplicate preflight recovery and manual publication transaction repair

- Work ID: `P5-CODEX-071`
- Date: 2026-10-30 (Asia/Seoul)
- Branch: `develop`
- Reason: a local duplicate preflight failed with `URLError`, and the FOMC manual publication POST had historical HTTP 503 / SQLSTATE `P0001` records without diagnostic context.

## Findings

- The crypto run at 13:17 KST was a manual rerun, not a scheduler-issued retry. Its research snapshot retained the 10:30 scheduled task context, but no occurrence ID was supplied for the 13:17 invocation. It must not be exported as a scheduled occurrence.
- The snapshot records `URLError` but not `URLError.reason`, so the historical low-level errno cannot be recovered. The lifecycle log shows the duplicate-preflight timestamp window overlapped API/Dashboard service reflection: API stop requested at `2026-10-30T04:17:32Z`, Dashboard stop at `04:17:42Z`, then API and Dashboard started at `04:18:05Z` and `04:18:08Z`. This establishes a local availability race as the likely cause; it does not prove whether the client observed refusal, reset, or timeout.
- API 8100 and Dashboard 3100 are listening now. A same-key generation preflight returned HTTP success with `local_status=not_found`, `draft_import_allowed=true`, `remote_status=not_checked`, and `publication_recheck_required=true`. This confirms P5-CODEX-066 generation-stage behavior is active. No Blogger read was performed.
- The FOMC Content Version `65133867-88d3-427a-bc24-b6994625eb38` remains linked to import `b4c45d23-0c74-4b12-92fd-382633093afa`, generation method `manual_codex_import`. Before this work, its operations DB query showed zero manual approval events and zero publication jobs. No operational POST or Blogger write was sent.
- The two historical API stderr entries report SQLSTATE `P0001` but lack PostgreSQL primary message, function, table, request time, or request ID. PostgreSQL logs had no matching detail in the prior read-only investigation. That historical `P0001` cannot be attributed retroactively to one trigger.
- Reproducing the current route in the isolated rollback test database found a current deterministic HTTP 503 cause: `42P10` from `ON CONFLICT(publishing_job_id)` failing to infer the partial unique index `post_publication_reviews_job_uq` (`WHERE publishing_job_id IS NOT NULL`). Operations and test schemas both contain that partial index. The INSERT now states the matching predicate.
- The reproducible PostgreSQL diagnostic identified `source_function=infer_arbiter_indexes`; the failure occurred while planning the follow-up-review INSERT, after the Job and approval INSERTs had begun. Because the endpoint uses a single transaction, the failed request rolled the entire transaction back. The corrected isolated route now commits the expected rows and its idempotent replay returns the existing Job.

## Changes

- `scripts/scheduled_duplicate_check.py`: bypass machine proxy configuration for the fixed loopback URL, use a 4-second timeout, retry transport failures at most three times with short bounded backoff, and preserve `unknown` while returning a safe transport category (`connection_refused`, `connection_reset`, `timeout`, etc.). HTTP errors are not retried.
- `services/api/woori/publications.py`: make the manual prepublication review `ON CONFLICT` target match the existing partial unique index. No approval or live publication behavior changed.
- `services/api/woori/main.py`: include a random request ID and safe SQLSTATE/error category in DB failure logs and 503 response. A narrow allowlist maps known database guard messages; arbitrary PostgreSQL text is not returned or logged.
- Tests cover bounded retry/recovery, connection refusal classification, HTTP error behavior, DB error redaction/classification, and an actual manual publication POST transaction in the isolated rollback database. The integration test verifies one approval, one queued job, one follow-up review, and idempotent replay; it performs no Blogger call.

## Validation and operational boundary

- Same-key generation preflight: successful local check, `draft_import_allowed=true`; no JSON envelope or ready file was created because this run was manual and not a genuine scheduled execution.
- Isolated manual POST integration route: passed after the partial-index conflict target fix. This is not an operational DB POST.
- Scoped validation: Ruff passed; mypy passed; pytest `50 passed`; `py_compile` passed; `git diff --check` passed.
- Operations schema remains version 58; no migration was needed.
- No existing approval/job/audit rows were deleted or changed. No Blogger POST, OAuth refresh, or publication request was made.
- Historical `P0001` remains unclassified; the current route's reproducible 503 cause (`42P10`) is fixed. A future database failure now exposes a safe code and correlation request ID so it can be tied to the DB source without exposing content or credentials.
- Actual FOMC POST, Blogger post ID, and public URL: none. The user must issue a fresh explicit publish click for the exact confirmed article if they still want publication; this task did not create a new request.
- Tests, commit SHA, and push result are recorded in Git history and the final follow-up section below.

## Final follow-up

- Code commit: `96cfea3` (`Fix : [Publication] Repair manual request transaction`).
- Development-record commit: recorded in the Git commit containing this file.
- Remaining issue: historical `P0001` lacks enough retained diagnostics for exact retrospective attribution; live manual publication has not been retried and no public URL exists.
