# Changelog

## Unreleased - Phase 2 - 2026-10-26

- Verify live readonly OAuth and all four configured Blogger IDs, account membership, URLs and empty post lists.
- Fix Google HTTP 400 caused by sending an empty first-page token; normalize omitted post items to an empty list.
- Add authenticated account-blog discovery with account-scoped audit/quota and refresh successful read timestamps.
- Expand live verification with bounded pagination, per-blog failures and immutable verification events (P2-003).
- Add readonly Google OAuth, encrypted tokens, refresh/revocation, browser-bound state and PKCE.
- Add Blogger GET/ID/post verification, safe API audit/errors, language quotas and Korean management UI.
- Add Mock-only mutation protocols with durable duplicate/uncertain-write blocking and local content versions.
- Move Dashboard/API to 3100/8100 and matching OAuth callback; keep PostgreSQL 5432.
- Verify isolated restore, register/test Worker and daily backup, and display local storage/backup warnings.
- Resolve deprecated TestClient httpx usage with httpx2. Keep paid AI and production writes blocked.

## 0.1.0 - 2026-10-26
- Establish main/develop policy and ten mandatory Codex rules.
- Add local Next.js dashboard, authenticated FastAPI API and durable diagnostic worker.
- Add isolated PostgreSQL schema, immutable audit and content versions.
- Block AI calls and Blogger publishing; add tests and operational documentation.

## Unreleased - multilingual extension - 2026-10-26
- Replace four-language runtime lists with BCP 47 language registration and country profiles.
- Register provided Blogspot URLs without inventing Google Blog IDs or making Blogger requests.
- Add normalized localizations, publishing/SEO/metrics schemas, reference guards and configuration audit triggers.
- Add local configuration UI/API, category/glossary/schedule settings and fail-closed readiness reporting.
- Preserve legacy content/audit history and summary language-code response compatibility.
