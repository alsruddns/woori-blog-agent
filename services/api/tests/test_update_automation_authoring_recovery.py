from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "update-codex-automation-authoring-recovery.py"


def _write_automation(path: Path, automation_id: str, status: str, cwd: str, prompt: str) -> None:
    path.mkdir(parents=True)
    values = {
        "id": automation_id,
        "kind": "cron",
        "name": automation_id,
        "status": status,
        "rrule": "RRULE:FREQ=DAILY;BYHOUR=9;BYMINUTE=0",
        "model": "gpt-6-luna",
        "reasoning_effort": "medium",
        "execution_environment": "local",
        "target": "test",
        "cwds": [cwd],
        "created_at": 1,
        "updated_at": 1,
        "prompt": prompt,
    }
    lines = []
    for key, value in values.items():
        encoded = (
            json.dumps(value, ensure_ascii=False) if isinstance(value, str) else json.dumps(value)
        )
        lines.append(f"{key} = {encoded}")
    (path / "automation.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_prompt_updater_dry_run_then_apply_preserves_schedule_and_paused_task(tmp_path) -> None:
    root = tmp_path / "automations"
    active = root / "automation-8"
    paused = root / "automation-10"
    unrelated = root / "outside"
    _write_automation(active, "automation-8", "ACTIVE", str(ROOT), "Original task prompt")
    _write_automation(paused, "automation-10", "PAUSED", str(ROOT), "Paused Chinese prompt")
    _write_automation(unrelated, "outside", "ACTIVE", str(tmp_path), "Unrelated prompt")
    active_path = active / "automation.toml"
    paused_path = paused / "automation.toml"
    before_active = tomllib.loads(active_path.read_text(encoding="utf-8"))
    before_paused = paused_path.read_bytes()
    backup_root = tmp_path / "backups"

    dry = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--automations-root",
            str(root),
            "--backup-root",
            str(backup_root),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(dry.stdout)["active_project_automation_count"] == 1
    assert tomllib.loads(active_path.read_text(encoding="utf-8")) == before_active
    assert paused_path.read_bytes() == before_paused

    applied = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--apply",
            "--automations-root",
            str(root),
            "--backup-root",
            str(backup_root),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(applied.stdout)
    after = tomllib.loads(active_path.read_text(encoding="utf-8"))
    assert report["active_project_automation_count"] == 1
    assert after["prompt"].startswith("P5-CODEX-131 EXECUTE THE AUTHORING RUN")
    assert after["prompt"].count("P5-CODEX-131 VERIFIED AUTHORING RECOVERY") == 1
    assert after["id"] == before_active["id"]
    assert after["rrule"] == before_active["rrule"]
    assert after["status"] == before_active["status"]
    assert paused_path.read_bytes() == before_paused
    assert Path(report["backup_directory"], "automation-8.automation.toml").exists()
