# P5-TREND-001 — Trend discovery baseline and pipeline readiness

- Work ID: P5-TREND-001
- Date: 2026-10-27 Asia/Seoul
- Branch: `develop`; starting commit `28a20f6`.
- Goal: inspect existing pipeline and latest Blogger test drafts, add a bounded real trend source without rebuilding existing research/generation, and determine whether current evidence and quality gates support an end-to-end article.

## Initial inspection

- Existing pipeline: Federal Reserve RSS, SEC EDGAR submissions/XBRL, and Wikidata. Schedules were disabled for all three at inspection time; the last Fed and SEC collections were 2026-10-26. Qwen3 local generation, immutable versions, evidence stages, and the existing review/publication gates were retained.
- Operations DB identity was `woori_blog_agent` via the application role. Read-only before/after checks showed 360 content versions, 1,421 audit events, four Blogger test-write records, zero `publish_ready=true`, and schema 34. Migrations 035–036 were not applied to the operations DB.
- Historical quality table contained 41 evaluations: 27 `quality_held`, 13 `failed`, and one `machine_passed_review_required`; zero were publish-ready. No new AI inference ran in this work.
- Four existing real Blogger private test drafts were rechecked from stored results and left untouched: ko Blog 3321654108096579717 / Post 3147869148049076326; en 5240203250707821039 / 6200412717175382056; zh-CN 1931836538202286191 / 2489135230154436472; ja 7562596540375659150 / 3922184436060234592. These are connection tests, not information articles.
- A first live RSS response was parsed but its persistence transaction failed because `audit_events.run_id` references queued jobs. The outbound start/completion metadata was retained in the isolated test DB; no observation row was committed. The audit linkage was fixed before the successful run.

## Implementation

- Added the allowlisted Google Trends Trending Now RSS read path for the fixed geographies KR, US, JP, TW, HK and SG, routed through `woori.external_policy.client`. There is no arbitrary URL or HTML crawler path. Per-process cap: one call/minute; durable append-only cap: 12 attempts per rolling hour; response cap: 1 MiB/20 seconds; 429/quota is a hard stop with no retry or provider fallback.
- Added additive migrations 035–036 for append-only trend attempts, runs, and observations. The data is separate from `research_sources` because search trend signals are not factual evidence. The RSS item sequence is not a documented rank, so rank is stored as NULL; related terms stay empty if absent; source update time stays NULL if absent. Source traffic labels remain strings and are not transformed into search-volume counts.
- Added authenticated `/admin/research/trends` and `/admin/research/trends/collect` endpoints and real run/observation data in `/research`. The Dashboard collection controls are disabled until the trend schema exists in the connected DB. Automatic collection remains off.
- Kept the existing Qwen3 local provider. Gemini was not enabled or called: the official free tier is model/project-specific, account eligibility can vary, free-tier data handling differs, and paid use requires billing linkage; this project has not verified its project-level eligibility/billing state.
- Topic scoring/grouping, general discovery of multiple factual sources per trend, article generation/localization for a selected trend, and new-content Blogger draft submission are not implemented in this change. The live sample included broad or unrelated terms, and the trend feed itself cannot establish article facts. Existing quality gates and Blogger write restrictions remain intact.

## Real collection and DB isolation

- Actual calls: two Google Trends RSS GETs for KR. The first parsed response was not committed due to the audited-run FK issue above. The second succeeded and returned 10 items; successful run ID `8798ceef-1a17-4f4c-9b8a-c31847c6856b`, response SHA-256 `de7b5b564d1d1854e0c2a2e5305e01248dbff195955966c623e1c1dfaceb9def`, observed elapsed time 1,473 ms. This is one successful live collection, not 20 ranked terms. `source_rank` and `source_updated_at` were NULL; no related-term values were provided.
- The successful run, 10 observations, one durable attempt and two `trend.collection.*` audit events are in `woori_blog_agent_test` only. Migration 035–036 were applied to that isolated DB using the existing provisioning script; the test app role was again verified unable to connect to the operations DB. The operations database remained schema 34, with counts still 360 versions/1,421 audits/four Blogger test records/zero publish-ready evaluations.
- No Blogger API was called in this work. No paid AI or data API was called. The existing Blogger exception was not widened. No content version was created or modified by the trend collector.

## Source and provider findings

- Google Trends Help documents RSS export and country/region selection; the Trends API remains limited-access alpha. This RSS representation supplied traffic buckets but no explicit rank in the observed response.
- Naver DataLab Search Trend requires caller-supplied topic groups and returns relative time-series ratios; its published daily cap is 1,000. It is not a general search-term top list and is not configured here. Daum/Nate official discovery feeds/APIs remain unverified; HTML crawling stays disabled.
- The Korea Tourism Organization's public Tourism Information Service is documented as free and real-time, with 1,000-call development quota and production approval. It is a factual information candidate, not a trend source; API credentials, production approval and per-field/image rights are not configured, so no request was made.
- Gemini's documented free tier was not treated as a guarantee of this project's zero-cost eligibility. Qwen3 local remains the active route; there were zero new AI calls.

## Changed files

- `services/api/woori/external_policy.py`
- `services/api/woori/trends.py`
- `services/api/woori/research_routes.py`
- `services/api/tests/test_trends.py`
- `scripts/035_trend_observations.sql`
- `scripts/036_trend_call_quota.sql`
- `scripts/migrate.py`
- `scripts/provision-test-database.py`
- `apps/dashboard/app/research/research.tsx`
- `docs/architecture/live-research.md`
- `docs/operations/research-sources.md`
- `docs/operations/zero-cost-policy.md`
- `README.md`
- `CHANGELOG.md`
- `docs/development/P5-TREND-001.md`
- `docs/development/P5-TREND-results.json`

## Validation

- `scripts/provision-test-database.py`: passed; isolated test DB schema 36 and test-role denial to operations DB verified.
- `scripts/verify.ps1`: passed: Ruff, mypy (30 source files), 211 pytest tests, isolated wheel build, Dashboard ESLint, production build, TypeScript typecheck, and `git diff --check`.
- `scripts/verify-secrets.py`: passed secret exclusion, staged content/history and HTTP scan; publication flags stayed disabled.
- Additional tests cover RSS field fidelity, source-rank non-inference, geo/path/method allowlist, unsafe/oversized XML rejection, route-to-DB persistence in isolated test DB, audit linkage, and append-only update rejection.
- Actual AI generation/localization: not run. Blogger writes in this phase: zero. Production DB migrations: not run. `publish_ready=true`: zero.

## Remaining work

1. Apply migrations 035–036 only through the reviewed operations backup/restore/migration procedure; controls remain disabled until then.
2. Verify external use terms for monetized trend-signal display/reuse before using the signal in public article copy.
3. Configure and review a permitted official discovery/source provider for other areas; Naver requires project registration and returns relative series, while Daum/Nate official feeds remain unverified.
4. Add deduplicated topic grouping, explicit editorial topic selection, and multiple reviewed topical fact sources. The broad live term `관광` is insufficient evidence for an expert travel article.
5. Continue using Qwen3 only behind existing quality gates; no trend-derived article passed the pipeline, and no new article exists.
6. New Blogger drafts require a separate exact-content/target approval; the four existing private test drafts are retained as-is.

- Costs: no added service cost; two public RSS GETs only.
- Blogger: no API requests or writes.
- Commit/push: to be recorded after this phase commit.
