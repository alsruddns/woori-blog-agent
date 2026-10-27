# Approved four-blog Blogger private-draft execution

- Work ID: P5-BLOGGER-DRAFT-EXEC-001
- Date: 2026-10-27 (Asia/Seoul)
- Repository: `C:\Users\achie\git\woori-blog-agent`
- Branch: `develop`
- Authorization: the project owner explicitly approved the four exact payloads and Blog IDs in the user message immediately before this execution.
- Code baseline: `b4b66385270c7544712f6567a85bb4b91513c306` (`Fix : [Blogger] Block duplicate private test drafts`), pushed before the live calls.

## Execution sequence

1. Read the four existing preview ledger entries and confirmed they were pending, had the exact approved fixed title/body, had `isDraft=true`, and referenced one existing full-scope OAuth connection.
2. Before each blog's insert, refreshed the common access proof through the existing OAuth grant. The authenticated account blog listing returned HTTP 200 and all four registered Blog IDs and URLs matched. Account identity remains unverified.
3. The guarded confirmation path fetched each blog's draft list (`status=draft`, Author view) and checked one page for the fixed test title. No matching title existed in any target blog. Each negative duplicate result was recorded in the audit log before insert.
4. Sent exactly one `posts.insert` request per approved target, with `isDraft=true`. No write was retried.
5. Re-read each returned Post ID using the Blogger Author view. Every detail GET returned HTTP 200, the status was draft, and both title and body matched the approved preview.

## Results

| Locale | Blog ID | Post ID | `posts.insert` HTTP | Draft read-back | Created (KST) | Duplicate found |
|---|---:|---:|---:|---|---|---|
| ko | `3321654108096579717` | `3147869148049076326` | 200 | Confirmed; title/body match | 2026-10-27 22:21:39.884302 | No |
| en | `5240203250707821039` | `6200412717175382056` | 200 | Confirmed; title/body match | 2026-10-27 22:21:56.129382 | No |
| zh-CN | `1931836538202286191` | `2489135230154436472` | 200 | Confirmed; title/body match | 2026-10-27 22:22:12.852080 | No |
| ja | `7562596540375659150` | `3922184436060234592` | 200 | Confirmed; title/body match | 2026-10-27 22:22:26.799091 | No |

All four previews transitioned to `succeeded`. The database records each request, insert result, recheck result, Blog ID, Post ID, status, and timestamp. The corresponding `blogger_api_calls` and append-only audit events were queried after execution; each duplicate-check result reports no matching title and one page checked.

## Counts and safety

- Blogger API traffic in this run: 16 successful requests total — 4 account blog-list GETs, 4 draft-list GETs for duplicate checks, 4 `posts.insert` POSTs, and 4 post-detail GETs. Every request returned HTTP 200. OAuth refresh, if needed, is separate from this Blogger API count.
- Test draft writes: exactly 4; one per approved blog. No retries and no matching prior test draft.
- Public publish, update, delete, schedule, and automatic publish requests: 0.
- Current DB snapshot after execution: 360 content versions, 0 publication records, 4 successful live test-draft ledger rows; automatic policy count 0 and publishing-language flag count 0. Existing source content versions were not changed.
- No paid AI or other paid data/API calls were made. The Blogger-only owner cost attestation remains scoped to Blogger; it is not independent Cloud Billing evidence.
- No OAuth secret, access token, refresh token, or account identity was printed or recorded in this report.

## Verification and Git

- Full `scripts/verify.ps1`: passed after the duplicate-check change; pytest 203 passed, Ruff passed, mypy passed, wheel passed, Dashboard ESLint/typecheck/production build passed, and `git diff --check` passed.
- Blogger write authorization: exact user authorization was present; all four writes used the previously approved payloads without modification.
- The implementation baseline was pushed before the calls. This record and the result JSON are committed and pushed separately. `main` was not changed; no branch was created.
