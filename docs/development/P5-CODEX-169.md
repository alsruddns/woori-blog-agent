# P5-CODEX-169 Automatic publication hold explanation

- Work ID/time: P5-CODEX-169, 2026-11-20 Asia/Seoul.
- Reason: The publication list displayed a generic automatic-publication failure twice and did not show the promised technical code.
- Before: Recent eligibility events included `high_impact_topic_requires_review` for Trends content, including safety recall, medical, death and litigation topics. These were review holds before a Publishing Job rather than proven Blogger write failures. Other history included `blog_or_oauth_not_verified`, so the exact report cannot be assigned to one event without the article identity. Current six active target blogs have connected OAuth and verified connection records; a read-only check does not prove a LIVE write.
- After: Show a specific high-impact review explanation and next step, identify this pre-job case as a review hold, display the actual technical reason code, translate the eligibility stage, and suppress duplicate presentation of the primary reason. The existing risk classification, publication gates, settings, jobs, historical audit events and Blogger data are unchanged.
- Files: `apps/dashboard/app/publishing/publication-messages.ts`, `apps/dashboard/app/publishing/publication-manager.tsx`, this record.
- Related: `docs/development/P5-CODEX-168.md`, `services/api/woori/trends_publication.py`. Commit: see git log for this record.
- Remaining: The user-provided text does not identify a manuscript. Separately, scheduled import retry logs show the P167 application/DB constraint mismatch (`non_trends_fact_check_timestamp_required`); it is not this identified Trends eligibility reason and was not altered or replayed in this change. No post-change public write is asserted.

## Service reflection

- Applied Dashboard commit `f03ef54ca20a44bb0b47fdbd17f50df36bdc9bd8` after lint, typecheck, production build and diff validation passed. Only Dashboard was gracefully restarted; API and both Workers remained running. PostgreSQL start/completion audit events were appended.
- Browser verification on `/publishing?view=auto_failure` found a real high-impact review-hold row; the specific explanation and exact code appeared once, and the row displayed review hold. No publication or policy mutation was initiated. Other entries can have different reasons; the original user-supplied text did not identify one.
