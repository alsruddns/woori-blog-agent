# Research operations

## Current capability

The API and Dashboard support bounded Federal Reserve RSS, SEC EDGAR and Wikidata collection, reviewed-source storage, trend observations, topic assessment, immutable Research Packages, deterministic quality checks, editorial review, and Blogger preview/publication preparation. Research and historical evaluation data are retained.

No production manuscript-generation or translation provider is currently attached. Cross-language drafting remains held. Mock generation is reserved for automated tests and is not a content provider. The API rejects local Qwen/llama.cpp configurations, automatic generation schedules, and collection-to-generation handoff. Codex/GPT scheduled or unattended generation has not been implemented.

Historical Qwen3 evaluation records and result artifacts remain read-only. They do not imply that a model runtime is installed, running, or available for new inference.

## Start the supported local services

Use the project-managed API, Dashboard, and Worker scripts only when those services are needed. No model setup, model download, llama.cpp server, or model runtime management step is required. The service manager tracks API and Dashboard; the research worker is a separate process. Do not enable OS startup registration unless separately intended and reviewed.

```powershell
./scripts/start.ps1 -Service api
./scripts/start.ps1 -Service dashboard
./scripts/run-worker.ps1
```

Check health and worker heartbeat through the existing operations pages. A stale or missing heartbeat is unknown/stale, never healthy. Do not restart services that have active user work.

## Research collection

Collection schedules can remain enabled independently of manuscript generation. Collection results are persisted with source URL, retrieval time, source-provided rank (nullable), rights/access metadata, and audit events. If a legacy collection row requests `auto_generate`, collection may finish but the generation handoff is explicitly blocked and audited. No synthetic article replaces a failed collection or unavailable provider.

Use the fixed, allowlisted adapters and their rate limits. Do not add arbitrary URL fetching, bypass source restrictions, or treat a trend as article evidence. Research Packages require reviewed factual sources and retain their existing hold states until their evidence and human-review requirements are met.

## Quality and publication

Quality validation, HTML sanitization, SEO checks, editorial review, publication approvals, Fake Publisher tests, and Blogger integration remain separate from manuscript generation. Publication mode defaults to Manual. Auto publication configuration does not create an AI writer and must not be treated as automated content generation. Real Blogger writes remain controlled by their own explicit policy and approval gates.

Machine checks do not approve semantic truth, rights, translation naturalness, or reader value. Keep held content held, preserve `generation_ready=false` and `publish_ready=false` unless an authorized workflow changes a specific record, and retain append-only history.

## Historical evidence

Prior Qwen3 and llama.cpp measurements, model identity/checksums, evaluation runs, quality outcomes, and quota history are preserved in `docs/development/` and the audit database. Their old runner scripts and runtime controls have been removed. Do not infer current runtime availability from those records.
