# P5-CODEX-168 Blogger connection status timeout

- Work ID/time: P5-CODEX-168, 2026-11-20 Asia/Seoul.
- Reason: `/blogger` displayed only an API/authentication error and hid the OAuth manager.
- Before: Dashboard server rendering aborted `/admin/blogger/status` after five seconds. The authenticated local API returned HTTP 200 in 5.71 seconds, with 18 OAuth connections and seven blogs; it scanned the large append-only audit history repeatedly for each connection and event type. This was a timeout, not evidence of an OAuth credential failure.
- After: Materialize the two relevant connection audit event types once per status request and retain each connection's latest event. Increase the page request timeout to 12 seconds as additional headroom. No OAuth token, scope, Blogger connection, external write or automatic publication setting is changed.
- Files: `services/api/woori/blogger_routes.py`, `services/api/tests/test_google.py`, `apps/dashboard/app/blogger/page.tsx`, this record.
- Validation: Modified API status function took 2.04 and 1.79 seconds locally. After JSON serialization, all 18 existing connection records matched the old API for identity, verified blogs, timestamps, status and scopes. OAuth test suite: 31 passed; Ruff and mypy passed; pytest cache permission warning only. Real OAuth authentication was not initiated or changed.
- Related: `docs/development/P5-CODEX-167.md`; service runtime verification is recorded below. Commit: see git log for this record.
- Remaining: Runtime performance depends on audit growth; status still reads diagnostic aggregates. Unrelated scheduled Imports have repeated database constraint errors `non_trends_fact_check_timestamp_required`; this task did not change their schema or replay failed imports.

## Service reflection and browser check

- Applied `f684dcf4b24fffc78ead33a63f6bb4fec108a9e6` through graceful restarts of Dashboard, API and both Workers. Workers acknowledged control revision 29; master, scheduled and Trends automatic switches remained enabled and emergency/restriction flags remained false. The separate aggregate `AutoPolicyActive` indicator was already false before reflection and remained false; this task did not change publication policy or diagnose all its inputs.
- Reflection checks: 282 selected API tests, 35 Pester tests, Ruff, mypy, Dashboard lint/typecheck, isolated wheel and production build passed. Pytest cache permission warning only.
- After reflection, authenticated local Blogger status returned HTTP 200 in 1.32 seconds. Playwright opened `http://localhost:3100/blogger`: the error text was absent and Google read/write OAuth connection buttons were visible. The browser console had an unrelated missing favicon 404 and CSS preload warnings. No OAuth connection action or Google/Blogger write was performed. Start/completion audit events were appended.
