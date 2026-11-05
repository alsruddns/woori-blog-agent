# P5-CODEX-148 Review List Discard and Trends Volume Column

## Work record

- Work date: 2026-11-05 KST
- Branch: develop
- Start HEAD and origin/develop: `742596f9c0d29ca5747caf3a35295fe6f787d373`
- Append-only start audit: `agent.work.started`, ID `376290`
- Operations schema/settings revision: 92 / 23

## Root cause and data action

The two previously identified versions (`9b023ae4-b4a2-4d34-9f0b-d33ce96f483f` and `86cae11d-f851-40e1-b8cb-a073e45f1d5a`) were already recorded as discarded and appeared in the discarded archive. A separate later import, `f2db024d-a146-458f-a179-96edf9638262`, created a new version, `73c08d7d-7814-4971-988b-1315b63a6047`, with the same title in a different content group. That is why a matching title remained in Review.

A read-only dry run confirmed the exact current version, group, import, and EN Blogger target. It had zero verified LIVE records, zero publishing jobs, and no discard record. The exact row backup and checksum manifest were saved under `.runtime/p148-target-backup.json` and `.runtime/p148-dry-run-manifest.json`. Backup SHA-256: `34d7367cc1d997f54a552d9e8739c1edd2e04df1419ed2f11fffa9c66522e6ec`; body SHA-256: `853a3cc763acb3f5fa065172f8c2d04c23ffa7aee2c482379293ab28ba87bdaf`.

Using the existing `/admin/publications/discards` management path, only the new version was reversibly discarded. No physical content/import deletion was performed. The API returned one success and zero failures. Read-back confirmed the exact version is absent from Review and present in Discarded. The earlier two versions remain discarded. The append-only `publication.manuscripts.discarded` audit event is ID `376308`. There are 13 matching-title entries in the discarded archive; historical entries were preserved. Blogger writes: zero.

## UI change

Moved Google Trends' original search-volume label out of the title subtitle and into a dedicated `Google Trends search volume` grid column. Original bucket labels such as `10K+` are shown unchanged with a note that they are not exact search counts. Search query and country remain under the title. Mobile layout shows the volume column label within the cell. Non-Trends rows show an em dash.

## Validation

- `services/api/tests/test_publications.py`: 53 passed.
- Dashboard lint: passed.
- Dashboard typecheck: passed.
- Playwright regression `P5-CODEX-148-trends-volume-column.spec.ts`: 2 passed across desktop and mobile. Verified dedicated column, original `10K+` label, non-exact-count note, mobile label, and separation from the title cell.
- Browser smoke on the real Dashboard review list confirmed the current Trends row displays its source label in the separate column.
- Read-only publication API checks showed rows with original volume labels in Review (2), Published (28), Held (1), and Auto Failure (5).
- The first Playwright attempt used `route.fetch()` from a browser request and got HTTP 403 from the local API proxy. This was a test-fixture issue, not an API or database failure. The test now supplies an isolated response fixture and passes both viewports.
- No Blogger POST/PATCH/DELETE operations occurred.

## Files changed

- `apps/dashboard/app/publishing/publication-manager.tsx`
- `apps/dashboard/app/style.css`
- `apps/dashboard/e2e/P5-CODEX-148-trends-volume-column.spec.ts`
- `docs/development/P5-CODEX-148.md`

## Operations reflection

- Feature commit `9a5f60916ee2d5446b98ccba53c443c5dc06cede` was pushed to `origin/develop`.
- `scripts/apply-verified-changes.ps1 -Apply -Confirm:$false` passed Dashboard lint, typecheck, and production build and updated the validated source marker to that commit.
- Dashboard was the only affected service, so the official reflection script restarted Dashboard only. Dashboard returned HTTP 200 and runs the new commit. API and both Workers were unchanged and remained on runtime commit `94cf2032eb2ccf6b35b3d0104747d5ed3e6c58a0`.
- Both real-data browser smoke and isolated desktop/mobile E2E passed. Manuscript, import, audit, and publication history remain preserved.
- No remaining work for this request.

## Commits

- Feature/UI commit: `9a5f60916ee2d5446b98ccba53c443c5dc06cede`.
- Follow-up test and operations record commit: see `git log -- docs/development/P5-CODEX-148.md`.
