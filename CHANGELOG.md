# Changelog

## Dashboard content workspace redesign (2026-10-28)
- Replaced the long research-first landing page with a Korean content operations dashboard and dedicated manuscript, source, model comparison, publishing, automation, and diagnostics navigation; `/research` remains a compatibility route to `/manuscripts`.
- Added bounded, server-paginated manuscript and Google Trends observation read models. Manuscript lists omit article bodies and quality JSON; selecting a row fetches the full article, evidence, checks, and editorial history on demand. The existing review and approval endpoints remain the only write path and their eligibility checks are unchanged.
- Added responsive data grids, keyboard-accessible details, mobile full-screen manuscript sheets, Korean KST date formatting, safe article previews, and folded diagnostics JSON. Model comparison only uses stored results and reports when a provider has no evaluation rows.
- Live read-only checks found 18 manuscripts, 0 stored trend observations, and 36 model evaluation records; the available model records are local Qwen3 variants and no NVIDIA Build result is stored. No operational migration or write, Blogger request, paid call, or AI inference was performed. Browser E2E was not run because the project has no installed Playwright package; no dependency was added.

## Phase 5 trend discovery baseline (2026-10-27)
- Added a fail-closed Google Trends Trending Now RSS collector for KR, US, JP, TW, HK and SG. Collection is manual/on-demand, one request per minute and at most 12 durable attempts per rolling hour; HTTP 429 and policy failures stop without retry or provider fallback.
- Added append-only run, attempt, and observation records with response SHA-256, region, raw query, source-provided traffic label, start/update times when present, source URL, and permanent audit events. Source rank remains NULL because the RSS feed does not explicitly provide a rank field; no ranking is inferred from item order.
- Added `/admin/research/trends` inspection and `/admin/research/trends/collect` plus actual observation/run fields to `/research`. Schema migrations 035–036 are additive; the operations database was not migrated in this change.
- No arbitrary HTML crawling, paid AI/data provider, auto-schedule, generated article, or new Blogger write was executed. Existing Qwen3 remains local-only; professional article generation stays gated on multiple reviewed, topic-relevant factual sources and the existing quality checks.

## Blogger-only cost attestation and private-draft test path (2026-10-27)
- Replaced the static Blogger cost block with an append-only owner-attestation event lookup scoped only to Blogger; every other provider cost gate remains unchanged and global billing-credential/terms/quota checks still apply.
- Added a fixed-payload, one-per-target, two-step live private-draft flow. A local preview binds the exact language, Blog ID, title, body, and `isDraft=true`; the final operator confirmation is required before the single POST. Network ambiguity blocks replay, and successful inserts are re-read by Post ID.
- Extended `/blogger` to show Blogger-only approval state, a live draft preview/confirmation, and actual-vs-Mock draft results. Public publish/schedule, automatic publishing, deletion, and `publish_ready` remain disabled.
- No production Blogger write is made until the user separately approves the exact four displayed requests. Google account identity and billing-console state are not inferred.

## Phase 5-G (shared Blogger OAuth mapping; 2026-10-27)
- Kept the existing single per-blog OAuth reference; a full-scope Blogger connection can serve both read and write permission ranges without new DB columns. Existing read and duplicate writer records remain preserved.
- Added duplicate writer-consent prevention, read-only account blog-list verification for all active registered Blog IDs/URLs, a five-minute verification snapshot, and an explicit-approval atomic common-connection assignment with append-only audit events.
- Exposed connection creation/expiry and encrypted refresh-token presence without token values, and displayed the Blogger cost gate. The current `provider_cost_unverified` gate blocks Google verification, so no live lookup or mapping change was made in this phase.
- Live Blogger writes, automatic publication, and `publish_ready` remain disabled; zero-cost policy is unchanged.

## Blogger OAuth writer permission (2026-10-27)
- Added a separate, user-consented Blogger `blogger` OAuth connection while retaining the existing read-only flow and existing blog-to-connection mappings.
- OAuth state now binds the requested scope; callback validation requires the returned scope to match exactly. Tokens remain Fernet-encrypted, refresh-token rotation preserves the previous refresh token when Google omits a replacement, and failed/denied writer consent only marks the new connection failed.
- Added Dashboard controls and per-connection/per-blog permission, expiry, and verification indicators. The UI states that OAuth write scope does not enable live posting.
- Added migration 034 for requested OAuth scopes on short-lived state records. Blogger write calls, automatic publication, and the unverified zero-cost provider gate remain disabled.

