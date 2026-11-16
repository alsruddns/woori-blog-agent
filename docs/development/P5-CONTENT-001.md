# P5-CONTENT-001 ? Trend research and evidence-package pipeline

Date: 2026-10-27
Branch: `develop`

## Purpose and baseline

Extend the existing Google Trends RSS collector into conservative topic candidates, a configurable editorial rubric, source linking, and a fact-grounded Research Package. Reused migrations 035?036, shared external-call policy, the `/research` page, and the existing reviewed-source/evidence-fact pipeline. No operations database migration or write was performed. The isolated `woori_blog_agent_test` database was provisioned and advanced through migration 039; its dedicated `woori_test_app` identity was confirmed and denied CONNECT to the operations database. Existing untracked `.playwright-mcp/` was preserved.

## Implementation

- Migration 037 adds immutable topic/query clusters, cross-region grouping proposals, a versioned scoring rubric, append-only assessments/editorial decisions/source links/independence reviews, and immutable research-package snapshots. Exact normalized queries cluster only inside the same geography and are explicitly not confirmed as the same event. Cross-geography exact/fuzzy overlaps create review proposals and never auto-merge.
- Migration 038 adds nullable `http_status` for newly collected RSS runs; it deliberately does not backfill historical runs whose response code was not retained.
- Migration 039 adds append-only human decisions (`same_event`, `different_event`, `insufficient_information`) and requires an event-group UUID only for `same_event`. The dashboard shows both observations, confidence/rationale, prior decision, and the review form.
- The initial rubric weights raw source-interest-label presence, freshness, query specificity, reviewed source coverage, independently reviewed source groups, and deduplication risk. The traffic label is never parsed as numeric volume. Broad terms, no current reviewed source, fewer than three verified facts, fewer than two human-confirmed independent-source groups, and unresolved event proposals remain held. Reader value, analysis suitability, and rights remain human review. Weights/thresholds are stored with rationale in the database; score is triage, not publication approval.
- A package can only reference existing current reviewed `research_sources` and `source_span_verified` `evidence_facts`. It records observations, facts, source metadata, unknowns, conflicts-to-review, prohibited unsupported claims, and a suggested outline. It is append-only, idempotent by payload hash, always requires human review, and has `publish_ready=false`. No arbitrary web search/fetch API was added; existing Fed/SEC/Wikidata source pipelines can be reused only after a topic-specific match and rights/source review.
- `/research` exposes regions, raw observations, candidate grouping and scoring, existing reviewed-source links, source independence decisions, package snapshots, and event-group review. No trend ranking or fabricated source data is displayed.

## Actual regional collection and resulting evidence

Five on-demand, live GETs were made through the existing fixed Google Trends RSS provider, using only the isolated test DB. Each region returned 10 observations through the collector successful HTTP 200 path. No extra regional calls were issued after those five requests. Combined with the prior KR sample retained in the same isolated DB, there are six region runs and 60 observations. Per-region raw queries, timestamps, RSS traffic labels, URLs, and response hashes are in `P5-CONTENT-results.json`. Every observation has `source_rank=null`; RSS item order was not interpreted as ranking. RSS also did not provide a refresh timestamp/query language in the parsed item data.

Historical run rows were created before migration 038 and therefore have `http_status=null`; they were not rewritten or backfilled. The new code stores actual response status and includes it in success/failure audit for future runs. The prior success status proves that the collector accepted its successful response path, but the database does not retain the original HTTP value.

The database now contains 60 immutable query-cluster topics/observation memberships and assessments, all 60 held. There is one cross-region proposal (`same_query_cross_geo`, confidence 0.8); it remains review-only and has no human review. Example candidate: Singapore `israel election`, score 54.15, decision `held`, because no current reviewed facts/source exist and independent corroboration/value review are absent. Its package is `insufficient_evidence` with zero sources and zero facts; the example payload and IDs are in the JSON results. The test DB itself contains zero `research_sources`, so no actual official document was available to attach. The end-to-end article-preparation acceptance criterion is therefore **not achieved**: no topic reached evidence-backed package readiness, and no article/localization/Blogger draft was produced. We did not lower thresholds or fabricate a success.

The raw feed contains a mixture of query languages; RSS did not identify the language, so topics keep `und` rather than infer it. Candidate examples include local/ambiguous phrases and broad terms. Candidate scoring does not make editorial selection.

## Source and provider policy

Google Trends RSS remains an observed-interest signal, not an article fact source. Official Trends Help describes RSS export and country/region selection: https://support.google.com/trends/answer/3076011?hl=en. The Google Trends API is an alpha with limited tester access and was not called: https://developers.google.com/search/apis/trends. Naver DataLab Search Trend requires caller-supplied topic groups and returns relative time-series comparisons rather than a global top-search feed; it is not configured or called: https://developers.naver.com/docs/serviceapi/datalab/search/search.md. Daum/Nate scraping remains disabled. Existing Fed/SEC/Wikidata connectors are not a general web-search service and do not provide a verified source for these particular candidates. RSS commercial reuse terms for monetized content remain subject to source-specific review. No paid data/AI API was used.

## Validation and data safety

- Test database identity: `woori_blog_agent_test` / `woori_test_app`; schema 39. Test app CONNECT denial to the operations database verified.
- Test-only RSS history: six successful region runs; 60 observations; no numeric ranks. No migrations were applied to operations DB.
- Focused suite after the final grouping-review and scoring-config changes: 45 passed (`test_trend_topics.py`, `test_trends.py`, `test_pipeline.py`).
- Complete `scripts/verify.ps1` passed: Ruff, mypy (31 files), 216 pytest tests, isolated wheel, Dashboard ESLint, Next.js production build and TypeScript typecheck, and `git diff --check`. The separate secret/history/HTTP scan passed; the test DB provisioner confirmed schema 39 and denied the test app role access to operations DB. Read-only operations DB inspection showed schema 34, 360 content versions, 1,421 audit events, and no trend-topic tables. The operations DB migration was not run.
- No AI call, Blogger API write, publication, or cost-bearing provider call was made. Existing original data and audit events were not modified; new test records remain isolated in test DB.

## Remaining blockers

1. No source/facts are linked to a trend candidate. A topic-specific source collection/review workflow must obtain actual allowed primary documents and independent verification where needed.
2. RSS language and numeric rank are not supplied; remain unknown/null.
3. The candidate and package require human editorial, source-rights, semantic, and reader-value review.
4. No article generation, four-language localization, or Blogger draft creation was attempted.
5. Operations DB schema remains unchanged; migration 037?039 were applied only to the isolated test DB.
