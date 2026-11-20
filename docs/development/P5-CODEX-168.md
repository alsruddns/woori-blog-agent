# P5-CODEX-168 Blogger connection status timeout

- Work ID/time: P5-CODEX-168, 2026-11-20 Asia/Seoul.
- Reason: `/blogger` displayed only an API/authentication error and hid the OAuth manager.
- Before: Dashboard server rendering aborted `/admin/blogger/status` after five seconds. The authenticated local API returned HTTP 200 in 5.71 seconds, with 18 OAuth connections and seven blogs; it scanned the large append-only audit history repeatedly for each connection and event type. This was a timeout, not evidence of an OAuth credential failure.
- After: Materialize the two relevant connection audit event types once per status request and retain each connection's latest event. Increase the page request timeout to 12 seconds as additional headroom. No OAuth token, scope, Blogger connection, external write or automatic publication setting is changed.
- Files: `services/api/woori/blogger_routes.py`, `services/api/tests/test_google.py`, `apps/dashboard/app/blogger/page.tsx`, this record.
- Validation: Modified API status function took 2.04 and 1.79 seconds locally. After JSON serialization, all 18 existing connection records matched the old API for identity, verified blogs, timestamps, status and scopes. OAuth test suite: 31 passed; Ruff and mypy passed; pytest cache permission warning only. Real OAuth authentication was not initiated or changed.
- Related: `docs/development/P5-CODEX-167.md`; service runtime verification is recorded below. Commit: see git log for this record.
- Remaining: Runtime performance depends on audit growth; status still reads diagnostic aggregates. Unrelated scheduled Imports have repeated database constraint errors `non_trends_fact_check_timestamp_required`; this task did not change their schema or replay failed imports.
