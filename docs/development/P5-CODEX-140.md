# P5-CODEX-140 — Scheduled Codex CLI live research retry

## Work record

- Work ID: P5-CODEX-140-RETRY
- Work date: 2026-11-05 (Asia/Seoul)
- Branch: develop
- Starting HEAD: aab2b5eeca4b2633871d01290d5b9255bfe6b90d
- Starting origin/develop: aab2b5eeca4b2633871d01290d5b9255bfe6b90d
- Starting tracked worktree: contained the initial P140 draft edits in external_policy.py and zero-cost-policy.md. Initial P140 draft helpers/tests were untracked. Those files were reviewed and continued; unrelated untracked files and the existing stash were preserved.
- Starting operations schema: 92. No migration was added.

## Cause and direction change

The 2026-11-05 09:00 KST automation-7 execution had passed its Resolver and local Duplicate Preflight. It stopped because the scheduled session did not expose its own web-search tool. The previous P140 draft treated missing scheduled-session web search as a blocker and did not use the supported local Codex CLI path.

The operator then explicitly authorized codex --search using the existing ChatGPT Plus Codex allowance. This authorization does not include a separate OpenAI API key, metered API, credit purchase, or paid fallback.

At execution time:

- codex login status: Logged in using ChatGPT.
- Installed Codex CLI: codex-cli 0.166.0-alpha.5.1.
- billing_credential_names(): empty list.
- A live codex --search exec --json probe emitted a web_search event.
- The scheduled research adapter also completed a live web_search event under the existing codex_runner process boundary.
- No separate OpenAI API endpoint was called.

The official Codex CLI documentation states that --search selects live web search and that codex exec --json exposes search events. The code now passes this global option before exec; it is enabled only for this scheduled research path.
Official references: https://learn.chatgpt.com/docs/cli/reference and https://learn.chatgpt.com/docs/web-search.

## Implemented path

The scheduled research broker now performs:

1. Re-resolve the current Desktop invocation and require scheduled mode.
2. Require current automatic-authoring permission and exact invocation identity in the supplied preflight.
3. Require local_status=not_found|failed_only and draft_import_allowed=true; retain overall_status=unknown and remote_status=not_checked.
4. Invoke the installed Codex CLI through codex_runner.execute(..., enable_search=True).
5. Match returned source URLs and titles to actual web_search results. Store the exact result snippet, source URL/domain/title, model-reported publication date, collection timestamp, CLI model, search count, execution ID, and explicit semantic/rights review requirements.
6. Reject absent, future, or older-than-14-day publication dates. Date-only evidence stays date-only; no timezone or time is fabricated.
7. Write an immutable scheduled-research-package/1.0 Research Snapshot through the existing atomic snapshot writer. A prior staging file is not overwritten.
8. Append a database audit event. A search execution failure is also recorded with a bounded reason code and api_key_fallback=false.

The Codex result is a search-result evidence package. Its excerpt, publisher, and date are not described as independently verified full-page evidence. Semantic truth, reuse rights, review, Import, publication eligibility, and Blogger publication remain separate gates. The prompt directs the scheduled author to use the saved package in its article snapshot and claim mapping.

The existing bounded RSS helper remains available as fallback for its supported source categories: White House, BLS/Federal Reserve, and NIST. It does not accept arbitrary URLs. Codex usage-limit, authentication, capacity, or timeout errors stop the run and do not switch to RSS or a paid route. Source insufficiency can use the fixed RSS fallback where a matching category exists.

## Live CLI research probe

The isolated live probe used the current ChatGPT login and did not call an Import or Blogger endpoint.

- Query: latest U.S. BLS JOLTS results.
- Search result status: evidence available; one live web_search event.
- Sources retained in the in-memory Research Package:
  - Axios, published 2026-11-03: https://www.axios.com/2026/11/03/jolts-labor-market-ai-jobs
  - Associated Press, published 2026-11-03: https://apnews.com/article/4f6f06216c943fc2f8306306fd3056e3
- Core returned evidence referenced BLS JOLTS data for September and labor-market/job-posting measures; the saved excerpt is the exact search-result snippet and remains unverified beyond that result.
- A separate Employment Situation query returned the October release date as November 6, 2026 and correctly produced no current article source as of November 5. The older October 2 release was not represented as fresh.

The live source package was returned in memory for this probe and was not saved under the old automation-7 09:00 occurrence. The isolated test writes the package only to a temporary test directory.

## Active automation prompt updates

The shared automation prompt updater was changed to append the P140 live-search contract while preserving existing P131 instructions. It was run in dry-run mode, then applied to the 20 active project-local Automation TOMLs.