## Phase 5-F (operational transition and Migration 033; 2026-10-27)
- Confirmed user-stopped Dashboard/FastAPI processes and their old process trees were gone; ports 3100/8100 were free. Kept the existing Qwen3 llama.cpp server on 11435 running and unchanged.
- Revalidated operations/test DB identities and test-role CONNECT denial to operations. Created a fresh operations custom-format backup and completed a real restore rehearsal into an owned temporary database; archive and restored snapshot checks passed, audit mutation was blocked, and only the temporary restore DB was removed.
- Applied official Migration 033 after the stopped-service maintenance check, backup/restore rehearsal, and test-schema validation. Operations moved 32→33; `content_versions` remained 360; the only new audit rows were the expected restore and schema-migration events; `publish_ready=true` remained 0.
- Started the current develop API and Dashboard using `scripts/start.ps1`; manager and listener PIDs were verified. Health, `/research`, same-origin research state, Blogger status, and publication status returned the expected current schema and disabled-write fields.
- Full verification passed (176 pytest, Ruff, mypy, wheel, Dashboard ESLint/typecheck/production build, and whitespace check); three focused isolated-database edit/approval tests also passed. Secret scan passed. Browser-based editor interaction was not available; operational content was not edited.
- No Blogger request/write, paid API call, or AI inference was made. OAuth remains `blogger.readonly`; Blogger cost status remains unverified/blocked; live writes, automatic publishing, paid AI, and `publish_ready` remain disabled.

## Phase 5-E (latest runtime and Blogger readiness verification; 2026-10-27)
- Confirmed the existing 3100/8100 services are still unmanaged checkout processes on older code. The lifecycle manager correctly has no ownership record; neither process was stopped or replaced. The project-local llama.cpp process was left untouched.
- Created a fresh operations custom-format backup and verified its PostgreSQL archive catalog. Operations remained schema 32 with 360 content versions, 1,307 audit events, and zero `publish_ready` records. Migration 033 remains pending because the existing API/Dashboard sessions were not gracefully stopped and a controlled maintenance window was not established.
- Ran the latest API and Dashboard on isolated loopback ports 18100/13100 against `woori_blog_agent_test` (schema 33). Health, research state, `/research`, the same-origin state proxy, and publication status returned expected responses; publication remained `fake_only` and real writes disabled. Test DB content, editorial, approval, and publication rows remained empty after the read-only integration session.
- Verified the registered OAuth connection stores only `blogger.readonly`. Official Blogger docs describe write endpoints/scopes but provide no explicit per-call price/free allocation; Cloud billing linkage was not accessible. The provider stays `provider_cost_unverified` and blocked.
- Reviewed `apps/dashboard/AGENTS.md`: its only content is the Next.js-managed guidance block, which Next.js re-adds during `next dev`; its Dashboard-only scope does not conflict with root policy, so it remains tracked.
- Verification passed: 176 pytest tests, Ruff, mypy (28 files), Python wheel, Dashboard ESLint/typecheck/production build, secret/history/HTTP scan, and `git diff --check`. Browser-driven editing could not be verified because no browser surface was available. No Blogger request/write, paid call, AI inference, or publish-ready change occurred.

## Phase 5-D (isolated runtime and integration verification; 2026-10-27)
- Provisioned the dedicated `woori_blog_agent_test` database and test-only app/owner roles. Pytest now requires ignored `.env.test`, verifies the test identity, and confirms the test app role cannot CONNECT to the operations database.
- Applied migrations 001–033 to the test database. Verified editor revision creation, HTML sanitization, stale-version conflict, publication approval/revocation, and approval invalidation after a newer edit inside rollback-only integration transactions.
- Created and catalog-verified an operations backup, then restored it into an owned temporary database and verified schema 32, data counts, and audit immutability. The rehearsal appended its expected audit event; no operational content or schema changed.
- Started the latest API and Dashboard on temporary loopback ports against the test database. API health/state and Dashboard `/research` plus its same-origin research proxy returned 200. Browser-driven editing was not verified because a browser surface was unavailable.
- Existing 3100/8100 listeners remained running: the safe manager has no ownership record and refused shutdown; the API had active client connections. The default listeners still return an older research-state shape. Operations Migration 033 remains pending until a graceful maintenance shutdown.
- Full verification passed: 176 pytest tests, Ruff, mypy, wheel, Dashboard ESLint/typecheck/production build, secret scan, and whitespace checks. No Blogger writes, paid calls, AI inference, or `publish_ready` changes occurred.

