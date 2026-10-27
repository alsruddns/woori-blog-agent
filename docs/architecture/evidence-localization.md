# Evidence-preserving localization

Schema versions 16–18 add the following additive records:

- `research_sources.source_language` records the language given at source registration; `source_reviews.source_language` appends a reviewed correction/attribution without rewriting historical sources. `und` stays unknown and blocks cross-language output.
- `evidence_facts` stores an exact excerpt, stable source-derived key, BCP 47 source language, entity fingerprints, numeric/date values, citation source IDs, extractor version, and source-span verification state. Facts can only be appended.
- `glossary_entries` records source/target language, official-translation status, translation provenance and explicit approval. Existing entries default to unapproved. `glossary_entry_revisions` retains each state append-only, including a migration backfill of the prior state.
- `localization_evaluations` stores the per-fact output snapshot, machine checks, model/call/time metrics, human-review requirement, and a database-enforced `publish_ready=false`.

## Runtime flow

1. An administrator reviews a current, unexpired source and may record its language on that immutable review.
2. `POST /admin/research/sources/{source_id}/facts` extracts exact sentence spans and inserts idempotently into the fact ledger. It rejects unreviewed, expired, or superseded sources.
3. `POST /admin/research/localizations` takes a fact ID and active target BCP 47 language. Same-language output is an exact source span. Cross-language output requires an enabled `local` provider plus profile-level translation and language verification. Daily profile limits are enforced. There is no Mock or paid/cloud fallback for translation.
4. The local provider receives only one excerpt and protects known names, approved glossary terms, complete recognized date spans, and numeric tokens with typed unique placeholders. Each marker must occur exactly once; missing, duplicated, colliding, or leaked markers fail closed. Exact source values are restored after inference. Numeric grouping and date display equivalence are checked separately from value equality; localized display conversion is not inferred by the model. Strict JSON schema parsing, timeout, response-size cap, local loopback endpoint, model identity, and existing token protections apply. Deterministic checks compare numbers/dates, known source entities, links, citations, repetition, and language script. A held result is retained as an evaluation, not accepted prose.
5. `build_localized_evidence_template` combines only machine-passed fact spans with supplied title/summary/keyword candidates and re-runs the existing grounding gate. Semantic fidelity, naturalness, rights, and editorial acceptance remain human checks. No function enables publication.

## Fact-first pipeline rendering (Phase 3.8-C3)

The durable content worker appends exact reviewed source spans to `evidence_facts` before planning. The `fact_registry` step is stored in the existing immutable `generation_stage_runs` ledger alongside source collection, extraction, validation, outline, per-section generation/localization, claim checks, SEO checks and persistence.

For local-language output, each source span is sent independently to the local translation adapter. The adapter protects extracted names and approved glossary entries, returns a strict JSON string field, and checks number/date/entity/script/link preservation. The application attaches citation IDs and section structure after translation. A held fact remains visible as held output; it is never converted into an approval. Title candidates are derived from the recorded topic phrase, while meaning, editorial quality, SEO intent and naturalness remain human-review items.

Evaluation-only jobs may use the fixed, already-installed Qwen3 4B Q4 model when the saved profile model differs. The override is captured in each target snapshot and audit event, does not modify generation settings, counts against the same configured daily limit, and remains under the pipeline concurrency and RAM/CPU gates.

The Research dashboard displays original excerpts beside persisted localized output, status/metrics, current glossary approvals, and immutable glossary history. It reports actual stored rows only.

## Phase 3.9-U source-overlap controls

The local faithful-paraphrase instruction requests independently worded text and explicitly rejects long copied runs. `localize_fact` applies the same existing 25-token longest-contiguous-source-overlap gate to each localized fact, and the complete article is checked again after rendering. This is an additional early hold, not a relaxed article threshold. A source-faithful paraphrase still needs a human semantic and rights review. Long date-qualified topic labels are reduced only at a clear date-introducer boundary for title/keyword metadata; ambiguous overlong phrases fail closed instead of being cut arbitrarily.

## Limitations

Language script and exact token checks are heuristics, not semantic entailment. The checker does not prove a translated sentence means the same thing as its source, nor does an English proper-name detector cover every writing system. Such cases remain human-review items. A `machine_passed` evaluation alone is never a human quality approval. Title/summary/keyword candidates must still be supplied and validated before a full localized draft can be composed.


## Latin entities adjacent to localized particles

Proper-name preservation uses ASCII-character lookarounds rather than Unicode word boundaries. This recognizes an unchanged Latin organization name when a Korean particle directly follows it, while the entity tokens themselves must still match the evidence. The check does not approve translated names without a glossary mapping and does not relax unsupported-entity checks. Semantic accuracy and naturalness remain human-review items.

## Protected number and date spans (Phase 4-L)

Localization inference replaces verified date spans and numeric tokens with type-specific placeholders before sending the excerpt to the local model. A missing or duplicated marker fails the translation; successful output restores the exact original value. `grounding.numbers()` separately normalizes harmless numeric grouping and recognized date display forms. ISO dates followed directly by Korean or other localized particles use ASCII token boundaries so the particle does not make a valid date look like three unsupported numbers. This is a detector correction only; changed values remain a hard failure. The research dashboard shows each fact's stored numeric/date values next to its source excerpt and glossary/revision history.
