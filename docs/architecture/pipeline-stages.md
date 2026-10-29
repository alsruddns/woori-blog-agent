> Current status: persisted stage records and deterministic quality gates remain supported. The local llama.cpp model-call execution described below is historical. No in-process production generator is attached. An official Codex desktop Local Scheduled task may act as an external draft-file exporter; a probe file was written on 2026-10-29, but article generation and Import remain unverified.

# Evidence-backed staged generation

Phase 3.7 splits research generation into durable, auditable stages: source collection, verbatim evidence extraction, evidence validation, a bounded outline, one model call per section, per-section localization, rule-based claim checks, SEO/quality checks, and version persistence. Every attempt is stored in `generation_stage_runs` with a UUID, target profile, worker/stage attempt, input and output snapshots, model and prompt version, source IDs, validation details, timing, and an audit event. A lease-recovered running stage is terminalized as `worker_interrupted`; terminal records cannot be edited or deleted.

Evidence facts receive stable IDs derived from the source ID, sentence index, and sentence hash. The evidence validation stage requires the extracted sentence to occur verbatim in the reviewed source revision. The outline only groups fact IDs and is capped at four sections. Each section receives only its assigned evidence, source IDs, and (for localization) the matching source section. Historical model calls used strict JSON schema output where the local llama.cpp endpoint supported it, followed by Pydantic validation and deterministic checks. The endpoint and model-call path have been retired. Section calls are retried once with the failed check names. A failed section remains visible as `held`; final rule, SEO, and human-review gates independently determine the saved version state.

The deterministic gates check citation IDs, permitted source IDs, number/date preservation, detected proper-name preservation and unsupported detected names, and exact repeated sentences. The whole-draft gate additionally checks language script, URLs, paragraph citations, repetition, source freshness, and obvious high-risk language. These checks are conservative diagnostics, not semantic entailment. A sentence can be syntactically cited while still making an unsupported inference; therefore no model self-score can approve facts, translation quality, copyright, or naturalness. All Phase 3.7 evaluation jobs are `evaluation_only`; saved versions remain `quality_held`, `publish_ready=false`, and require human review.

Localization is driven by active database language profiles and their country, generation, localization, SEO, and glossary policies. The pipeline has no four-language branch. Proper names and numeric/date values are preserved as source identifiers; country-specific facts must come from reviewed evidence for that target. Unsupported localized names or values are held for review.

The research dashboard reads stage history and category/profile source coverage from the database. It exposes stage input/output snapshots to the authenticated local administrator. Benchmark summaries distinguish actual model execution from deterministic validation and human review. Blogger write paths and paid/metered external providers remain blocked.

## Known limits

- Exact evidence spans prove extraction provenance only; they do not prove source truth or semantic equivalence of model paraphrases.
- The current section gate can only detect certain surface-level changes. A citation marker is not a proof that every sentence is supported.
- One Federal Reserve source/topic was used for the Phase 3.7 live four-language run. That is not a representative seven-category or language-wide quality dataset.
- Current generator output can still fail name, number, language, SEO, and semantic review. This is expected to remain held until the quality evidence is sufficient.
- Blogger themes/API support for `hreflang` has not been implemented or claimed.
# Fact-first source registry

For evidence-led jobs, a `fact_registry` stage follows exact-span extraction and appends the registered fact IDs to the shared immutable fact ledger. Localized facts are translated individually; citation markers and article structure are rendered by application code, then the assembled article passes claim and SEO checks. Machine localization checks are retained per fact, and semantic accuracy stays pending human review.


## Worker health and automatic quality status (Phase 3.9)

`worker_heartbeats` is a mutable current-state projection for the single local research worker. The process refreshes it every 15 seconds; status transitions, PID changes, and sanitized error-category changes are appended to `audit_events`. The dashboard calls a heartbeat fresh only within 45 seconds. A missing or stale row means health is unknown, never healthy.

Generation stage/SEO checks and immutable full-article evaluation records supply the machine result. A machine pass remains human-review-required, and `publish_ready` is constrained false. Deterministic rechecks create a new evaluation batch and audit events rather than modifying prior results.

## Phase 3.9-S quota and Worker isolation

Operational and evaluation generation targets use independent daily counters. Creating a target consumes its mode's quota even if it later fails or is cancelled; idempotent retries reuse the existing target and do not consume another slot. The daily window resets at 00:00 Asia/Seoul using explicit timezone conversion; dashboard responses include the next reset timestamp. No endpoint resets usage. Both modes continue to share the system pause, resource-admission, and concurrency limits.

For SEC evaluation, localized targets require a successful English source-language draft for the same keyword. The API checks this prerequisite before creating generation targets. A missing prerequisite is recorded as an append-only audit event with `quota_consumed=false` and `model_calls=0`; it is distinct from a model failure. Historical targets created before this preflight remain counted under the existing rule.

Evaluation mode is disabled by default. API enqueue and the evaluation Worker require the explicit `pipeline_controls.evaluation_isolated` flag and an operational database URL that resolves to a different PostgreSQL database name. Evaluation ticks consume/recover only evaluation jobs. A separate quota or queue filter without a separate database is insufficient. The isolated Worker verification harness uses a randomly named schema with a schema-only search path and a test-only diagnostic queue; it does not touch public operational rows and drops that schema after recording the result.
