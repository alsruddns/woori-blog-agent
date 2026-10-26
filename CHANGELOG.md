# Changelog

## Phase 3.8-C2
- Added append-only deterministic re-evaluation of the eight Phase 3.8-C1 outcomes, preserving the original content versions and recording one prior schema failure as not replayable because its raw output had not been retained.
- Added bounded structured-output retry (one new seed only for JSON/schema errors), immutable capped parse-failure artifacts, stronger internal-ID/script/keyword checks, and regression coverage for prior false positives.

## Phase 3.8-C1
- Added a zero-cost SEC EDGAR submissions/XBRL collector alongside the bounded Federal Reserve collector, with filing-linked facts, exact retrieval timestamps, source policy metadata and append-only completed-article evaluations.
- Added local Qwen full-article evaluation for active language profiles, separate source-grounding/SEO checks, saved localized versions and dashboard previews. All articles require human review; publication remains disabled.

## Unreleased - Phase 3.8-B - 2026-10-26

- Add immutable source-span fact records, reviewed source-language attribution, and fail-closed BCP 47 localization checks for names, numbers, dates, citations, repetition, and URLs.
- Add glossary approval provenance and append-only glossary revisions; historical terms are backfilled as unapproved.
- Add local-only excerpt translation with bounded JSON output, evidence-only draft composition, durable localization evaluations, and `/research` comparison/history views.
- Evaluate the saved Federal Reserve source: English exact-span rendering passed mechanical checks (0 AI calls); Korean remained held because the local engine was unavailable. No improvement is claimed; zh-CN/ja expansion is deferred.
- Keep semantic accuracy and naturalness for human review, `publish_ready=false`, and all Blogger writes disabled.
- Append a new source-review language attribution instead of changing historical source metadata; preserve existing unapproved glossary terms as their first immutable revisions.
- Run an evaluation-only Qwen3 4B Q4_K_M Vulkan comparison on two Federal Reserve fact spans across en/ko/zh-CN/ja; preserve entity names, normalize inherited-year dates, and keep all candidates held for human semantic review.

## Unreleased - Phase 3.8-A - 2026-10-26

- Re-evaluate Phase 3.7 saved drafts immutably and separate deterministic false positives from actual repetition, missing localization, and unsupported meaning.
- Correct Markdown section-number, localized-date, cited-heading, citation-marker repetition, and possessive-name validation regressions without relaxing unsupported-claim checks.
- Add append-only A/B evaluation history and a deterministic evidence-first template; display real comparison and failure counts on `/research`.
- Compare the same Federal Reserve source in English and Korean; English template passes mechanical checks, Korean remains held for untranslated source text. Human review and publishing remain disabled.

## Unreleased - Phase 3.7 - 2026-10-26

- Persist independently auditable source, evidence, outline, per-section generation/localization, claim, SEO, and draft-persistence stages.
- Use stable evidence sentence IDs, exact source-span extraction checks, section-scoped evidence, bounded retry, and keep failed versions quality-held.
- Add live database stage/coverage views and expand regression tests for unsupported names, headings, recovery, and stage metrics.
- Run a real Qwen3 4B Q4_K_M Vulkan evaluation on the same Federal Reserve source across four DB languages; all four versions remain quality-held.
- Document source availability and licensing review; no new source integration or Blogger writes were enabled.


## Unreleased - Phase 3.6 - 2026-10-26

- Add source-linked evidence facts, citation markers and stricter rule checks for sourced names, numbers, URLs, language fields, citations and repeated paragraphs.
- Pin public Qwen3 4B/8B Q4_K_M downloads by immutable revision and SHA-256; add memory admission and avoid overwriting an existing local inference engine.
- Add same-material, same-prompt model/language measurement comparison in the research dashboard; retain quality-held and publishing-off safeguards.
- Record model measurements and human-review limitations as internal evaluation only.

## Unreleased - Phase 3.5 - 2026-10-26

- Install and checksum project-local official CPU llama.cpp and Qwen GGUF models; preserve all system and other-project settings.
- Measure actual inference for two models and active DB languages, including failures and resource samples.
- Collect bounded Fed public-domain release evidence and Wikidata CC0 topic metadata with durable jobs and immutable source revisions.
- Add cancellable SSE local inference, explicit quality-held evaluation jobs, grounding/metadata diagnostics and append-only revalidation.
- Store four actual-model drafts against collected evidence; keep semantic/translation quality unapproved and all publishing disabled.
- Restore UTF-8 Korean research UI/rules and expose live collection, model, benchmark, provenance and quality results.