## Phase 5-C (local server lifecycle and explicit publication approval; 2026-10-27)
- Added PowerShell status/start/stop/restart management for project-owned Dashboard/API processes with PID reuse checks, executable and checkout validation, port ownership checks, active-client checks, graceful-only shutdown, and no forced termination. Added local llama.cpp status/start support and a verified Ctrl+Break shutdown attempt; unmanaged existing processes are deliberately not stopped.
- Added test-time DB identity validation and forced rollback around application DB connections. The existing Phase 5-B 12 fixture versions remain immutable and are not in the evaluation-DB manuscript list; no content or audit rows were hidden, changed, or removed.
- Added migration 033 and an append-only publication approval/revocation event bound to the exact latest editorial version and body hash. Approval requires both machine quality pass and a positive human editorial review, and never creates a job or changes `publish_ready`.
- Latest live Dashboard/API restart remains unverified because current listeners were started outside the new manager and have no verified graceful control record. No process was stopped; browser editor save flow remains unverified. Blogger writes and paid calls remain blocked.

## Phase 5-B (operations DB integrity and editor integration; 2026-10-27)
- Traced the 12 operational content versions after the 348-row checkpoint to four unisolated runs of the direct-SQL lease recovery integration test; preserved the immutable fixture rows and associated diagnostic audit history.
- Changed the integration-test API/Worker connections to share a forced-rollback transaction and added persisted content/audit count assertions; added a permanent AGENTS.md rule against committed test fixtures in the operational database.
- Verified separate operations/evaluation database identities, least-privilege runtime roles, immutable content/audit protections, and the existing publication fail-closed state. No Blogger request or AI/API inference was performed.
- Current 3100/8100 listeners remain on older code; no forced restart was attempted. Latest browser editor integration remains pending a controlled graceful restart.

## Phase 5-A (manuscript editing and publishing preparation; 2026-10-27)
- Added a filtered manuscript workbench for source-backed Fed/SEC drafts with locale, registered blog, category, editorial/publication state, title search, and modified-time sorting; keeps the full stored sample visible.
- Added a versioned human editor for title, safe formatted HTML, SEO description, keywords, Blogger labels, locale-matched blog target, manual/draft/scheduled intent, and KST planned time. Every save re-runs existing quality checks, rejects stale bases, and appends rather than overwrites.
- Added sandboxed mobile/desktop preview and server-side allowlist HTML sanitation; scripts, event attributes, active embeds and unsafe links are dropped.
- Added existing Blogger post-ID mapping visibility for future updates; no live adapter was enabled and selecting a target or schedule does not dispatch a post.
- Migrations 030–032 record editor metadata, base-version links/body hashes, and any verified existing Blogger post ID. A published draft cannot be retargeted to another blog; Blogger writes, automatic publication, paid API calls, and `publish_ready` activation remain blocked.
- Preserved every saved Fed/SEC content version in the review list (18 distinct versions observed) instead of collapsing older versions by topic and locale. The isolated evaluation DB remains the source of draft bodies; edits are append-only in the operations DB.
- Fixed the missing optimistic-base-hash column with migration 032 and removed an unnecessary row-update lock that prevented the least-privilege app role from saving editor revisions.

## Phase 4-M (editorial review and verifier analysis; 2026-10-27)
- Rechecked the immutable 12-draft Fed/SEC sample read-only: detector false positives were isolated and 10 now pass machine checks; two real output problems remain held. All 12 still need human review and remain non-publishable.
- Fixed date-bearing query terms being mistaken for internal IDs, `Q Apple Inc` being extracted from `10-Q`, and source-supported `USD` wording being treated as an unsupported proper name. Added focused regression tests without relaxing unsupported-number, quote, or language gates.
- Added append-only review-start events and immutable editorial revisions with full deterministic quality rechecks, review status aggregation, source/fact display, side-by-side versions, and editorial review separate from publication approval. Migration 029 adds the new tables and audit records; no stored article or previous evaluation was rewritten.
- No model inference or quota use in this phase. Blogger writes, paid API calls, automatic publishing, and `publish_ready` activation remain disabled.

