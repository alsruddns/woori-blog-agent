# Evidence-backed staged generation

Phase 3.7 splits research generation into durable, auditable stages: source collection, verbatim evidence extraction, evidence validation, a bounded outline, one model call per section, per-section localization, rule-based claim checks, SEO/quality checks, and version persistence. Every attempt is stored in `generation_stage_runs` with a UUID, target profile, worker/stage attempt, input and output snapshots, model and prompt version, source IDs, validation details, timing, and an audit event. A lease-recovered running stage is terminalized as `worker_interrupted`; terminal records cannot be edited or deleted.

Evidence facts receive stable IDs derived from the source ID, sentence index, and sentence hash. The evidence validation stage requires the extracted sentence to occur verbatim in the reviewed source revision. The outline only groups fact IDs and is capped at four sections. Each section receives only its assigned evidence, source IDs, and (for localization) the matching source section. Model calls use strict JSON schema output where the local llama.cpp endpoint supports it, followed by Pydantic validation and deterministic checks. Section calls are retried once with the failed check names. A failed section remains visible as `held`; final rule, SEO, and human-review gates independently determine the saved version state.

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
