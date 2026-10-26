# Local operations and recovery

Run commands from repository root. API and Next.js bind only to loopback. Use separate terminals for API, dashboard and worker; Ctrl+C stops them. PostgreSQL is the existing Windows service. No other database or project account is altered.

## Windows scheduling
Review and explicitly run scripts/register-worker.ps1 to create an at-logon task under the current user. It is not automatically registered in Phase 1. IgnoreNew prevents overlapping scheduled instances, failures restart after one minute, and execution time is unlimited. Reboot recovery begins after user logon; unattended pre-logon operation requires a separately configured service account/task. The durable queue preserves jobs during downtime. Worker reconnects every five seconds after DB/network errors, without logging credentials. Unexpected programming errors exit so Task Scheduler can restart; inspect task LastTaskResult. Diagnostic lease recovery records error type/message/location/time and resolution; attempts >=3 terminate failed. Future pipeline steps need explicit failure classifiers and backoff.

## Secret handling
Keep .env, .env.bootstrap, .env.migration and apps/dashboard/.env.local outside Git. Restrict filesystem ACLs to the operating user/administrators; do not share the workspace with untrusted OS users. Runtime reads only .env; owner/admin env files are tool-specific. Archive the bootstrap secret securely outside the workspace once provisioning is verified. Rotate credentials after suspected disclosure. Never paste connection URLs into logs or screenshots.

## Backup and restore
Run `.venv/Scripts/python scripts/backup.py`. It uses project owner credentials, PostgreSQL 16 pg_dump custom format and pg_restore --list validation. It never passes passwords on the command line. Backups contain content/audit data and must be encrypted and copied off-device with access controls. Archive catalog validation is not a restore rehearsal.

Recommended daily backup and weekly alerts on failure/staleness (>26 hours), disk free space (<20%) and database/audit growth. Permanent audit retention means backups grow indefinitely: budget storage, monitor table sizes and expand storage before exhaustion. No automatic deletion is permitted. Manual backup utility is delivered; recurring backup tasks/alerts are not configured yet.

Restore rehearsal: create a new explicitly named `woori_blog_agent_restore_YYYYMMDD` database with project-owner ownership using an administrator. Never target an existing database. Use pg_restore --exit-on-error --no-owner against that new database with owner credentials via PGPASSFILE. Check migration version, table counts, audit event ordering and app read access before any recovery cutover. Do not use --clean on a live database. Preserve the original and compare pending jobs; do not replay publishing effects. Production cutover needs explicit user approval. Restore rehearsal is pending.

## Branches
Only main and develop. Develop receives reviewed/tested changes and pushes. Merge to main requires explicit user approval. No remote deletion required in this initial empty repository. main currently contains policy bootstrap only; GitHub has no configured protection rules.