## Phase 4-L (multilingual fact preservation; 2026-10-27)
- Protect verified numeric tokens and full date spans with typed placeholders during local translation; missing, duplicate, collision, and leaked markers fail closed. Exact values are restored before deterministic checks.
- Correct ISO-date token boundaries when Korean/Japanese particles follow the date. Regression tests distinguish display/grouping normalization from changed numeric or date values without weakening the quality gate.
- Rechecked 12 stored latest Fed/SEC model-language drafts append-only. The corrected detector removed false `no_unverified_numbers` failures; 4 passed machine checks and 8 remain held for quote, keyword, localization, or unsupported-name checks. All require human review.
- Ran one actual SEC Korean Qwen3 4B evaluation (5 model calls, 256 completion tokens, 37.14 seconds); it remains held for language/keyword quality. No new model was downloaded; Blogger writes and paid API calls were zero.

## Phase 4-K (local model comparison; 2026-10-27)
- Added a checksum-pinned Qwen3-4B-Instruct-2507 Q4_K_M artifact as evaluation-only. The existing Qwen3-4B-Q4_K_M remains the operational default; the candidate is rejected for operational runs even if settings are changed.
- Compared actual Fed and SEC C3 outputs where allowed. Candidate SEC English passed machine checks; candidate Fed English, SEC Korean and SEC Japanese remained held. Repeated numerical/proper-name/localization failures stopped remaining candidate locales; all drafts remain unpublished and require human review.
- Added model/run comparisons to the read-only research Dashboard from isolated evaluation DB results, including model identity, measured checks and runtime; source and quality gates remain unchanged.
- Gemma 3 4B was reviewed but not downloaded because access requires accepting separate Google model terms. No Blogger writes or paid inference/API calls were made.

## Phase 4-J (local AI recovery and SEC evaluation; 2026-10-27)
- Diagnosed `local_engine_unavailable` as stale runtime PID metadata; verified pinned model/archive hashes and RX 570 Vulkan visibility, restarted the existing local model and confirmed authenticated health/model-list responses.
- Ran actual Apple SEC evaluations in the isolated evaluation DB for en, ko, ja and zh-CN. All four runs stored new drafts; only English passed machine checks. All remain `quality_held` and `publish_ready=false`; human review remains required.
- Replaced only verified project-owned stale Dashboard/API processes with current develop servers after confirming both queues idle. Validated latest state via API and research SSR, including per-blog AdSense checks, SEC source status, quota, worker, cost and publication gates.
- No Blogger requests, paid calls, quota resets or operational quota changes. Detailed metrics and per-language failures are in P4-J-results JSON and linked run artifacts.

## Phase 4-I (evaluation policy and AdSense preparation; 2026-10-27)
- Raised only the isolated evaluation database's active base-language quota from 2 to 10 per KST day after reviewing two measured Qwen3 4B runs and current machine headroom. Preserved existing usage and added one SEC English reservation inside the ten-slot limit; global concurrency remains one and shared CPU/RAM/disk gates remain active.
- Enforced the SEC reservation in evaluation admission so Fed work cannot consume the reserved English target. Added read-only quota, reserved-volume, and remaining-capacity fields to the Dashboard API.
- Added a per-Blogger AdSense preparation checklist with explicit not-verified/human-review states, public counts left unknown without a fresh allowed public read, and no approval prediction. Added official Google references and marked post-count/article-length heuristics as internal only.
- Recorded the isolated quota change in append-only audit event `evaluation.quota.policy.updated`. Operational generation quotas, Blogger connection/cost gates, publication controls, and `publish_ready` were not changed.
- SEC inference remained blocked because the project-local llama.cpp runtime was unavailable. Current 3100/8100 services were not restarted; safe refresh steps are documented.

## Phase 4-H (quota and runtime validation; 2026-10-27)
- Traced both current-day English evaluation targets to separate bounded Fed experiments at 00:00 and 00:28 KST. Each made five Qwen3 4B calls and ended `quality_held`; two distinct target rows correctly consumed the two-slot quota. No SEC inference was started.
- Added a quota regression test for KST midnight independence from PostgreSQL session timezone, failed-target counting, idempotent retry reuse, and hard-stop at the existing limit.
- Validated the latest FastAPI state with an isolated in-process TestClient against the actual operations/evaluation databases. Current 3100/8100 processes predate the latest readiness fields; their runtime was left untouched. Dashboard data and stale runtime status are documented.
- SEC and Fed continue sharing the existing per-language quota. Documented a bounded SEC-first reservation and stable evaluation idempotency design without increasing quota or changing runtime policy.
- Blogger reads remain blocked by `provider_cost_unverified`; no Blogger request, paid call, automatic publication, or `publish_ready` change was made.

