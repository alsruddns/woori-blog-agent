# P5-CODEX-092 — Trends Auto publication activation

- Work date: 2026-10-31 (Asia/Seoul)
- Branch: `develop`
- Initial HEAD: `a9009fb3b98007abe8fccfa8fe2e44ce49dd8a33`
- Reason: connect the already implemented Trends lane to an explicitly configured automatic publication policy and remove Trends-only application volume ceilings without weakening evidence, rights, duplicate, emergency-stop, or minimum-spacing gates.

## Before

- Operations schema was 68. `trends_publication_policy_events.daily_limit` was required (1–10); the enqueue path enforced it.
- The Publication Worker applied global/language daily and hourly counts to every live lane. `BloggerLivePublisher` separately applied a language hourly count, including Trends.
- Registered country mappings were KR for the Korean blog; AU, CA, GB, IN, PH, SG, US for English; JP for Japanese; the Chinese blog had no mapped geo.
- No Trends policy events or active Trends jobs existed. No `external.blogger.public_publish.approved` event existed. All four `test_publish_verified_at` values were NULL.
- Historical LIVE publishing records exist, but the current explicit publisher verification marker and a fresh per-blog identity check were absent.
- Existing KR/US insufficient-evidence imports and the JP Trends import `b0f2a399-4b6a-4fc3-9181-84040ad87aad` (7 unverified claims) remain ineligible. No new operational article was generated in this change.
- Current runtime policy states no production manuscript-generation provider is attached and generation APIs/schedules fail closed. Blogger Cloud billing association and public-write zero-cost approval remain unverified.

## Changes

- Added schema 69: new Trends policy events may use `daily_limit=NULL` for unlimited volume; old immutable policy rows are preserved.
- The Trends policy API defaults to unlimited. Enqueue skips the daily count cap only for NULL and still holds on missing count data.
- Publication Worker global/language daily and hourly caps are now lane-scoped: they remain for scheduled/manual work and are skipped for `trends_auto` only.
- Blogger write spacing (OAuth connection 2 minutes and blog 5 minutes), remote duplicate check, quality/claim/rights review, policy recheck, and emergency stop remain. The writer's hourly cap is bypassable only through the Trends worker call; normal callers retain the cap.
- Trends policy settings UI now displays unlimited and sends `daily_limit: null`.
- Service reflection classification directs publication modules to the Publication Worker instead of unnecessarily selecting Research Worker.
- Zero-cost policy and development record updated. No CN mapping was created.

## Database and operations

- Created and verified custom-format backup `backups/20261030T172440Z.dump` (6,226,813 bytes); archive catalog validation passed.
- Applied additive migration 069 to the local operations database. `scripts/migrate.py --status` reports `woori_blog_agent`, schema 69.
- Read-only post-migration check: 4 existing blogs; KR/EN/JP mappings unchanged; ZH has no geo; 0 Trends policy events; 0 public-publish approval events; 0 active Trends jobs. No operational policy was activated and no publishing record was added.
- A policy activation attempt was intentionally not made: the required real `test_publish_verified_at`, fresh per-blog Blogger identity verification, explicit public-write approval event, verified Cloud Billing association, and a newly verified eligible Trends article are not all present. No Blogger remote write was made.

## Validation

- Isolated test DB provisioned at schema 69; its app role's effective access to the operations DB remained denied.
- Focused API tests: 82 passed across Trends publication, publication worker, and Blogger live policy suites.
- Ruff and mypy passed for modified API modules and tests.
- Dashboard lint and typecheck passed; the one Production Build passed.
- Operations migration succeeded and schema status verified at 69.
- PowerShell parse and lifecycle Pester: 31 passed, 0 failed.
- Final committed reflection validation: 206 API tests passed; Ruff, mypy, wheel build, Dashboard lint/typecheck/production build passed.
- Runtime reflection restarted API, Dashboard, Research Worker, and Publication Worker because the prior runtime baseline lagged at `bf8f49eb`; all stopped gracefully, no force termination. API `/health` and Dashboard `/research` returned HTTP 200. Publication Worker heartbeat is fresh in `operations-scheduled-auto-and-manual-and-trends`; Research Worker heartbeat is fresh. Applied code commit: `0fd95bcd0b0b618f3f05709acd63500d56b27a0e`.
- Existing P5-CODEX-089 Playwright policy spec passed on the live Dashboard at desktop 1440px and mobile 390px (2/2). The UI reports unlimited volume; policy remains inactive because no policy event exists.
- No actual Trends Publishing Job or Blogger LIVE result was created; operational LIVE verification is not complete.

## Files

- `scripts/069_trends_unlimited_publication.sql`
- `scripts/migrate.py`
- `scripts/provision-test-database.py`
- `scripts/apply-verified-changes.ps1`
- `services/api/woori/publications.py`
- `services/api/woori/trends_publication.py`
- `services/api/woori/publication_worker.py`
- `services/api/woori/blogger_writes.py`
- `services/api/tests/test_trends_publication.py`
- `services/api/tests/test_publications.py`
- `services/api/tests/test_blogger_live_policy.py`
- `apps/dashboard/app/sources/trends-publication-settings.tsx`
- `docs/operations/zero-cost-policy.md`
- `docs/development/P5-CODEX-092.md`

## Remaining

- KR/EN/JP Trends Auto policies are not active. The exact missing prerequisites are non-null `test_publish_verified_at`, a fresh read-only Blogger identity verification, the separate `external.blogger.public_publish.approved` event, verified Blogger Cloud Billing/quota zero-cost status, and a newly generated eligible Trends article. These were not fabricated or bypassed.
- No new eligible Trends article, Publishing Job, Blogger postId, public URL, or remote LIVE check exists for P092.
- Blogger per-post search-description and robots settings remain outside this task; prior API review did not establish supported public-write fields.
- Trends Auto activation and LIVE publication remain unverified; preserve the current fail-closed state until the listed prerequisites are verified.