- Backup: %USERPROFILE%\.codex\automation-backups\P5-CODEX-140-RETRY-20261105T005805Z
- Backup for the manual Run now distinction correction: %USERPROFILE%\.codex\automation-backups\P5-CODEX-140-RETRY-20261105T011035Z
- Backup for RSS-category relevance criteria: %USERPROFILE%\.codex\automation-backups\P5-CODEX-140-RETRY-20261105T011218Z
- Active definitions updated: 20.
- Paused automation-10: unchanged.
- Verified for each backup pair: ID, active state, RRULE, model, target, checkout, and creation identity unchanged; new marker appears once.
- No Automation was created, deleted, paused, or rescheduled.
- The native Scheduled UI control pipe was unavailable. The local TOML files were changed and read back; the active prompt as loaded by a future Desktop execution has not yet been confirmed.
- The broker accepts the common general category. RSS fallback remains restricted to its supported categories and is not claimed to cover every scheduled topic.
- The P140 contract explicitly keeps official Desktop Run now in the existing manual_codex_import lane; the scheduled-only broker rejects manual identity.
- Prompt category guidance only selects a fixed RSS family when it is source-relevant (U.S. policy, BLS/Federal Reserve, or NIST cybersecurity); all other topics use general search without unrelated RSS fallback.

## Tests and runtime state

- Focused test_scheduled_research.py + test_keyword_authoring.py: 25 passed.
- Full services/api/tests suite: 929 passed.
- Ruff: passed after fixing all reported issues.
- mypy on scheduled_research.py and codex_runner.py: passed.
- py_compile on the changed Python scripts/modules: passed.
- Isolated Python wheel build: passed.
- No Dashboard source changed; Dashboard lint/typecheck/build were not applicable to these changes.
- No P140-driven Blogger test write, draft creation, historical occurrence replay, Import, or publication was run.
- One normal Trends Auto LIVE publication was observed from the already-running worker at 2026-11-05 10:03:37 KST (publishing Job ca03e656-9570-4d82-a662-8f4fc8d133a0, lane trends_auto, blog Trend Journal EN). This was not a P140 test write and occurred before the new code was reflected into the services.

Before service reflection, the operational status showed healthy API, Dashboard, Research Worker, and Publication Worker. AutoMode was auto, AutoPolicyActive was true, Publication Worker was in scheduled-auto/manual/Trends mode, and the publication queue had zero queued/due Jobs after the Trends Auto LIVE publication. At the first queue check, one Research Job was writing and one was queued. Both later reached a state with no active Research Jobs before restart planning. No forced termination is permitted.

All four services must be gracefully restarted after the active Research Jobs clear, using the existing service lifecycle scripts. Restart, new PID/heartbeat, runtime source revision, and HTTP checks remain pending until that safe window is reached.

## End-to-end status

| Stage | Result |
|---|---|
| Resolver and Duplicate Preflight contract | Preserved and rechecked by broker |
| Live Codex CLI search | Verified with ChatGPT login |
| Research Snapshot package | Saved in isolated test; live probe package remained in memory |
| Scheduled manuscript generation | Not yet observed in a new official Desktop run |
| Envelope handoff / Research Import / Import Receipt | Not yet observed in a new official Desktop run |
| Publication Queue / Blogger LIVE | No P140 job was enqueued; one independent, normal Trends Auto LIVE write was observed as noted above |
| Existing 2026-11-05 09:00 failed occurrence | Not replayed |

The code and local prompt changes are ready for operational reflection. The next new scheduled occurrence is required to verify the official Desktop prompt reload and complete the actual manuscript-to-Import path. No operation is reported as an end-to-end production success before that evidence exists.

## Changed files

- services/api/woori/codex_runner.py
- services/api/woori/scheduled_research.py
- services/api/woori/external_policy.py
- services/api/tests/test_scheduled_research.py
- services/api/tests/test_keyword_authoring.py
- scripts/scheduled-research-broker.py
- scripts/update-codex-automation-authoring-recovery.py
- docs/operations/zero-cost-policy.md
- docs/development/P5-CODEX-140.md

## Remaining work

- Run the normal service reflection/restart workflow and restart all four services together; verify P140 code revision, PIDs, HTTP 200, Worker heartbeats, AutoMode, AutoPolicyActive, 15-minute interval, daily cap, six-blog scope, and publication priority.
- Observe a new official Desktop scheduled execution. Confirm package file, manuscript envelope, Import receipt, and publication queue only if naturally produced by that new run.
- Record operating revision, post-restart PIDs, completion audit event, final Git commit, and push outcome in a follow-up section after reflection.

## Completion metadata

- End HEAD: pending.
- Commit: pending.
- Origin push: pending.
- Final PostgreSQL completion audit: pending.
