# Changelog

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
