# P5-CODEX-161 Publication Worker diagnostic and policy application

- **Work ID:** P5-CODEX-161
- **Work time:** 2026-11-18, Asia/Seoul
- **Reason:** The operator requested applying the Worker after manual and automatic publication controls showed "Worker application pending or connection failed".
- **Existing problem:** Publication Worker PID 39452 repeatedly reported SQLSTATE 42883 (`UndefinedFunction`) and its heartbeat was `degraded`. It had read controls revision 29, but the Automation UI correctly treated publication controls as unapplied. Previous logs intentionally omitted the database message, preventing diagnosis.
- **Purpose:** Preserve fail-closed publication behavior while emitting only a safe PostgreSQL type/operator signature for SQLSTATE 42883, so the failing database expression can be identified and repaired.
- **Before:** `db_function=op_error`, SQLSTATE 42883, with no safe detail to distinguish the missing operator/function. Global interval 10 and six Trends language permissions were stored, but no Publication Worker policy was effective.
- **After (diagnostic implementation):** Added `safe_database_error_hint()` to Publication Worker and included its sanitized output in cycle-failure logs. It reports only operator/type or function/type signatures, never SQL text, parameters, values, or raw database messages. Added focused tests for signature extraction and omission of other error text. The Worker still needs graceful reflection and a fresh heartbeat; a SQL repair remains pending until the sanitized runtime signature identifies the failing expression.
- **Changed files:** `services/api/woori/publication_worker.py`; `services/api/tests/test_worker_runtime.py`; `docs/development/P5-CODEX-161.md`.
- **Tests:** `pytest services/api/tests/test_worker_runtime.py -q`: 4 passed. Ruff passed. Python compileall passed. `git diff --check` passed. Pytest emitted only a cache permission warning for `.pytest_cache`.
- **Commit hash:** To be connected by the following `git log` entry after commit and push.
- **Related docs:** `docs/development/P5-CODEX-159.md`; `docs/development/P5-CODEX-160.md`; `scripts/apply-verified-changes.ps1`.
- **Remaining issues:** Run change-scoped verified reflection for the Publication Worker, capture the sanitized SQLSTATE 42883 signature, fix the underlying database expression/schema mismatch, then verify a fresh running heartbeat and revision 29 policy application. Respect the active Blogger restriction/quota backoff. Do not force-kill processes or create public writes as a diagnostic. No main merge or deployment is authorized.
