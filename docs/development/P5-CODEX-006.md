# P5-CODEX-006 — Manual / Auto 게시 모드

- 작업 시각: 2026-10-28 (Asia/Seoul)
- 목적: 게시 모드 설정, 보수적 Auto 자격 검사, Manual 요청 상태, 감사 추적을 구현한다.
- 시작 상태: develop at 7bbf26e; 004/005 렌더러·SEO 준비물 확인; existing publisher is Fake-only; operating auto flag and live writer are fail-closed.
- 변경 전 문제: UI had no persisted Manual/Auto configuration or blog/language overrides; publication list did not show exact editorial/publication approval status; app could not expose conservative Auto block reasons.
- 구현: Migration 042 adds scoped preferences with Manual default, limits, timezone, allowlist, excluded topics and an immutable approval=false guard; API stores config plus append-only audit events, resolves blog > language > global, exposes exact editorial and publication approval status, adds one-way emergency stop, and reports Auto eligibility using fail-closed evidence requirements. Existing live Blogger adapter remains disabled and Fake-only simulation is preserved.
- Safety boundary: Auto mode is a stored requested preference only. Operations auto approval is constrained false in schema; live writes remain hard disabled; `publish_ready` is not changed. Migration was not applied to any database in this phase. No Blogger, AI provider, or external API calls were made.
- Validation: see `P5-CODEX-006-results.json`; tests and builds are recorded there with actual results.
- Files: `scripts/042_publication_modes.sql`, `scripts/migrate.py`, `services/api/woori/publication_modes.py`, `services/api/woori/publications.py`, `services/api/tests/test_publications.py`, `services/api/tests/test_publication_modes.py`, Dashboard publication proxy/manager/page/style, `docs/operations/publishing-modes.md`, and results JSON.
- Remaining: apply migration only through approved test/operations procedure; connect each auto eligibility fact to immutable reviewed data; obtain separate operations approval before any live writes; test current admin user/session and actual Dashboard runtime; live Blogger posting is intentionally unverified and prohibited.
