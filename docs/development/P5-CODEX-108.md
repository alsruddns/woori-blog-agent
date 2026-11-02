# P5-CODEX-108 - Shared Blogger Queue and 30-Minute Global Interval

- Work date: 2026-11-03 KST; resumed after usage-limit interruption.
- Branch: `develop`
- Starting HEAD: `856ddf9069fbe7609de9e0b54b74822e7996d954`
- Preserved stash: `stash@{0}` (inspected, not applied or removed).
- Implementation commit: `5d07e16e625964df6b39f06d4b3bc53a2c1c23fa`.

## Problem and change

The previous Blogger write paths retained separate 2-minute account and 5-minute blog spacing. LIVE publication could create a Draft first and later publish it, making the requested mode and actual Blogger result easy to confuse. Google Trends also had a pending 30-minute cadence while the effective value was 60 minutes.

Migration 081 independently sets the Trends collection cadence to 30 minutes and introduces `automation_controls.global_publish_min_interval_minutes`, default 30 with a lower bound of 30. The value is read from PostgreSQL on every write gate. Manual Draft/LIVE, Trends, and scheduled Blogger writes share a single database advisory lock and a durable time anchor based on authorized Blogger write-start audit events. A failure to read the interval or history blocks the write. Existing queued items therefore use the current interval when they reach the write gate; completed publication records and jobs are unchanged.

The shared publishing job lanes preserve manual FIFO priority, followed by automatic candidates ordered EN, KO, JA, ZH. New LIVE writes use Blogger `isDraft=false`; success requires read-back of the same post ID, target blog, LIVE status, title/content, public URL, and timestamp. Past failed/queued jobs are not bulk-replayed.

Trends collection and Blogger publication intervals are separate settings. Trends defaults to 30 minutes; Blogger writes have a minimum of 30 minutes. A 30-minute interval is an application control, not a Google quota guarantee.

## Operations and protected state

- API, Dashboard, Research Worker, and Publication Worker were healthy at inspection. Existing worker processes were stopped only through the project graceful stop scripts after completing their current work cycle; no process was force-killed.
- Operations DB started at schema 80 and automation controls revision 12. Trends was enabled with 60 minutes effective and 30 minutes pending. The existing 15 scheduled automations and prior publication records/jobs were preserved.
- Backup `backups/20261102T160010Z.dump` was created and its `pg_restore --list` catalog validated. Migration 081 was then applied. Operations schema is 81, settings revision 13, Trends interval is 30 with no pending transition, and the global Blogger interval is 30.
- Final operational switches remain: Trends collection ON; Codex authoring ON; global automatic publishing ON; Trends auto publication OFF; scheduled auto publication ON; manual publishing ON; emergency stop OFF. Draft/LIVE policy remains LIVE for scheduled publishing.
- Trends auto publication remains OFF because the required append-only Trends public-write authorization and separate external public-write approval are absent. No approval record was fabricated. Existing zero-cost/public-write gates were not bypassed.
- Blogger API write calls during this work: 0. No test Blogger post was created.

## Changed files

- `scripts/081_trends_and_global_publish_intervals.sql`, `scripts/migrate.py`, `scripts/provision-test-database.py`
- `services/api/woori/blogger_writes.py`, `automation_controls.py`, `automation_auto.py`, `publication_worker.py`, `publications.py`, `publication_monitor.py`
- Dashboard automation controls, publication manager/worker panel, Trends settings, and existing E2E fixtures
- API tests for interval enforcement, LIVE read-back, publishing lanes, and Trends
- `docs/operations/zero-cost-policy.md`, `docs/operations/research-sources.md`

## Verification

- Isolated test database reached schema 81; production migration 081 applied after backup.
- Changed API test files: 128 passed.
- Ruff: passed. Mypy: passed for six changed API modules. Dashboard lint and typecheck: passed. Python wheel build: passed. Isolated Dashboard production build: passed.
- Playwright controls E2E at 1440px and 390px: 14/14 passed.
- Live Dashboard browser check at 1440px and 390px: page and automation-controls proxy returned HTTP 200; both 30-minute values rendered; no horizontal overflow and no page errors.
- `scripts/apply-verified-changes.ps1 -Apply -Confirm:$false` safely reflected the implementation commit to API, Dashboard, Research Worker, and Publication Worker. API and Dashboard health returned HTTP 200; both Worker heartbeats are fresh.
- API settings revision 13; Research Worker applied revision 13; Publication Worker applied revision 13. Dashboard showed revision 13 and both Worker acknowledgements at revision 13.
- The 01:00 KST Trends collection completed at 01:00:28 after migration. The next 01:30 slot had not arrived before this verification ended, so a second post-change round is not verified.
- Actual Blogger LIVE success is unverified: no qualifying new scheduled job was available and the external public-write gate remains fail-closed. The current worker reports no queued/due live jobs.

## Remaining items

- Observe the 01:30 KST Trends slot to verify a second post-change collection round.
- Trends automatic LIVE remains unactivated until its required publication authorization and external write approval exist.
- A new qualifying scheduled LIVE publication remains unverified; no real write was attempted.
- The implementation commit is above. The final documentation-only follow-up commit is discoverable with `git log -- docs/development/P5-CODEX-108.md`.
