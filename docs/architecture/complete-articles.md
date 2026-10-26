# Phase 3.8-C1: official-source complete article evaluation

## Data flow

The durable collection queue remains the only route to external sources. Federal Reserve collection uses its configured RSS/release allowlist. SEC collection is limited to `data.sec.gov` company submissions plus accession-matched companyconcept XBRL facts, requires a declared contact in the SEC User-Agent, and applies a local 3/minute and 24/hour cap. No filing HTML, arbitrary URL, bulk companyfacts, or attachment is collected. External calls still pass through the shared zero-cost policy.

For evaluation, the latest approved and unexpired Fed and SEC records are selected. Their recorded collection timestamp, publication date, rights review, access policy and source excerpt are retained. A versioned deterministic fact ledger splits source excerpts, hashes each fact, and stores source IDs, entity IDs, numeric/date tokens and extraction version. This is traceability metadata, not an independent fact-check of source truth.

The local-only Qwen3 4B Q4_K_M process receives the fact ledger and source record to create an article in each active database language profile. Draft title, summary, keywords, body, source IDs and measured model/resource metrics are checked separately from source-span verification. Full-article checks cover paragraph citations, numeric and name grounding, language/script, repetitions, source overlap, article structure and title/keyword alignment. Unsupported or unverified claims remain held. Human semantic, naturalness and rights review are distinct fields and never inferred from the machine result.

Each topic/language evaluation is append-only in `article_quality_evaluations`; any generated content version is inserted into the existing content group/version model. `seo_audits` records deterministic checks. `publish_ready` is always false and Blogger write remains blocked. Re-running uses a new batch ID and creates new evaluations/versions; it does not edit prior evaluation rows.

## Dashboard

`/research` exposes current source last-attempt/last-success times and source policy, plus saved article title, summary, keywords, full body, automated checks, execution time/resource measurements, and human-review/publication state. It displays persisted evaluation results rather than fixture/demo content.

## Limits

The current evaluation is deliberately narrow: one Federal Reserve release and one Apple SEC 10-Q. It is not representative of all seven topic categories or all markets. Qwen output is variable and this run did not pass the machine quality gate. A schema-valid or machine-passing result would still require a human editor. Search ranking and investment utility are not measured. No real Blogger write or paid service is used.
