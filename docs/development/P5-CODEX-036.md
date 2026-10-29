# P5-CODEX-036 — Google Trends RSS volume and hourly collection

## Work record

- Work ID: `P5-CODEX-036`
- Work time: 2026-10-29 15:25–15:54 KST
- Branch: `develop`
- Reason: RSS traffic labels were stored only as strings, the scheduler was not anchored to KST hour boundaries, and the Trends view exposed raw observations instead of lifecycle and research status.
- Previous state: schema 50; `source_volume_label` existed, but no parsed lower-bound or period column; collection was due per-region at an hour interval rather than a durable top-of-hour sweep. RSS sequence was already not stored as rank.
- Result: schema 51 adds nullable bucket lower-bound and period fields. The scheduler starts a KST hourly sweep in the first five minutes of the hour and advances one region per safe five-minute slot. A shared PostgreSQL gate now enforces the five-minute spacing and 12-call rolling-hour cap across processes and direct callers. The existing worker topic/candidate path is retained.

## Findings

- The operating DB was `woori_blog_agent`, accessed read-only as `woori_app` for diagnostics. Before the migration it contained 610 observations across all 11 regions in the last 24 hours: AU 30, CA 30, GB 30, HK 80, IN 30, JP 80, KR 80, PH 30, SG 80, TW 70, US 70. All were successful run records in that window.
- Stored RSS `ht:approx_traffic` labels included `100+`, `200+`, `500+`, `1,000+`, `2,000+`, `5,000+`, `10,000+`, and `20,000+`. They are bucketed Google estimates, not exact searches or RSS ranks.
- The current 300-row unique-query read model reported 238 new and 62 continuing observations. All 300 showed research status `not_researched`; the existing DB has 494 topic groups, 610 memberships, one Research Package, and one linked topic source.
- The most recent existing candidate-selection audit (15:01 KST) recorded 8 eligible issues, 4 selected for official research, and `official_research_executed=false`, `generation_provider_connected=false`. The Research Worker already calls topic building and bounded candidate selection after a successful RSS collection; no generation provider or automatic official-source execution was added.
- Official Google Trends Help describes volume as bucketed for the selected time window, says data refreshes on average every ten minutes, and lists UI windows of 4, 24, 48 hours, and 7 days. It does not document an RSS `hours=1` parameter. Three real read-only RSS requests were made through the shared outbound gate: default KR returned 10 items (SHA-256 `922930dd…296a5e`); `hours=1` returned 10 items (SHA-256 `19685c88…43acd4`); a subsequent default KR request 18 seconds later returned the same SHA-256 as the `hours=1` response. The earlier response differed. Equal responses alone do not establish parameter support, and changed responses can reflect refreshed feed data. `hours=1` is not allowlisted or used in scheduled collection.
- The comparison had an interval variance: the last two diagnostic requests were 18 seconds apart, below the collector's five-minute policy. The shared external gate has since been strengthened to enforce that interval durably across every caller/process; no more diagnostic RSS requests were made in this task.

## Implementation

- `parse_approx_traffic` recognizes integer buckets such as `1,000+` and abbreviated `1.2K+`; it preserves the source string and writes only the recognized lower bound. Unrecognized or missing strings remain `NULL`. The RSS period remains `NULL` because it is not established by the source.
- Migration `051_trend_approx_traffic.sql` added nullable `source_volume_lower_bound` and `source_volume_period` fields. Historical observations were not updated; the read model can derive a display-only lower bound from the immutable raw label.
- The KST scheduler uses persisted `trend_collection_attempts` and run statuses to resume after restart, skip regions already attempted during the current hourly bucket, retry only transient regional failures once, stop on provider quota/policy errors, and keep the extra retry within the 12-call durable cap. If the top-of-hour start window is missed, it waits for the next hour. Requests remain sequential with five-minute spacing.
- The shared external gate atomically reserves Google Trends calls in append-only audit history, limits all callers to 12 per rolling hour, and applies a cross-process five-minute minimum interval. The collector attempt ledger remains an additional gate. External audit payloads contain metadata only.
- The existing research state now exposes the latest observation per normalized query and region, first/last observation time, new/continuing/reappeared status (reappearance after a 24-hour gap), bucket comparison state, and latest Research Package status. Traffic changes stay incomparable unless source, period, and parsed buckets match.
- The existing research Dashboard now lists the 11 regions and renders the useful observation fields instead of raw observation JSON. It displays that heartbeat does not prove which worker revision is loaded.
- `hours=1` is rejected by the runtime outbound allowlist. Scheduled RSS requests continue to use only `geo`.

## Database and data preservation

- A project backup was created and its archive catalog validated before migration: `backups/20261029T064022Z.dump`.
- `scripts/migrate.py` applied schema 51 to `woori_blog_agent`; the migration event was inserted by the SQL migration. Schema and nullable columns were verified with the migration role. The historical observation count remained 610.
- `scripts/provision-test-database.py` applied schema 51 to the dedicated `woori_blog_agent_test` database and verified that the test app role cannot connect to `woori_blog_agent`.
- No OAuth, manuscript, source, Research Package, or historical observation row was modified or deleted.

## Changed files

- `services/api/woori/trends.py`
- `services/api/woori/external_policy.py`
- `services/api/woori/research_routes.py`
- `services/api/tests/test_trends.py`
- `apps/dashboard/app/research/research.tsx`
- `scripts/051_trend_approx_traffic.sql`
- `scripts/migrate.py`
- `scripts/provision-test-database.py`
- `scripts/verify-worker-isolated.py`
- `docs/operations/zero-cost-policy.md`
- `docs/development/P5-CODEX-036.md`

## Verification

- `pytest services/api/tests/test_trends.py services/api/tests/test_dashboard_read_models.py services/api/tests/test_migration_runner_guard.py -q`: 31 passed against the isolated test DB.
- Ruff: passed on all changed Python files.
- Mypy: passed on `trends.py`, `external_policy.py`, and `research_routes.py`.
- `npm run lint`: passed.
- `npm run typecheck`: passed.
- `scripts/migrate.py`: schema 51 verified.
- `scripts/provision-test-database.py`: test DB schema 51 and operations DB connection denial verified.
- `git diff --check`: passed.
- No real RSS collection job was inserted by the diagnostic probes; the three external calls were recorded as metadata-only outbound audit events. No Blogger write was made.
- The existing API/Dashboard/Research Worker processes were not restarted or stopped. The new scheduler and Dashboard code are implemented but runtime adoption by those processes is not verified. Worker heartbeat freshness alone does not identify the loaded revision.

## Commit, related policy, and remaining work

- Related policy: `docs/operations/zero-cost-policy.md`.
- Commit SHA: `f384645b98bdf71004a686a05c3b7cfc0b642aa7`.
- Remote push: `origin/develop` succeeded.
- Remaining: restart the project Research Worker and API/Dashboard through their owning terminals to load the new revision; confirm a real scheduled sweep and updated Dashboard read model. `hours=1` remains undocumented and unsupported. Existing research candidates require official-source work; this task does not create an automatic writer. No unattended AI generation provider is attached.
