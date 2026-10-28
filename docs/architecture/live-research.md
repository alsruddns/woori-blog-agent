# Live research and generation capability

## Current state

The FastAPI research API and Dashboard support bounded source collection, source review, trend observations, topic assessment, Research Packages, evidence facts, deterministic quality checks, editorial review, Blogger-safe HTML/SEO previews, and publication preparation. Existing content, evaluations, audit events, and publication records remain in their current databases.

No production manuscript-generation or translation provider is attached. The local Qwen3/llama.cpp provider, model overrides, setup/download scripts, and runtime controls have been retired. API generation requests, content-generation schedules, and collection-to-generation handoffs fail closed. The synthetic MockProvider is test-only. Codex/GPT scheduled or unattended execution is not implemented.

Cross-language localization is stored as held with zero model calls unless it is deterministic same-language normalization. Existing fact ledgers, source snapshots, glossary history, and prior localization evaluations are preserved. No held result is promoted automatically.

## Collection pipeline

Fixed RSS/API adapters retrieve bounded data through the provider allowlist. Each observation retains the actual source-provided fields, retrieval time, source URL, payload identity, rights/access review and audit events. Missing ranks remain null. Trend observations and topic similarity do not themselves establish factual support.

Official sources and reviewed source spans are linked to topic candidates. A Research Package records facts, sources, conflicts, uncertainty and use restrictions. Insufficient or unreviewed evidence remains held. Source collection may run without any manuscript writer. Legacy `auto_generate` flags do not trigger generation; the handoff is blocked and audited.

## Preserved generation and editorial boundaries

The database retains generation-stage schemas and historical Qwen3 evaluation records for audit and read-only comparison. No schema migration is needed for this cleanup, and no operations, evaluation or test database was modified by the cleanup itself. Old `engine`/`provider` values may remain in existing rows but cannot enable local inference; the API rejects local provider settings and the Worker does not process generation queues while no writer is configured.

HTML conversion, sanitization, SEO checks, stored manuscript browsing, human editorial review, versioning, approval/revocation records, Manual/Auto publication policy configuration, Fake Publisher tests, and Blogger safety gates are independent of the retired model runtime. Their use does not imply a writer is connected.

## Historical artifacts

Past model/runtime identities, checksums, benchmarks, source packages, generated drafts, quota records, and quality outcomes remain in `docs/development/` and append-only database history. They document prior experiments, not current runtime availability. `.local` model files and shared engine binaries are user-managed; repository scripts no longer install, start, monitor, stop, or delete them.
