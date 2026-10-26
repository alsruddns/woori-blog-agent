# ADR 0002: configuration-driven multilingual expansion
Date: 2026-10-26. Accepted.

Retain the Phase 1 runtime and Git/safety policies. Replace fixed language constraints with languages, regional profiles and normalized localizations. Keep the four current languages only as initial data. Separate language identity from target country and from blog identity; many blogs can use one language.

Preserve original content/version/audit UUIDs and data via ordered migrations 002–004. Keep legacy version inserts compatible through an insert trigger; new code should use localization_id. Disable language/blog records rather than delete. Forbid changes to historical identity fields and enforce matching language/country references on jobs, SEO results and metrics.

Use langcodes plus language-data for BCP 47 normalization/registry checks, and croniter plus zoneinfo for schedule validation. Schedules are stored, not executed. No static list of four languages exists in runtime business logic. Standards: [RFC 5646](https://www.rfc-editor.org/rfc/rfc5646.html), [langcodes validation limitations](https://github.com/rspeer/langcodes), [croniter](https://github.com/pallets-eco/croniter).

Keep unverified capability and Blog ID fields read-only to normal configuration API calls. Exact language support is checked against empty-by-default adapter registries. Retain the unconditional Phase 1 network block and DB prohibition of automatic publication. Future activation requires separate approval, trusted adapter verification, connection/test evidence, quality gates and a reviewed migration; registering a language never grants publication permission.

Audit successful configuration changes through DB triggers in the same transaction. Store entity references, actor and row fingerprints without copying arbitrary policy text or credential-like payloads to logs. Fingerprints are change markers, not an immutable hash chain, policy snapshots or external proof against a database administrator. Full policy revision replay is a future feature.
