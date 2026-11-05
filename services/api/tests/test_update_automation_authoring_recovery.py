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
    assert "scripts/automation-research-stage.py" in after["prompt"]
    assert "a missing variable or file is never a reason to stop" in after["prompt"]
    assert "Do not separately run the resolver or duplicate preflight first" in after["prompt"]
    assert after["prompt"].count("P5-CODEX-131 VERIFIED AUTHORING RECOVERY") == 1
    assert after["id"] == before_active["id"]
    assert after["rrule"] == before_active["rrule"]
    assert after["status"] == before_active["status"]
    assert paused_path.read_bytes() == before_paused
    assert Path(report["backup_directory"], "automation-8.automation.toml").exists()


def test_prompt_updater_replaces_old_priority_instead_of_leaving_conflicting_steps(tmp_path) -> None:
    root = tmp_path / "automations"
    active = root / "automation-6"
    old_priority = (
        "P5-CODEX-139 RUN THROUGH THE AUTHORING HANDOFF (highest priority):\n"
        "First command: resolve the invocation. Second command: run preflight.\n\n"
        "Task code: market close\n"
    )
    _write_automation(active, "automation-6", "ACTIVE", str(ROOT), old_priority)
    backup_root = tmp_path / "backups"

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
    after = tomllib.loads((active / "automation.toml").read_text(encoding="utf-8"))

    assert after["prompt"].startswith("P5-CODEX-131 EXECUTE THE AUTHORING RUN")
    assert "First command: resolve the invocation" not in after["prompt"]
    assert "automation-research-stage.py" in after["prompt"]
    assert after["rrule"] == "RRULE:FREQ=DAILY;BYHOUR=9;BYMINUTE=0"
    assert json.loads(applied.stdout)["active_project_automation_count"] == 1


def test_prompt_updater_refreshes_current_priority_without_legacy_boundary(tmp_path) -> None:
    root = tmp_path / "automations"
    active = root / "automation-14"
    prompt = (
        "P5-CODEX-131 EXECUTE THE AUTHORING RUN (highest-priority execution order):\n"
        "Current priority text with no legacy success sentence.\n\n"
        "P5-CODEX-131 VERIFIED AUTHORING RECOVERY (authoritative): old contract.\n\n"
        "P5-CODEX-140 CODEX CLI LIVE RESEARCH (mandatory): old search directions.\n"
    )
    _write_automation(active, "automation-14", "ACTIVE", str(ROOT), prompt)
    result = subprocess.run(
        [
            sys.executable, str(SCRIPT), "--apply", "--automations-root", str(root),
            "--backup-root", str(tmp_path / "backups"),
        ],
        check=True, capture_output=True, text=True,
    )
    report = json.loads(result.stdout)
    assert report["active_project_automation_count"] == 1
    after = tomllib.loads((active / "automation.toml").read_text(encoding="utf-8"))
    assert "opened by the CLI research session" in after["prompt"]
    assert "The excerpt is a CLI-reported quote until the Import Worker retrieves the exact page" in after["prompt"]
