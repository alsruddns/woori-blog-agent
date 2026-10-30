# P5-CODEX-076 — Read-only Publication Worker monitor

Date: 2026-10-30 KST; develop. Existing publishing policies, Jobs, sources and audit records preserved.

## Change

- Added authenticated GET /admin/publications/worker-jobs and same-origin GET proxy allowlist. Read-only monitor selects real blogger_live/non-simulation Jobs and verified remote publication records, plus latest per-import/blog auto failure events with no corresponding live Job. No dispatch, retry, approval, OAuth, publishing transport or schema change.
- Explicit period: all registered Jobs, current status, Mock excluded. Counts separate queued, running, remotely verified LIVE, failed/blocked/uncertain/cancelled, and pre-Job failure. Recovered failures are not counted as current failures. Worker running/stopped/stale (45 seconds) is separate from the DB running-Job count.
- Job rows contain exact version/title/target/import origin/lane/ID, earliest registration audit time, latest Worker-claim time, latest state timestamp, stage, last audit timestamp, retries and failure category, and verified-only public URL. Missing timestamps remain unknown. Expired running leases are flagged; no invented percentage or progress is shown.
- Added the monitor above existing manuscript summary/tabs in publishing. State filter and pagination, exact imported manuscript deep links, bounded titles/IDs, existing themed cards and responsive mobile Job cards with monitor-specific column labels. Existing manual publish and Scheduled Auto controls remain unchanged.
- Local polling is independent of the heavier manuscript list: one no-store request per 10 seconds while visible, no overlapping calls, AbortController cleanup/filter change/hidden-tab abort, visibility resume and manual refresh. No new real-time infrastructure.
- Changed files: services/api/woori/publication_monitor.py; publications.py GET wrapper; tests/test_publication_monitor.py; apps/dashboard/app/publishing/publication-worker-panel.tsx, publication-manager.tsx; app/api/publications/[[...path]]/route.ts; app/style.css; this record.

## Verification

- Isolated rollback test covers queued/running/verified-published/failed Jobs, pre-Job failures, all filter results, authorization, invalid filter rejection and unchanged audit count after all GETs. Heartbeat tests cover stopped, never-started, delayed and fresh independently of Job status. No synthetic Job was inserted into the operating database.
- Focused monitor/publication regression: 46 tests passed. Ruff/mypy and frontend ESLint/TypeScript passed during implementation. Final Production Build, browser/poll/mobile and runtime evidence follow below.
- Initial live read: queued 0, running 0, published 3, failed/held Jobs 0, pre-Job failures 6; Worker running PID 51292. These are current counts, not cumulative failure attempts. No new Blogger writes were performed.
- Windows native Computer Use pipe was unavailable; Playwright browser tool connected successfully for actual localhost verification. Mobile/visibility results are recorded after runtime reflection.

## Final runtime and browser evidence

- Code commits: eee4c622802f57502e75f32b3a8b7033e9205757 (monitor/API/tests) and 93df640f19b9011603d2de7712f8d3cdd3bfb6b3 (mobile labels and manuscript count wording). Final documentation commit follows these in git log.
- Production Build passed in isolated `.next-p5-93df640f19b9`; generated TypeScript configuration files were restored. Dashboard latest listener PID 38812 (runner 48728), API listener PID 15620 (runner 12228, backend commit eee4c62). Only changed API/Dashboard were reflected. Research PID 22828 and Publication PID 51292 were preserved without restart.
- First Dashboard stop correctly refused two active browser connections; navigated the verification browser away, then the existing stop/start scripts completed graceful Dashboard replacement. No forced termination.
- Actual browser GET `/api/publications/worker-jobs` HTTP 200 at 2026-10-30 15:42:36 KST: queued 0, running 0, verified LIVE 3, failed/held Jobs 0, pre-Job failures 6. Worker running, PID 51292, `operations-scheduled-auto-and-manual`, latest heartbeat 15:42:21 KST. Worker is idle, not processing a Job.
- All six UI filter selections returned HTTP 200 with totals 0 / 0 / 3 / 0 / 6 / 9 for queued / running / published / failed / pre-Job / all. Empty states are shown for actual zero-count states. Nonempty queued/running/failed states were verified in the isolated DB tests, not fabricated in operations.
- Actual visible polling over 11 seconds: 1 request; hidden over 11 seconds: 0; visible resume: 1; maximum simultaneous requests: 1. Browser console errors/warnings: 0; fresh page runtime errors: 0.
- CSS viewport 390px in light and dark: document scroll width 390px; desktop CSS viewport 1280px: document scroll width 1280px. Screenshots visually reviewed, including mobile Job card labels, wrapped ID, exact imported manuscript/version links and verified public URL.
- Untracked browser evidence retained locally: `.playwright-mcp/P5-CODEX-076-desktop-final.png`, `P5-CODEX-076-390-light.png`, `P5-CODEX-076-390-dark.png`, `P5-CODEX-076-390-job-card.png`. Screenshots and temporary artifacts are excluded from commits.
- No migration, new operational Job, approval, retry, Blogger write or Worker-policy modification. Current existing three successful Job histories are displayed; this task did not publish those posts. Future live transitions depend on actual new Jobs.
- Checks: focused Python regression 46 passed; Ruff/mypy passed; ESLint and TypeScript passed; final Production Build passed; diff whitespace check passed. No unrelated full frontend regression suite was claimed.
