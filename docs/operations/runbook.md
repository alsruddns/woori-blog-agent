# Local operations and recovery

Run commands from repository root. API and Next.js bind only to loopback. Use separate terminals for API, dashboard and worker; Ctrl+C stops them. PostgreSQL is the existing Windows service. No other database or project account is altered.

## Windows scheduling
Phase 2 registered WooriBlogAgent-Worker and WooriBlogAgent-Backup through scripts/register-maintenance.ps1 under the current user with Interactive/Limited privileges and hidden windows. IgnoreNew prevents overlap. Failures restart after one minute, up to three times. Worker execution is unlimited; Backup is limited to one hour. Worker starts at logon; Backup runs at logon and daily 03:00. Unattended pre-logon/logged-out operation is not supported. Registration refuses to overwrite an existing task. The actual durable diagnostic job completed successfully and Backup LastTaskResult was 0.

Worker reconnects every five seconds after DB/network errors without logging credentials. Unexpected programming errors exit for Task Scheduler restart. Lease recovery records safe error metadata; attempts >=3 terminate failed. The Worker still performs diagnostics only, never Google writes or AI calls. API and Dashboard remain manual start scripts on 8100/3100.

## Secret handling
Keep .env, .env.bootstrap, .env.migration and apps/dashboard/.env.local outside Git. Restrict filesystem ACLs to the operating user/administrators; do not share the workspace with untrusted OS users. Runtime reads only .env; owner/admin env files are tool-specific. Archive the bootstrap secret securely outside the workspace once provisioning is verified. Rotate credentials after suspected disclosure. Never paste connection URLs into logs or screenshots.

## Backup and restore
Run `.venv/Scripts/python scripts/backup.py`. It uses project owner credentials, PostgreSQL 16 pg_dump custom format and pg_restore --list validation. It never passes passwords on the command line. Backups contain content/audit data and must be encrypted and copied off-device with access controls. Archive catalog validation is not a restore rehearsal.

maintenance.py now runs daily backups and writes backups/health.json plus audit events. Dashboard warns on failure/staleness (>26 hours) and disk free space (<20%). A successful backup with a disk warning exits successfully to avoid pointless re-backups; a failed backup exits nonzero for bounded scheduler retries. External notifications are not configured. Permanent retention grows storage indefinitely; expand storage or plan an approved separate backup target. No automatic deletion is permitted.

scripts/restore-rehearsal.py completed an actual restore into a fresh woori_blog_agent_restore_<date>_<random> database. It exports a repeatable-read snapshot, verifies the current schema version, content, editorial revision/review, publishing and audit table counts, and audit UPDATE protection, then removes only the database it created after checking its prefix and owner. Existing databases are never restore targets. Creation/cleanup use the existing localhost administrator pgpass; no .env.bootstrap credential is used by runtime. Original data is not overwritten. Production recovery/cutover still requires user approval. Encrypted off-device backups and key recovery rehearsal remain operational follow-up work.

## Branches
Only main and develop. Develop receives reviewed/tested changes and pushes. Merge to main requires explicit user approval. No remote deletion required in this initial empty repository. main currently contains policy bootstrap only; GitHub has no configured protection rules.

## Multilingual operations
Back up before running migrate.py; the current schema is version 32. Review migrations and use only .env.migration owner credentials. Runtime remains woori_app. Do not rerun bootstrap against an existing installation.

Use /config on port 3100. Deactivate languages/blogs to pause selection; existing content and historical publishing/audit rows remain. Country profile saves replace all policy text fields for that language/country. Blog URL/language and language code are immutable identities. Current registration accepts only HTTPS blogspot.com roots. Phase 2 /blogger resolves IDs through Google after consent and verified AUTHOR reads; never guess IDs or manually fill connection evidence.

All capabilities and automatic publication remain blocked in Phase 1. Setting a schedule or marking a policy active has no external effect. Task Scheduler still runs diagnostic jobs only. Readiness is reported per profile and blog; missing adapter support cannot be bypassed by a configuration flag. Search performance view remains empty until an authorized collector is implemented.

Tests use the owner account only inside rolled-back schema/history verification transactions; general API/Worker paths do not read .env.migration or .env.bootstrap. No actual publication or simulated remote post is persisted by multilingual tests.

## Ports, OAuth and restart checks

Dashboard 127.0.0.1:3100, API 127.0.0.1:8100, PostgreSQL localhost:5432. Do not occupy/stop another project's 3000/8000. The browser uses same-origin Next BFF; API CORS stays disabled. Callback URI is http://127.0.0.1:3100/api/blogger/callback. Use the same browser and 127.0.0.1 host throughout OAuth. See [Google setup](google-oauth.md).

Reboot test procedure (actual reboot not performed): record a queued diagnostic run and its audit ID; let the user reboot and log in; check both tasks' triggers, LastRunTime, state and LastTaskResult; verify the same run reaches succeeded with start/completion audit events, or a stale lease is recovered; verify backup freshness/health.json; start API/Dashboard manually; test read-only Google connection if authorized. Do not create actual publishing work or replay remote effects. An unattended service account requires a separate reviewed setup; no Windows password was requested or saved.