## Phase 4-G (SEC evaluation preflight; 2026-10-27)
- Revalidated the rotated evaluation migration credential using the ignored configuration without printing secret values. The new credential connects only to the evaluation database; operational database CONNECT is denied. The former credential was not retained, so a direct old-password rejection attempt was not made.
- Confirmed the Asia/Seoul quota window has not reset: SEC English is 2/2 and no successful English SEC source draft exists. Actual Qwen3 inference and all dependent locales were safely stopped before model startup; remaining Japanese and Chinese quota was not used.
- Confirmed four Fed language drafts remain machine-passed and pending human review (0/4 review records). Dashboard source contains the review workflow, but the already-running local services return a pre-Phase-4-F state payload; they were not restarted.
- Kept Blogger reads blocked under `provider_cost_unverified`; no new cost research or Blogger request was made. Existing logged Blogger operations are GET-only; real writes, automatic publishing, and `publish_ready` remain disabled.
- Recorded this assessment as an append-only evaluation audit event and a separate sanitized JSON result.

## Phase 4-F (security and SEC preflight; 2026-10-27)
- Rotated the isolated evaluation migration-role credential after an ignored environment-file value appeared in an earlier tool result; validated the replacement connection without printing credential material. Added password redaction regression coverage and a metadata-only config report command.
- Confirmed the migration role has no superuser/database-role creation privileges, cannot connect to the operations DB, and had no other active sessions. No migration was run.
- Block SEC localized evaluation requests before generation-target creation when the successful English source draft is absent. Record the block without consuming quota or invoking a model.
- Current SEC English quota is exhausted (2/2), with no successful English source version, so new SEC inference remains blocked. Blogger API pricing/free allowance and the Cloud project's billing attachment remain unverified; Blogger GET and all writes remain disabled.
- `publish_ready=false`, automatic publication, and Blogger writes remain disabled.

## Phase 4-E (partial validation; 2026-10-27)
- Show SEC evaluation quota and source-draft prerequisite per registered language. English quota is independent; downstream localization still requires a successful English draft for the same SEC topic.
- Fail SEC evaluation before enqueue when that source-language draft is missing, preventing a failed localized run from consuming another locale's daily quota.
- Keep historical Mock Publisher and Worker evidence explicitly labeled historical, and expose failed SEC attempts without treating them as saved drafts or human-review items.
- Review Blogger API pricing, project billing association, quota semantics, and public Atom/RSS alternatives from official references. Cost/billing and feed reuse conditions remain unverified, so neither Blogger API GET nor public feed GET was sent.
- Record four Fed machine-passed drafts as pending human review (0/4 reviewed); editorial review remains separate from publication approval.
- No schema migration. Operating Blogger writes, automatic publication, and `publish_ready` remain disabled.

## Phase 4-D (partial validation; 2026-10-27)
- Reviewed official Blogger/OAuth/Cloud quota and API Keys pricing references. Blogger per-call pricing/free allocation and the OAuth project's billing attachment remain unverified, so the Blogger read provider stays blocked; no live GET was attempted.
- Captured the SEC evaluation DB's current quota and safely stopped before model start because English was already at 2/2. Recorded the blocked evaluation and readiness assessment in append-only audit events and a corrected JSON snapshot.
- Added an operations readiness table backed by current database and provider-gate state, plus cited historical isolated Worker test evidence. It distinguishes machine checks, human review, cost/read gates, Mock publication and separate live publication approval.
- Added explicit editorial approval separate from Blogger publication permission. Approval requires positive human assessments for factual accuracy, translation naturalness and reader value; no human review was entered in this phase.
- Added migration 028; Blogger writes, automatic publication and `publish_ready` remain disabled.

## Phase 4-C (partial validation; 2026-10-27)
- Add a human review workspace for the four machine-passed Fed C3 language drafts, with full text, paragraph-to-sentence citation display, source facts, dates/numbers, keywords, and append-only review comments/history.
- Persist editorial feedback in an immutable operations table. Review notes never modify an article version, approve Blogger publication, or change `publish_ready`.
- Add a scoped read-only grant for evaluation quality rows and dashboard prepublication status covering quota, historical Blogger verification, OAuth scopes, and safety counts.
- Do not run SEC inference because the required first English target is already at its 2/2 KST quota. Do not send Blogger GET requests because the zero-cost provider gate still blocks Blogger API calls pending cost review.
- Keep Blogger writes, paid services, automatic publication, and `publish_ready` disabled.

