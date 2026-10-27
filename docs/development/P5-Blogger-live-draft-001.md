# Blogger-only cost attestation and four-blog private-draft test preparation

- Work ID: P5-BLOGGER-DRAFT-001
- Date: 2026-10-27 (Asia/Seoul)
- Branch: `develop`
- Purpose: record the owner's explicitly authorized Blogger-only cost-policy exception, verify one existing full-scope OAuth grant against the four configured blogs, and prepare exact one-time private-draft previews. No live post insert was issued; the stored payloads still require the user's final per-payload approval.

## Initial state and reason

The provider policy blocked Blogger because price and project billing status had not been independently verified. The project owner then explicitly confirmed in the task that Blogger API use is free for this project and requested removal of the Blogger-only cost block. The other provider cost gates must remain unchanged. Two existing connected OAuth grants had the Blogger write scope; the four blog mappings still referenced the existing read-only connection. No new OAuth grant or mapping change was requested.

## Changes

- Added a fail-closed, append-only Blogger owner-attestation check to the shared provider policy. It reads the latest Blogger approval/revocation event and scopes the exception to Blogger read, a user-confirmed private test draft, and a user-approved existing-post update operation. Other providers continue using their original cost gates.
- Added a narrowly allowlisted draft test path. It accepts only the four configured Blog IDs and exact fixed localized test copy, records a one-time preview and request fingerprint, and requires a fresh all-blog access verification plus the exact final confirmation phrase before the single `posts.insert?isDraft=true` call. A write is marked uncertain before network I/O; an uncertain/failed attempt cannot be replayed automatically.
- Added OAuth writer availability, cost-approval and draft-result status to `/blogger`, and exposed the preview/confirmation routes through the same-origin Dashboard proxy.
- Added regression coverage for provider isolation, operation/path/method boundaries, approval/revocation semantics, exact draft confirmation, and no-network preview idempotency.
- Clarified the cost-policy document: the low-level policy recognizes the bounded update scope, but this change does not expose or execute an existing-post update workflow.

## Actual checks and external activity

- Recorded Blogger-only owner approval event ID `174738`, approval ID `7fc907c7-a0b8-4032-84f2-a86c5c4f2d2b`, at `2026-10-27 21:58:41 KST`. The append-only event contains the before/after state, actor/evidence type, and exact Blogger scope. This is an owner attestation, not independent proof of Google's pricing or Cloud Billing state.
- Selected an already connected writer OAuth grant with exact `https://www.googleapis.com/auth/blogger` scope and encrypted refresh token. The token was refreshed through the existing OAuth flow. No token, client secret, or Google account identity was emitted or inferred. The other writer grant and all existing read mappings were preserved.
- Performed a read-only account blog listing with the selected existing grant. Blogger returned HTTP 200 and the accessible Blog IDs and URLs matched all four registered blogs. Verification event ID `174746` records four accessible blogs and `identity_verified=false`. This does not prove a successful write to each blog.
- Created four local exact-payload previews only. Each is `isDraft=true`, `external_call_made=false`, and is currently `pending`; preview IDs are `58dc89dd-97be-4fa3-a540-2f5784f9a569` (en), `4fddf8fb-a08e-4c25-8826-6c01aba01935` (ja), `cfb86b6c-17d0-4f79-9f18-4e675c12181f` (ko), and `4c2767a1-1063-4c7b-aae9-b8ad1f4e9179` (zh-CN). Exact title/body payloads are persisted in the operations database audit trail and are shown to the user for final approval.
- Actual Blogger requests: one account-list GET succeeded; one OAuth refresh exchange occurred. `posts.insert`, post update, delete, publish and schedule calls: zero. No existing Blogger post was changed.
- Current operations-database snapshot: 360 content versions, 1,332 audit events, zero publication records, four pending live-draft ledger entries. The attestation, read-verification, and previews intentionally append operational audit/write-ledger records; no content version was created or changed by this task.
- Automatic publishing remains disabled; `publish_ready` remains false. No paid AI/data provider was enabled or called.

## Failures and resolution

- The first preview SQL query exposed a psycopg `%` placeholder escaping issue. Escaped the literal LIKE wildcard and verified all four previews are idempotent, local-only, and do not call Google.
- A diagnostic print hit the Windows console's CP949 encoding limit while rendering localized text. Re-ran diagnostics with UTF-8 output; no secret values were printed and no remote write was triggered.
- The live preview test initially had a test expectation mismatch for allowlisted content; updated the regression test to assert the intended exact-copy restriction. The successful test confirms preview-only behavior, not a real write.

## Verification

`scripts/verify.ps1` completed successfully on 2026-10-27:

- Ruff: passed
- mypy: passed (29 source files)
- pytest: 200 passed
- Isolated Python wheel: passed, `woori_blog_agent-0.1.0-py3-none-any.whl`
- Dashboard ESLint: passed
- Dashboard TypeScript/typecheck: passed
- Next.js production build: passed
- `scripts/verify-secrets.py`: passed (staged files, operations/evaluation history, publication flags, and loopback HTTP responses)
- `git diff --check`: passed

No real `posts.insert` has been attempted, so actual Blogger draft creation, returned Post IDs, and Blogger-side read-back remain unverified and require the user's final approval immediately before each approved insert. Failed or ambiguous live requests will not be automatically retried. The approved cost exception does not independently verify Google Cloud Billing settings.

## Files changed

- `services/api/woori/external_policy.py`
- `services/api/woori/blogger_drafts.py`
- `services/api/woori/blogger_routes.py`
- `services/api/woori/google_http.py`
- `services/api/tests/test_blogger_live_policy.py`
- `services/api/tests/test_google.py`
- `apps/dashboard/app/api/blogger/[...path]/route.ts`
- `apps/dashboard/app/blogger/manager.tsx`
- `apps/dashboard/app/blogger/page.tsx`
- `scripts/record_blogger_cost_attestation.py`
- `docs/operations/zero-cost-policy.md`
- `CHANGELOG.md`
- This development record and its results JSON

## Git

Implementation commit `3f4029a58177dd1de78dd348a42c788dbf5a899e` was pushed to `origin/develop`. A final documentation-only commit records this push status. `main` was not changed; no new branch was created.
