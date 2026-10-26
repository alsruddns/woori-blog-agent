"""Run real Worker lifecycle checks in a disposable PostgreSQL cluster."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import psutil
import psycopg
from dotenv import dotenv_values
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
APP_TOKEN = "isolated-worker-test-token-not-a-secret-0001"


def preflight() -> dict[str, float]:
    memory = psutil.virtual_memory()
    cpu = psutil.cpu_percent(interval=0.5)
    disk = shutil.disk_usage(tempfile.gettempdir())
    available_gib = memory.available / 1024**3
    free_disk_gib = disk.free / 1024**3
    if available_gib < 6 or memory.percent >= 80 or cpu >= 80 or free_disk_gib < 10:
        raise SystemExit("Resource gate closed; isolated Worker verification not started")
    return {
        "ram_total_gib": round(memory.total / 1024**3, 2),
        "ram_available_gib": round(available_gib, 2),
        "ram_used_percent": round(memory.percent, 1),
        "cpu_percent_sample": round(cpu, 1),
        "temp_disk_free_gib": round(free_disk_gib, 2),
    }


def checked(command: list[str], *, env: dict[str, str] | None = None, cwd: Path = ROOT) -> None:
    result = subprocess.run(command, check=False, cwd=cwd, env=env, capture_output=True, text=True, timeout=180)
    if result.returncode:
        raise RuntimeError(f"{Path(command[0]).name} exited {result.returncode}; output suppressed")


def run_worker(args: list[str], env: dict[str, str], *, timeout: int = 20) -> dict[str, float | int]:
    process = subprocess.Popen(
        [str(PYTHON), "-m", "woori.worker", *args], cwd=tempfile.gettempdir(),
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    sampler = psutil.Process(process.pid)
    worker_pid = process.pid
    peak_rss = 0
    peak_cpu = 0.0
    started = time.monotonic()
    try:
        while process.poll() is None and time.monotonic() - started < timeout:
            try:
                children = sampler.children(recursive=True)
                runtime = children[-1] if children else sampler
                worker_pid = runtime.pid
                peak_rss = max(peak_rss, runtime.memory_info().rss)
                peak_cpu = max(peak_cpu, runtime.cpu_percent(interval=None))
            except psutil.Error:
                pass
            time.sleep(0.2)
        if process.poll() is None:
            _stop_owned_process_tree(process)
            raise RuntimeError("Worker lifecycle exceeded its bounded timeout")
        _stdout, stderr = process.communicate(timeout=5)
        error_type = None
        if process.returncode:
            lines = stderr.decode("utf-8", errors="replace").splitlines()
            error_type = lines[-1].split(":", 1)[0][:80] if lines else "unknown_process_error"
        return {
            "launcher_pid": process.pid,
            "worker_pid": worker_pid,
            "exit_code": process.returncode,
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "peak_worker_rss_bytes": peak_rss,
            "peak_worker_cpu_percent_sample": round(peak_cpu, 1),
            "sanitized_error_type": error_type,
        }
    finally:
        if process.poll() is None:
            _stop_owned_process_tree(process)


def _stop_owned_process_tree(process: subprocess.Popen[bytes]) -> None:
    try:
        root = psutil.Process(process.pid)
        for child in reversed(root.children(recursive=True)):
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
    except psutil.NoSuchProcess:
        pass
    if process.poll() is None:
        process.kill()
    process.wait(timeout=5)


def _runtime_pid(process: subprocess.Popen[bytes], timeout: float = 3) -> int:
    root = psutil.Process(process.pid)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and process.poll() is None:
        try:
            children = root.children(recursive=True)
        except psutil.Error:
            children = []
        if children:
            return children[-1].pid
        time.sleep(0.05)
    return process.pid


def wait_for_status(
    connect_url: str, service: str, status: str, timeout: float = 8,
    expected_pid: int | None = None,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with psycopg.connect(connect_url, row_factory=dict_row) as conn:
            row = conn.execute(
                "SELECT process_id,status,last_seen_at FROM worker_heartbeats WHERE service_name=%s",
                (service,),
            ).fetchone()
        if row and row["status"] == status and (expected_pid is None or row["process_id"] == expected_pid):
            return dict(row)
        time.sleep(0.1)
    raise RuntimeError(f"Worker heartbeat did not reach expected state: {service}/{status}")


def main() -> None:
    before = preflight()
    if not PYTHON.exists():
        raise SystemExit("Project Python tools are unavailable")
    admin_url = dotenv_values(ROOT / ".env.migration").get("MIGRATION_DATABASE_URL", "")
    ops_url = dotenv_values(ROOT / ".env").get("DATABASE_URL") or "postgresql://woori_app@127.0.0.1:5432/woori_blog_agent"
    if not admin_url:
        raise SystemExit("Project-scoped migration connection is unavailable")

    schema = "wba_worker_test_" + uuid.uuid4().hex[:12]
    app_test_url = make_conninfo(ops_url, options=f"-csearch_path={schema}")
    keys = {name: "worker-" + name + "-" + uuid.uuid4().hex for name in ("normal", "dedupe", "lease", "terminal")}
    results: dict[str, object] = {
        "phase": "3.9-S", "kind": "isolated_worker_real_process",
        "captured_at": datetime.now(UTC).isoformat(), "preflight": before,
        "isolation": "temporary schema-only search_path; diagnostic-only worker",
    }
    schema_created = False
    try:
        with psycopg.connect(admin_url, row_factory=dict_row) as conn:
            identity = conn.execute(
                "SELECT current_database() AS name,inet_server_addr()::text AS address"
            ).fetchone()
            if not identity or identity["name"] != "woori_blog_agent" or identity["address"].split("/")[0] not in {"127.0.0.1", "::1"}:
                raise SystemExit("Refusing to create a test schema outside the local project PostgreSQL database")
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            schema_created = True
            conn.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(schema)))
            migration_files = sorted((ROOT / "scripts").glob("[0-9][0-9][0-9]_*.sql"))
            if len(migration_files) != 24 or migration_files[-1].name != "024_evaluation_isolation_quotas.sql":
                raise RuntimeError("Expected complete schema migrations 001 through 024")
            for migration in migration_files:
                content = migration.read_text(encoding="utf-8").replace("SCHEMA public", "SCHEMA " + schema)
                conn.execute(content, prepare=False)
            conn.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO woori_app").format(sql.Identifier(schema)))
            conn.execute("UPDATE pipeline_controls SET evaluation_isolated=true")
            normal_id = conn.execute(
                "INSERT INTO job_runs(idempotency_key,task_kind) VALUES (%s,'diagnostic') RETURNING id",
                (keys["normal"],),
            ).fetchone()["id"]
            conn.execute("INSERT INTO job_runs(idempotency_key,task_kind) VALUES (%s,'diagnostic') ON CONFLICT DO NOTHING", (keys["dedupe"],))
            conn.execute("INSERT INTO job_runs(idempotency_key,task_kind) VALUES (%s,'diagnostic') ON CONFLICT DO NOTHING", (keys["dedupe"],))
            lease_id = conn.execute(
                """INSERT INTO job_runs(idempotency_key,task_kind,status,attempts,lease_until)
                VALUES (%s,'diagnostic','running',1,now()-interval '1 minute') RETURNING id""",
                (keys["lease"],),
            ).fetchone()["id"]
            terminal_id = conn.execute(
                """INSERT INTO job_runs(idempotency_key,task_kind,status,attempts,lease_until)
                VALUES (%s,'diagnostic','running',3,now()-interval '1 minute') RETURNING id""",
                (keys["terminal"],),
            ).fetchone()["id"]

        worker_env = dict(os.environ)
        worker_env.update({"DATABASE_URL": app_test_url, "ADMIN_TOKEN": APP_TOKEN,
                           "PYTHONPATH": str(ROOT / "services" / "api")})
        results["migration"] = "024 in isolated schema"
        results["normal_worker"] = run_worker(["--diagnostic-only", "--run-seconds", "12"], worker_env)
        if results["normal_worker"]["exit_code"] != 0:
            raise RuntimeError("Normal Worker exited abnormally")
        wait_for_status(
            app_test_url, "research_worker", "stopped",
            expected_pid=int(results["normal_worker"]["worker_pid"]),
        )
        with psycopg.connect(app_test_url, row_factory=dict_row) as conn:
            run_ids = [normal_id, lease_id, terminal_id]
            checks = conn.execute("SELECT id,status,attempts FROM job_runs WHERE id=ANY(%s)", (run_ids,)).fetchall()
            dedupe = conn.execute("SELECT count(*) AS n FROM job_runs WHERE idempotency_key=%s", (keys["dedupe"],)).fetchone()["n"]
            events = conn.execute(
                "SELECT event_type,count(*) AS n FROM audit_events WHERE run_id=ANY(%s) GROUP BY event_type",
                (run_ids,),
            ).fetchall()
            if conn.execute("SELECT current_schema() AS name").fetchone()["name"] != schema:
                raise RuntimeError("Worker test connection did not stay inside its isolated schema")
            by_id = {row["id"]: row for row in checks}
            if dedupe != 1 or by_id[normal_id]["status"] != "succeeded" or by_id[normal_id]["attempts"] != 1:
                raise RuntimeError("Normal completion or idempotency check failed")
            if by_id[lease_id]["status"] != "succeeded" or by_id[lease_id]["attempts"] != 2:
                raise RuntimeError(
                    "Expired lease was not recovered within bounded retry policy: "
                    f"status={by_id[lease_id]['status']} attempts={by_id[lease_id]['attempts']}"
                )
            if by_id[terminal_id]["status"] != "failed" or by_id[terminal_id]["attempts"] != 3:
                raise RuntimeError("Maximum-attempt lease did not terminalize")
            event_counts = {row["event_type"]: row["n"] for row in events}
            if event_counts.get("run.completed", 0) < 2 or event_counts.get("run.failed", 0) != 1:
                raise RuntimeError("Expected completion/failure audit events were not recorded")
        results["jobs"] = {
            "normal": "succeeded_once",
            "lease_expired_attempt_1": "recovered_and_succeeded_attempt_2",
            "lease_expired_attempt_3": "failed_terminally",
            "duplicate_idempotency_rows": dedupe,
            "audit_event_counts": event_counts,
        }
        results["abrupt_worker"] = _abrupt_stop_and_recover(app_test_url, worker_env)

        evaluation_env = dict(worker_env)
        evaluation_env["WOORI_OPERATION_DATABASE_URL"] = ops_url
        denied = run_worker(["--evaluation", "--run-seconds", "1"], evaluation_env)
        if denied["exit_code"] == 0:
            raise RuntimeError("Evaluation worker accepted a schema-only database as a separate database")
        results["evaluation_worker"] = {
            "exit_code": denied["exit_code"],
            "result": "correctly_refused_same_physical_database",
        }
        with psycopg.connect(app_test_url, row_factory=dict_row) as conn:
            if conn.execute("SELECT count(*) AS n FROM worker_heartbeats WHERE service_name='evaluation_worker'").fetchone()["n"]:
                raise RuntimeError("Refused evaluation worker wrote a heartbeat")
        with psycopg.connect(admin_url, row_factory=dict_row) as conn:
            leaked = conn.execute(
                "SELECT count(*) AS n FROM public.job_runs WHERE idempotency_key=ANY(%s)",
                (list(keys.values()),),
            ).fetchone()["n"]
            if leaked:
                raise RuntimeError("Test queue rows leaked into the operational public schema")
        results["operational_public_schema_rows_for_test_keys"] = 0
    finally:
        if schema_created:
            with psycopg.connect(admin_url) as conn:
                conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
            with psycopg.connect(admin_url, row_factory=dict_row) as conn:
                remains = conn.execute("SELECT to_regnamespace(%s) AS schema", (schema,)).fetchone()["schema"]
                if remains is not None:
                    raise RuntimeError("Temporary Worker schema cleanup failed")
    output_dir = ROOT / "docs" / "development"
    output_path = output_dir / f"P3-9S-worker-{uuid.uuid4()}.json"
    output_path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"artifact": str(output_path.relative_to(ROOT)), "worker_checks": results}, ensure_ascii=True))

def _abrupt_stop_and_recover(app_url: str, env: dict[str, str]) -> dict[str, object]:
    process = subprocess.Popen(
        [str(PYTHON), "-m", "woori.worker", "--diagnostic-only"], cwd=tempfile.gettempdir(), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    try:
        runtime_pid = _runtime_pid(process)
        try:
            wait_for_status(app_url, "research_worker", "running", expected_pid=runtime_pid)
        except RuntimeError:
            with psycopg.connect(app_url, row_factory=dict_row) as conn:
                recorded = conn.execute(
                    "SELECT process_id,status,last_error_category FROM worker_heartbeats WHERE service_name='research_worker'"
                ).fetchone()
            _stop_owned_process_tree(process)
            _stdout, stderr = process.communicate(timeout=5)
            error_lines = stderr.decode("utf-8", errors="replace").splitlines()
            sanitized = error_lines[-1].split(":", 1)[0][:80] if error_lines else "no_stderr"
            raise RuntimeError(
                "New Worker did not publish its heartbeat: "
                f"expected_pid={runtime_pid} recorded={recorded} stderr_type={sanitized}"
            ) from None
        with psycopg.connect(app_url, row_factory=dict_row) as conn:
            before = conn.execute(
                "SELECT process_id,last_seen_at FROM worker_heartbeats WHERE service_name='research_worker'"
            ).fetchone()
        if runtime_pid != process.pid:
            psutil.Process(runtime_pid).kill()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _stop_owned_process_tree(process)
        else:
            _stop_owned_process_tree(process)
        with psycopg.connect(app_url, row_factory=dict_row) as conn:
            after = conn.execute(
                "SELECT process_id,status FROM worker_heartbeats WHERE service_name='research_worker'"
            ).fetchone()
        if after["process_id"] != runtime_pid or after["status"] != "running":
            raise RuntimeError(
                "Abrupt termination heartbeat state mismatch: "
                f"pid={after['process_id']} expected_pid={runtime_pid} status={after['status']}"
            )
        restarted = run_worker(["--diagnostic-only", "--run-seconds", "12"], env)
        final = wait_for_status(
            app_url, "research_worker", "stopped", expected_pid=int(restarted["worker_pid"]),
        )
        if int(final["process_id"]) == runtime_pid:
            raise RuntimeError("Restart did not replace the old Worker process identity")
        with psycopg.connect(app_url, row_factory=dict_row) as conn:
            transitions = conn.execute(
                "SELECT count(*) AS n FROM audit_events WHERE event_type='worker.status.changed'"
            ).fetchone()["n"]
        return {
            "abrupt_pid": runtime_pid,
            "abrupt_heartbeat_status": after["status"],
            "restart": restarted,
            "final_status": "stopped",
            "heartbeat_transitions": transitions,
            "prior_last_seen": before["last_seen_at"].isoformat(),
        }
    finally:
        if process.poll() is None:
            _stop_owned_process_tree(process)


if __name__ == "__main__":
    main()
