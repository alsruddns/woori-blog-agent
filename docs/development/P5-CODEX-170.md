# P5-CODEX-170 Publication management timeout and Trends diagnosis

- Work ID/time: P5-CODEX-170, 2026-11-20 Asia/Seoul.
- Reason: Publication management showed a local API connection error, and the user clarified the earlier eligibility failure concerned a Trends manuscript.
- Before: Local API health was HTTP 200; authenticated compact publication list returned HTTP 200 after 6.00 and 6.26 seconds, exceeding the Dashboard's five-second timeout. The read-only list also repeated a manual permission lookup already present in the mode-settings capability snapshot. An actual connection failure and a timeout had the same message.
- After: Reuse the already-computed manual capability in this read-only response, extend the initial request timeout to 20 seconds, and show a distinct timeout message and retry link. Authorization, write-time permission checks, Trends/Scheduled policies and jobs are unchanged.
- Trends diagnosis: Recent pre-job eligibility records show `high_impact_topic_requires_review`; multiple Trends jobs also reached a separate `automatic_duplicate_unconfirmed_or_found` hold. Audit records during those duplicate lookups show `free_quota_exceeded`. The exact item was not identified; no remote calls or retries were performed, no quota or duplicate checks were bypassed, and uncertain jobs were not replayed.
- Changed files: `services/api/woori/publications.py`, `apps/dashboard/app/publishing/page.tsx`, this record.
- Validation: 63 publication and monitor tests passed, Ruff and mypy passed; pytest cache warning only. Direct read-only list timings after the change were 4.88 seconds for review and 3.37 seconds for auto-failure under concurrent tests. Related: `docs/development/P5-CODEX-169.md`; commit identity via git log.
- Remaining: Verify actual page after deployment. Provider quota availability, exact Trends article identity and remote uniqueness remain unresolved; no public write or requeue is claimed. The separate scheduled Import DB constraint mismatch previously reported remains outside this fix.
- Follow-up test: Added a regression check that the read-only list uses the computed capability snapshot without invoking a second manual permission check; it passed in the isolated test database.

## Service reflection

- Applied `238c262fae59e7a2978a34c25c6449696867b495` after 54 API tests, Ruff, mypy, Dashboard lint/typecheck, wheel and production build passed. Pytest cache write warning only.
- First reflection attempt left all services running because this task's browser had open connections to the Dashboard. The verification browser was closed; a second validated reflection gracefully restarted Dashboard, API and Publication Worker. Research Worker was not restarted. No force termination was used.
- Browser verification of `/publishing?view=auto_failure` loaded 13 rows without the API unavailable or timeout message. Worker and control state were checked; no settings were changed. Start/completion audit events were appended. Exact user article, separate quota-exceeded cause, and existing uncertain jobs remain unverified or held.
