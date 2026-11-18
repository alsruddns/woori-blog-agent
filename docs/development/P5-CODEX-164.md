# P5-CODEX-164 Scheduled Codex research schema compatibility

- Work ID/time: P5-CODEX-164, 2026-11-19 Asia/Seoul.
- Reason and previous state: Scheduled research consistently reported `scheduled_codex_search_unavailable:CodexFailure`. A controlled diagnostic with the installed ChatGPT-authenticated Codex CLI 0.169.0 reproduced HTTP 400 before web search: its strict output schema rejects `format: uri` at the scheduled research source URL. The exception wrapper also hid the safe operational error code and misclassified usage-limit failures.
- Purpose and change: Remove the unsupported schema keyword while retaining the existing HTTPS, URL identity, open-source and downstream review checks; request the exact tool-emitted URL; preserve the existing safe CodexFailure code in scheduled failure classification. No publication policy, Trends path, historical occurrence, or queue is changed.
- Changed files: `services/api/woori/scheduled_research.py`, `services/api/tests/test_scheduled_research.py`, this record.
- Validation: Before the fix, the actual strict schema produced `invalid_json_schema`; after it, an authenticated diagnostic performed three web searches and source openings, but its chosen AP canonical URL differed from the observed tool URL and was correctly held. The prompt was strengthened; this diagnostic did not create a Research Package, manuscript, Import, or publication. Tests and reflected service status are recorded in the follow-up commit or git log.
- Related: `docs/operations/scheduled-outage-recovery.md`, P5-CODEX-106, P5-CODEX-162.
- Commit: see git log for this record and follow-up.
- Remaining: Actual future scheduled execution, evidence validation, Import, remote duplicate and Blogger wire admission must succeed independently. A search or read-only policy check does not prove public publication. Existing failed occurrences are not replayed.

## Verification and service reflection

- The strengthened exact-URL prompt was exercised in a separate authenticated diagnostic: two searches completed and `evidence_available` was returned with no collection failures. This was a diagnostic only, not a scheduled occurrence or publication.
- Applied code commit `972a193e4cedda3a21e56725f4c2b0dc84171771`: related API tests 62 passed; Pester 35 passed; Ruff, changed-module mypy, isolated wheel and Dashboard production build passed. Pytest reported a cache write permission warning.
- API, Research Worker, and Publication Worker were gracefully restarted and reported the code commit; both Workers acknowledged control revision 29. Master Auto, scheduled Auto and authoring were enabled and emergency stop was false. No settings were changed. Publication Worker reported the scheduled/manual/Trends execution mode and active policy. Its status also displayed `automatic_publication_suspended` for at least one paused queue item; this does not establish that a future scheduled manuscript has passed all publication gates.
- Start and completion audit events were appended to PostgreSQL. A real scheduled Import and LIVE write remain unverified; no old occurrence was replayed.
