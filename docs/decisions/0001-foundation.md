# ADR 0001: isolated local foundation
Date: 2026-10-26. Accepted.

Use Next.js/TypeScript, FastAPI/Python and PostgreSQL 16 without Docker. Prefer a PostgreSQL durable queue over an in-memory scheduler on Windows. Use append-only audit and content tables, separate database owner and restricted runtime role. No paid AI or publishing network adapter exists in Phase 1.

Repository initially had no commits or branches on origin. GitHub default branch was already main. A policy-only root commit anchors main; all implementation commits are on develop. There were no branch protection rules or rulesets to transfer. Only main and develop are permitted. No merge or deployment is authorized.

Audit hash chaining is deferred: database privileges plus mutation-blocking triggers protect routine application use, but do not prove integrity against the database owner/superuser. Offline encrypted immutable backups and later external checkpoints are needed for that stronger guarantee.
