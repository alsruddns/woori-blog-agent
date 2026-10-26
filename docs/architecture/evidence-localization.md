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
4. The local provider receives only one excerpt, protects known names and approved glossary terms with fixed placeholders, and restores only the source spelling or approved translation after the model responds. Missing/duplicated placeholders fail closed. Strict JSON schema parsing, timeout, response-size cap, local loopback endpoint, model identity and existing token protections apply. Deterministic checks compare numbers/dates, known source entities, links, citations, repetition, and language script. A held result is retained as an evaluation, not accepted prose.
5. `build_localized_evidence_template` combines only machine-passed fact spans with supplied title/summary/keyword candidates and re-runs the existing grounding gate. Semantic fidelity, naturalness, rights, and editorial acceptance remain human checks. No function enables publication.

The Research dashboard displays original excerpts beside persisted localized output, status/metrics, current glossary approvals, and immutable glossary history. It reports actual stored rows only.

## Limitations

Language script and exact token checks are heuristics, not semantic entailment. The checker does not prove a translated sentence means the same thing as its source, nor does an English proper-name detector cover every writing system. Such cases remain human-review items. A `machine_passed` evaluation alone is never a human quality approval. Title/summary/keyword candidates must still be supplied and validated before a full localized draft can be composed.
