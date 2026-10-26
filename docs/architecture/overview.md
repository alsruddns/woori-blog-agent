# Phase 1 architecture

Next.js server component -> loopback FastAPI with bearer authentication -> PostgreSQL 16. Python worker polls durable job_runs, with SKIP LOCKED claiming, lease recovery and bounded attempts. Queue state and audit events commit together. Waiting jobs survive reboot; expired running leases are recovered on the next worker tick. This is a diagnostic worker, not the future content pipeline.

One content_groups record connects immutable content_versions in ko/en/zh-CN/ja. Each language has independent numbered revisions; source_version_id links derivation. Future content services must enforce same-group source links, transactional version allocation and semantic comparisons. Phase 1 provides schema only, not editing/comparison UI.

Future pipeline: keyword discovery -> research -> fact/source verification -> generation -> intent-aware localization -> quality/SEO gates -> approval -> Blogger -> Search Console -> improvements. Topics: finance, stocks, crypto, K-pop idols, K-Beauty, Korean travel and restaurants for foreign visitors. Four independent blogs will map to the four languages in a later phase; no live blog IDs are configured.

AI and Blogger adapters currently raise before network access, regardless of environment flags. Local model integration is also deferred. Future paid providers require explicit recorded approval plus fail-closed configuration. Future publishing requires an outbox, stable per-blog/version idempotency keys and remote reconciliation after ambiguous network outcomes; diagnostic queue deduplication alone is not a publishing guarantee.

No Search Console/Analytics/OAuth connectors, SEO checks or content generation are claimed implemented. Blogger-specific SEO limitations must be verified against official API capabilities before implementation.