## Phase 3.9-U (implementation complete; real model check pending)
- Confirm the Phase 3.9-T 30-token overlap is an exact copied source sentence, not a verifier false positive; preserve the original held version and append two deterministic rechecks.
- Strengthen local fact paraphrasing, apply the unchanged 25-token source-overlap limit per fact, and derive bounded search-intent metadata from clearly date-qualified topic labels.
- Keep real model improvement unverified until Phase 3.9-V; quality and publication gates remain closed.

## Phase 3.9-T (partial validation; 2026-10-27)
- Added a physically separate, secret-free evaluation database snapshot with least-privilege application, reader, migration, and identity roles; no Blogger/OAuth/publishing state is copied.
- Added read-only evaluation result visibility to the research dashboard and a single-shot isolated Worker path for sequential, per-language C3 evaluation.
- Added evaluation-only cross-run source-draft reuse for localization, preserving source-version links without touching operational records.
- Run one actual Fed English C3 job in the isolated evaluation DB with Qwen3 4B Q4_K_M; save the draft as `quality_held` because the direct-quotation/source-overlap gate detected a 30-word overlap. Do not claim a quality improvement over C1 (7 held, 1 not replayable); stop the remaining seven planned evaluations pending analysis.
- Fixed evaluation Worker bootstrap validation without loading an administrator secret and retried the same quota-counted run; verify heartbeat stop, 33 audit events, 5 model calls, and resource samples. Publishing and paid services remain disabled.

## Unreleased - Phase 3.9-S - 2026-10-26

- Separate evaluation and operations daily quotas while retaining shared resource, pause, and concurrency gates; evaluation fails closed unless physical DB isolation is verified.
- Add per-mode Worker heartbeat/audit state and an isolated diagnostic Worker harness covering completion, retry, lease recovery, duplicate prevention, abnormal exit, and cleanup.
- Record that C3 inference remains blocked while evaluation shares the operational database and the current evaluation quota is exhausted; no operational rows were reset.

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

## Unreleased - Phase 3.9-V - 2026-10-27
- Fix a verified Korean proper-name checker false positive when exact Latin entities are followed by Hangul particles; preserve strict unsupported-name detection.
- Run four quota-bound Fed C3 language evaluations using the existing local Qwen3 4B model and preserve per-run artifacts plus deterministic rechecks. SEC evaluation remains quota-blocked.


## Unreleased - Phase 4-A - 2026-10-27
- Add blocked-by-default publication requests, eligibility reasons, append-only state events and mock attempts.
- Add a network-free Fake Publisher and a permanently disabled real Publisher adapter; no route can approve human review or enable live writes.
- Add the `/publishing` dashboard and same-origin API proxy with blocked request and offline simulation views.
- Add additive schema migration 025; publication attempts and state history are immutable and `publish_ready` remains disabled.


## Unreleased - Phase 4-B - 2026-10-27
- Add future-only Asia/Seoul-aware mock scheduling, rescheduling, cancellation, and append-only schedule events.
- Add a lease-based one-job Worker restricted to fake-only runs, with bounded retry, heartbeat, uncertain-result stop, and expired-lease recovery.
- Add paginated Blogger read-only post reconciliation; mismatches are reported for manual review and no internal publication state is changed.
- Add explicit mock/worker/sync status to the publication dashboard and schema migration 026.

## P5-CONTENT-001 (2026-10-27)
- Added migrations 037?039 for immutable trend-topic clusters, non-merging cross-region proposals, configurable triage scores, append-only editorial/source/grouping reviews, and Research Package snapshots.
- Added actual HTTP response status capture for future RSS runs; historical statuses remain null where they were never recorded.
- Extended `/research` with topic assessment, reviewed source linking, package inspection, and event-group review controls.
- Tested US, JP, TW, HK and SG Google Trends RSS in the isolated test DB: ten observations each; source rank remained null. All 60 candidates are held; no reviewed factual sources were present, so the example package remains `insufficient_evidence`. No article, AI call, Blogger write, or operations DB migration occurred.
