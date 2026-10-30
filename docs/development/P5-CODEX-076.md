# P5-CODEX-076 — Read-only Publication Worker monitor

Date: 2026-10-30 KST; develop. Existing publishing policies, Jobs, sources and audit records preserved.

## Change

- Added authenticated GET /admin/publications/worker-jobs and same-origin GET proxy allowlist. Read-only monitor selects real blogger_live/non-simulation Jobs and verified remote publication records, plus latest per-import/blog auto failure events with no corresponding live Job. No dispatch, retry, approval, OAuth, publishing transport or schema change.
- Explicit period: all registered Jobs, current status, Mock excluded. Counts separate queued, running, remotely verified LIVE, failed/blocked/uncertain/cancelled, and pre-Job failure. Recovered failures are not counted as current failures. Worker running/stopped/stale (45 seconds) is separate from the DB running-Job count.
- Job rows contain exact version/title/target/import origin/lane/ID, earliest registration audit time, latest Worker-claim time, latest state timestamp, stage, last audit timestamp, retries and failure category, and verified-only public URL. Missing timestamps remain unknown. Expired running leases are flagged; no invented percentage or progress is shown.
- Added the monitor above existing manuscript summary/tabs in publishing. State filter and pagination, exact imported manuscript deep links, bounded titles/IDs, existing themed cards and horizontally scrollable mobile table. Existing manual publish and Scheduled Auto controls remain unchanged.
- Local polling is independent of the heavier manuscript list: one no-store request per 10 seconds while visible, no overlapping calls, AbortController cleanup/filter change/hidden-tab abort, visibility resume and manual refresh. No new real-time infrastructure.
- Changed files: services/api/woori/publication_monitor.py; publications.py GET wrapper; tests/test_publication_monitor.py; apps/dashboard/app/publishing/publication-worker-panel.tsx, publication-manager.tsx; app/api/publications/[[...path]]/route.ts; app/style.css; this record.

## Verification

- Isolated rollback test covers queued/running/verified-published/failed Jobs, pre-Job failures, all filter results, authorization, invalid filter rejection and unchanged audit count after all GETs. Heartbeat tests cover stopped, never-started, delayed and fresh independently of Job status. No synthetic Job was inserted into the operating database.
- Focused monitor/publication regression: 46 tests passed. Ruff/mypy and frontend ESLint/TypeScript passed during implementation. Final Production Build, browser/poll/mobile and runtime evidence follow below.
- Initial live read: queued 0, running 0, published 3, failed/held Jobs 0, pre-Job failures 6; Worker running PID 51292. These are current counts, not cumulative failure attempts. No new Blogger writes were performed.
- Windows native Computer Use pipe was unavailable; Playwright browser tool connected successfully for actual localhost verification. Mobile/visibility results are recorded after runtime reflection.
