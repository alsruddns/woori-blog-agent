# P5-CODEX-075 — Exact Japanese/Chinese publication policies

- Date: 2026-10-30 KST. Branch develop.
- Read-only inventory: ko/KR Blogger 3321654108096579717 and en/US Blogger 5240203250707821039 already had exact policies. Japanese Blogger 7562596540375659150 (ja) and Chinese Blogger 1931836538202286191 (zh-CN) only had empty-country policies, while their imported localizations are ja/JP and zh-CN/CN. No manuscript or blog language mismatch exists.
- Through authenticated existing /admin/config/profiles and /admin/config/policies, registered ja/JP policy 6df71e32-05b9-4d91-9b0f-de8518218425 and zh-CN/CN policy 258e904d-9c48-4b02-b4a8-5352a5a00171. Both API calls returned 200. Retained the default profile settings/timezone/cron and active=false; no global Auto or Scheduled Auto approval scope changes. Configuration triggers recorded append-only audits. Previous policies remain intact. No migration.
- Standard BCP47 normalization: zh-cn -> zh-CN, zh -> zh. A generic Chinese language is not silently mapped to mainland China. Actual DB manuscript/blog locale remains zh-CN/CN. No foreign-country fallback.
- Actual same-origin manual eligibility GETs: Japanese import 9bd1706b-5e0a-4cb4-a7fd-d4949b9ecad7 and Chinese import 2a5ffdcd-cf23-4f82-a452-48d4de7b1aa0 each HTTP 200, eligible=true, blockers=[]. The existing button still requires the user's checkboxes and final confirmation click. No manual publication POST or new manual Job was sent.
- Scheduled Auto uses the same exact profile language/country join from P5-CODEX-074. Both blog records remain inside the existing enabled four-blog scope; their unresolved source/body eligibility issues remain independent holds, not missing-policy errors.

## Job flow correction

- Existing publication list already required an actual active_job_id for a queued item, but mapped both queued/running Jobs to queued. Added publication_list_flow: remotely verified published, persisted running Job=publishing, persisted queued Job=queued, no Job=review_needed. Expose has_publishing_job/publishing_job_id; running items remain in the active queue view. A status string without a persisted Job ID never implies Worker wait.
- Dashboard now says Worker processing wait / publishing separately and explains that manual Job creation requires the user's public-publish action; eligible state alone is not an actual Job. Scheduled Auto Job creation remains automatic after scoped eligibility.
- Changed files: services/api/woori/publications.py; services/api/tests/test_publications.py; apps/dashboard/app/publishing/publication-manager.tsx; this record. No scheduling, OAuth, manual POST, automatic publisher or content changes.

## Verification

- Focused pytest 61 passed (including four-language exact-country policy, missing-policy safety, manual approval/idempotency, Scheduled Auto queue and Jobless-vs-running read-model regressions). Ruff/mypy and Dashboard ESLint/TypeScript passed.
- Runtime and final commit results are appended after Production Build and targeted application. Actual manual or scheduled publication is not claimed by this configuration/UI task.