## Unreleased - Phase 3 - 2026-10-26

- Add evidence-reviewed keyword research, immutable sources/reviews, versioned prompts and per-profile AI policies.
- Add closed Mock/CPU-local providers, N-language draft orchestration, provenance and internal quality holds.
- Extend the durable Worker with fenced retries, partial-result recovery, resource admission and scheduled dispatch.
- Add Korean research management UI, real proxy/Worker Mock E2E and regression coverage; preserve production write/paid AI blocks.
- Document sources, costs, local hardware limits and remaining human/model validation.

## Unreleased - Phase 2 - 2026-10-26

- Verify live readonly OAuth and all four configured Blogger IDs, account membership, URLs and empty post lists.
- Fix Google HTTP 400 caused by sending an empty first-page token; normalize omitted post items to an empty list.
- Add authenticated account-blog discovery with account-scoped audit/quota and refresh successful read timestamps.
- Expand live verification with bounded pagination, per-blog failures and immutable verification events (P2-003).
- Add readonly Google OAuth, encrypted tokens, refresh/revocation, browser-bound state and PKCE.
- Add Blogger GET/ID/post verification, safe API audit/errors, language quotas and Korean management UI.
- Add Mock-only mutation protocols with durable duplicate/uncertain-write blocking and local content versions.
- Move Dashboard/API to 3100/8100 and matching OAuth callback; keep PostgreSQL 5432.
- Verify isolated restore, register/test Worker and daily backup, and display local storage/backup warnings.
- Resolve deprecated TestClient httpx usage with httpx2. Keep paid AI and production writes blocked.

## 0.1.0 - 2026-10-26
- Establish main/develop policy and ten mandatory Codex rules.
- Add local Next.js dashboard, authenticated FastAPI API and durable diagnostic worker.
- Add isolated PostgreSQL schema, immutable audit and content versions.
- Block AI calls and Blogger publishing; add tests and operational documentation.

## Unreleased - multilingual extension - 2026-10-26
- Replace four-language runtime lists with BCP 47 language registration and country profiles.
- Register provided Blogspot URLs without inventing Google Blog IDs or making Blogger requests.
- Add normalized localizations, publishing/SEO/metrics schemas, reference guards and configuration audit triggers.
- Add local configuration UI/API, category/glossary/schedule settings and fail-closed readiness reporting.
- Preserve legacy content/audit history and summary language-code response compatibility.
## [Unreleased] - 2026-10-26
### Added
- Enforced a zero additional cost policy through a shared outbound provider allowlist, billing-credential tripwire, request audit metadata, and hard stop on provider quota responses.
- Added administrator visibility for cost policy status and credential variable names, plus reviewed provider cost/usage/license records.
### Changed
- Blogger read requests now stop immediately on 429 or quota exhaustion instead of retrying.
- Blogger API reads remain blocked until the Google Cloud project's account-side billing status is manually verified at zero cost.
# Phase 3.8-C3 (implementation; live evaluation incomplete)

- Added an append-only fact registry stage and per-fact local translation with application-rendered citations and article structure.
- Added a fixed evaluation-only Qwen3 4B model override that preserves saved settings, uses existing daily limits, and remains behind resource and publication gates.


## Unreleased - Phase 3.9 operations
- Add an audited PostgreSQL heartbeat for the internal research worker and expose freshness, database-backed job/content/evaluation/failure summaries in the research dashboard.
- Add an append-only deterministic Phase 3.9 recheck of saved article evaluations; no model or external calls are made by that evaluator.

## Unreleased - Phase 3.9-R - 2026-10-26
- Preflight the full bounded Fed/SEC evaluation batch against per-language daily generation capacity before loading the local model or enqueueing any job; preserve the existing quota and resource gates.
- Diagnose the shared evaluation/operations quota, idle Vulkan model memory use, live service health, and Worker/queue state in an append-only preflight artifact. Actual inference and real Worker execution remain unverified because quota capacity was exhausted and no isolated Worker runtime was available.
