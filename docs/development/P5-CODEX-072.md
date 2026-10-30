# P5-CODEX-072 — Country-specific manual publication policy repair

- Date: 2026-10-30 KST. Branch: develop.
- Latest failed request IDs: `8489f222669ec9041e18e54e` and `e4b411b372ac31b4c59d429d`. Both reached Backend POST `/admin/publications/manual-live-requests` and logged `P0001`, `publication_locale_guard`, `exec_stmt_raise`. These are not the previous 42P10 failure.
- The old log formatter omitted timestamps. The log file last-write time was 13:38:49 KST, which bounds the latest record but does not prove its exact request time. The response is reconstructed from the running handler contract (503, `error=Database operation unavailable`, `code=publication_locale_guard`, matching `request_id`); no browser Network capture was available. New DB errors include UTC timestamps.
- Actual DB trigger `publishing_job_locale` invokes `validate_localization_reference()`. Its strict comparison is localization language/country against the publishing policy's profile language/country. The RAISE text is `Localization does not match language/country policy`. `exec_stmt_raise` is PostgreSQL's internal RAISE executor, not the application function.
- FOMC import `b4c45d23-0c74-4b12-92fd-382633093afa`, import version `ed85a5c4-a387-40ad-84c7-8299cddee46f`, content version `65133867-88d3-427a-bc24-b6994625eb38`: language `ko`, country `KR`. Korean Blogger record `9c4c3e67-6a0c-4213-a5f6-79e6e8841eb6` / remote ID `3321654108096579717` is `ko`. There is no language mismatch. The candidate query selected default-country policy `7d624815-4c35-4077-adb6-d70a615d4d07` whose profile country is empty. The POST carries blog/version IDs and exact hashes, not a locale string. Follow-up reviews have no locale field; the failure is the earlier Job INSERT.
- Root cause: `_candidate` silently fell back from `ko/KR` to `ko/empty`. Eligibility reported a policy present, but the Job trigger correctly rejected the mismatch. The previous test also used an empty localization country, so it missed this operating-data structure.

## Changes and configuration

- `services/api/woori/publications.py`: select only exact language/country profiles. Missing exact-country policy produces the existing explicit `publication_policy_missing` blocker before an INSERT.
- `services/api/woori/main.py`: add UTC timestamp to safe DB error logs.
- `services/api/tests/test_publications.py`: exercise actual isolated DB POST for ko/KR, en/US, ja/JP, zh-CN/CN, default-country policy rejection, exact-country success, mismatched blog language rejection, follow-up creation and idempotent replay. External calls remain mocked; each test is forced-rollback isolated. Actual policy blockers are used.
- Used existing authenticated configuration API `/admin/config/profiles` and `/admin/config/policies` to add ko/KR profile and policy `83714eb4-2cb6-49e8-b135-62b1e2d21884` for the same Korean blog. Both returned HTTP 200. Copied existing profile settings and policy timezone/cron. Policy remains inactive and auto_publish_allowed remains false. Existing configuration audit triggers preserve append-only before/after evidence. No source content, existing policy, approval, or Job was rewritten.
- No schema migration: schema 58 and strict country/language trigger remain intact.

## Validation and remaining boundary

- Ruff and mypy passed; scoped pytest 47 passed, including four real DB route transactions with forced rollback. No operational publication POST was generated.
- Before repair, operational Job/approval/follow-up-review counts for the target were all 0; no publishing record/postId/URL existed. There was no partial committed request to recover.
- Publication remains unverified until the user clicks again. Do not call this an operational POST or Blogger publication success.
- Runtime application and commit are recorded by the subsequent Git/runtime follow-up.
