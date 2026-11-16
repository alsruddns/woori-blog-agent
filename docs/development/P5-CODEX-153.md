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
- The first Playwright invocation could not connect because the configured isolated test port 13100 was stopped; rerunning against the isolated local test server passed. The production bundle was built but its isolated `next start` smoke could not be launched by the command safety review; production UI verification remains pending until managed Dashboard restart.
- No paid API or Blogger write was used by this fix.

## Audit and release

- The API snapshot and browser request were read-only. No database settings or audit rows were modified. A generic agent-work audit append endpoint is not available; a direct DB insert was rejected by the tool safety review, so the PostgreSQL `agent.work.started/completed` events were not recorded.
- Code commit: `a66ef4a9a1677d9032282b7fcae9cce7bde0d791`.
- Documentation commit: follows this record in Git history.
- Push/PR status: pending.
- Main merge/deployment: not requested for this follow-up fix; do not merge to `main` without a new explicit request.

## Remaining

- Apply the verified Dashboard build through the managed restart path and confirm `/operations/automation` renders against the live local response with no console error.
- Preserve the currently enabled scheduled-only publication policy; this UI fix does not change its scope or worker settings.
