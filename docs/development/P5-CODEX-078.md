# P5-CODEX-078: in-place publishing and interval recovery

2026-10-30 KST, develop. Existing Imports, approvals, Jobs, audits, scheduled settings and Blogger policies are preserved.

## UI

- Publishing imported-title buttons and failure-row manual actions open the existing ExternalImportWorkspace sheet in embedded mode. Same detail/editor/evidence/history/distribution implementation and manual eligibility/hash-bound POST are reused; no new Import or write API.
- URL keeps publishing view/search/language/blog/page and exact detail IDs. Server page now awaits Next searchParams and forwards supported filters, so refresh restores the selected list. Closing removes only detail parameters; existing ESC/popstate handling remains.
- Removed UI-appended failure badge beside titles; status remains in its status column. Stored titles/search/sort are not rewritten.
- Three manual checkboxes default true, reset on opening, and have separate vertically aligned 44px click rows. Actor admin/reason 확인완료 remain editable. Defaults alone cause no audit or request: exact-title/body/hash/blog final confirmation and explicit user publish click remain required.
- POST uses the existing idempotency key/transaction, ref-based synchronous duplicate guard, disabled pending action and 30s response timeout. An uncertain response is not automatically resent; user must refresh existing Job/eligibility state before another request. Exact idempotency remains server-enforced. Sheet shows errors/success/returned Job ID; parent list and read-only Job monitor refresh immediately. Job queued is never labelled published.
- Existing 10s visible-only monitor remains; queued interval waits show their actual available_at KST. No invented progress or next time.

## Interval failure

- Existing PHP2Shell Import `9a6d4636-3156-4eb6-907b-33deb4940c17`, version `611298c5-0efd-43f9-9180-fc9fc5309d0b`, Job `2e9752ff-cd20-49b9-84b3-700d3a1b3e6a`; English blog 5240203250707821039. Existing manual approval created 15:59:06.432622 KST. Failed create_draft at 15:59:10.627029, retry_count 0, no remote_post_id.
- Root cause: BloggerLivePublisher._account_write_guard in blogger_writes.py, before HTTP/ledger claim, raises account_minimum_interval_not_elapsed. It serializes by OAuth connection ID, not inferred Google-user identity: shared connection 4839f8b9-69c8-4ce4-b1c1-5b71e96d5896, account 2 minutes and blog 5 minutes from last live write request audit (including draft/publish, conservatively including failed requests). Neither interval is shortened.
- Last shared-account write request: Japanese publish_draft at 15:58:09.180695 KST; verified publication 15:58:14, post 752018775265955197. Thus account deadline for original failure was 16:00:09.180695 KST; blog deadline is also checked and later of both applies. Current recovery recalculates from current audits, not this historical timestamp.
- WriteIntervalWait now carries the real max(account+2m,blog+5m,now) deadline. Both draft and publish Worker catch paths preserve exact stage/remote ID/approval/idempotency, set queued/publication_queued, clear lease, and persist available_at/reason with append-only interval_wait audit. No retry_count consumption or failed HTTP attempt is fabricated. Existing due-Job query only leases after available_at; normal safety/remote checks rerun.
- recover_interval_job accepts only the legacy pre-HTTP failed manual stage with the exact interval category, no remote ID and matching existing approval hashes/attestations. It checks current blockers and remote duplicates, re-locks/rechecks unchanged Job and absence of prior write ledger/publication, then requeues the same Job and audits recovery. It never creates an approval or Job. Ambiguous or found remote result stops recovery for reconciliation.

## Checks and runtime

- Focused isolated DB/manual transaction/guard/monitor tests: 81 passed. Four locales exercise original approval → interval defer → due gating → remote unknown rejection → same Job recovery → duplicate recovery rejection, preserving one approval. Pure timing tests cover account/blog deadlines and expired boundaries; guard test checks OAuth binding before any write. Existing publisher/duplicate/manual policy tests are retained.
- Ruff and mypy passed on changed Python. Dashboard lint/typecheck passed during implementation; final Production Build, browser and intercepted POST E2E results follow below. No DB schema change or migration.
- Browser tests must intercept manual POST; development instructions are not a new publication approval. Only the already approved PHP2Shell Job may be recovered in operations.
- Changed files: imports/external-import-workspace.tsx; publishing/page.tsx, publication-manager.tsx, publication-worker-panel.tsx; style.css; e2e/P5-CODEX-078-publishing.spec.ts; blogger_writes.py; publication_worker.py; tests/test_publications.py; test_publication_interval.py; this record. Commit/runtime evidence follows in final section/git log.
