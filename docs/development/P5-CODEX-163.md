# P5-CODEX-163 Trends collection cadence update

- **Work ID:** P5-CODEX-163
- **Work time:** 2026-11-18, Asia/Seoul
- **Reason:** The operator requested reducing Google Trends collection cadence from 30 minutes to 10 minutes and applying the change.
- **Existing problem:** Persisted `trend_collection_settings` had collection enabled with a 30-minute interval and no pending change.
- **Purpose:** Change the configured collection cadence to 10 minutes through the authenticated existing settings endpoint, preserving the current in-progress slot and recording the change in the append-only audit log.
- **Before:** `enabled=true`, `interval_minutes=30`, `pending_interval_minutes=null`; most recent completed sweeps were at 17:30 and 18:00 KST with 14 configured regions each. Research Worker PID 21380 was healthy and acknowledged automation controls revision 29.
- **After:** The authenticated endpoint returned HTTP 200. It retained the active 30-minute interval for the current slot and saved `pending_interval_minutes=10`, effective at 18:30 KST (2026-11-18). The settings readback confirmed the pending value and next-run boundary. The API wrote `trend.collection.settings_changed` audit event 733010 in the same transaction. Research Worker remained fresh at revision 29 and reads the persisted collection settings on its normal stage loop; no restart or manual collection call was performed. No historical slot was replayed.
- **Changed files:** `docs/development/P5-CODEX-163.md`.
- **Tests:** No code changed and no test suite was run. The authenticated settings endpoint returned HTTP 200; a subsequent GET confirmed the persisted 10-minute pending cadence and 18:30 KST effective time. Worker heartbeat/revision and latest collection slots were read-only checked.
- **Commit hash:** Documentation-only commit; resolve the full hash with `git log -- docs/development/P5-CODEX-163.md`.
- **Related docs:** `docs/operations/zero-cost-policy.md`; `services/api/woori/trends.py`; `services/api/woori/research_routes.py`; `services/api/woori/research_stages.py`.
- **Remaining issues:** The effective interval remains 30 minutes until the scheduled 18:30 KST boundary, then the configured interval becomes 10 minutes. The collector retains existing per-slot idempotency and provider backoff behavior; this setting change does not bypass them or guarantee a successful provider response.
