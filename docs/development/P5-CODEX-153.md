# P5-CODEX-153 — Automation settings history page crash

## Work record

- Work ID: P5-CODEX-153
- Date/time: 2026-11-16 (Asia/Seoul)
- Branch: `develop`
- Starting HEAD: `54f462ca89fe0a9bfb0863b51057a1ef50ecdd01`
- Code commit: `a66ef4a9a1677d9032282b7fcae9cce7bde0d791` (`Fix : [Automation UI] Render changed_fields history`)
- Reason: The operator reported that `/operations/automation` opened an error page.
- Prior issue: The API returned HTTP 200 with an append-only control-history event whose payload had `changed_fields` and no `changes` array. The UI unconditionally called `event.payload.changes.map(...)`, causing a client `TypeError` and the generic Next.js error page. Restarting alone could not fix this payload/UI contract mismatch.
- Objective: Keep the automation settings screen available across both historical change payload shapes without modifying any publication controls or stored audit history.

## Change

- Before: legacy events with `changes` rendered; the current `changed_fields` event crashed the entire page on `.map`.
- After: the history renderer checks both values are arrays, displays legacy key/before/after changes, and displays `changed_fields` entries as field names. The event record remains unchanged.
- No automation settings were saved and no Blogger write was made.

## Files

- `apps/dashboard/app/operations/automation/controls.tsx`
- `apps/dashboard/e2e/P5-CODEX-106-controls.spec.ts`
- `docs/development/P5-CODEX-153.md`

## Validation

- Focused Playwright regression: **2 passed** (desktop and mobile), covering both `changed_fields` and legacy `changes` payloads with no page errors.
- Dashboard ESLint: passed.
- Dashboard TypeScript typecheck: passed.
- Isolated Next.js production build: passed.
- `git diff --check`: passed.
- The first Playwright invocation could not connect because the configured isolated test port 13100 was stopped; rerunning against the isolated local test server passed.
- `scripts/apply-verified-changes.ps1 -Apply -Confirm:$false` passed Dashboard lint, typecheck, and isolated production build; the managed Dashboard stopped gracefully and restarted on port 3100 with applied commit `8ec83ef6931801ce2bec7a6da7ec2d0c1283eab2`.
- Live production-browser check at `http://127.0.0.1:3100/operations/automation`: the page rendered, the latest audit row displayed all five `changed_fields`, and the generic error page was absent. API request returned HTTP 200. No JavaScript page error occurred. Console still reports the unrelated missing `/favicon.ico` (404) and CSS preload warnings.
- No paid API or Blogger write was used by this fix.

## Audit and release

- The API snapshot and browser request were read-only. No database settings or audit rows were modified. A generic agent-work audit append endpoint is not available; a direct DB insert was rejected by the tool safety review, so the PostgreSQL `agent.work.started/completed` events were not recorded.
- Code commit: `a66ef4a9a1677d9032282b7fcae9cce7bde0d791`.
- Initial documentation commit: `8ec83ef6931801ce2bec7a6da7ec2d0c1283eab2`; final evidence update is recorded in the follow-up documentation commit in Git history.
- Push/PR status: pushed to `origin/develop` at `d7876bba3115b091ed32bd8d758f23a7417e1b88`; PR [#2](https://github.com/alsruddns/woori-blog-agent/pull/2) is open for review and intentionally not merged.
- Main merge: not requested for this follow-up fix; do not merge to `main` without a new explicit request.

## Remaining

- A missing `/favicon.ico` still returns 404; it did not affect the automation page. CSS preload warnings also remain unrelated to this fix.
- Preserve the currently enabled scheduled-only publication policy; this UI fix does not change its scope or worker settings.
