from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "automation-research-stage.py"
SPEC = importlib.util.spec_from_file_location("automation_research_stage", SCRIPT)
assert SPEC and SPEC.loader
stage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stage)


def _preflight(*, mode: str = "manual", local_status: str = "not_found") -> dict:
    invocation = {
        "automation_id": "automation-7",
        "execution_mode": mode,
        "trigger": "automation_cron_run_now" if mode == "manual" else "automation_cron_scheduled",
    }
    if mode == "manual":
        invocation["manual_run_id"] = "codex-manual:automation-7:123e4567-e89b-12d3-a456-426614174000"
    else:
        invocation.update({
            "occurrence_id": "codex-slot:automation-7:20261105T0900KST",
            "scheduled_slot": "2026-11-05T09:00:00+09:00",
        })
    return {
        "status": "unknown",
        "local_status": local_status,
        "remote_status": "not_checked",
        "draft_import_allowed": local_status in {"not_found", "failed_only"},
        "automation_execution": {"invocation": invocation, "contract": {"schema": "fixture"}},
    }


def _args(tmp_path: Path, *, preflight: dict | None = None, package: Path | None = None):
    return {
        "automation_id": "automation-7",
        "category": "general",
        "language_code": "ko",
        "target_country": "KR",
        "target_blog_id": "3321654108096579717",
        "event_group_id": "kpop-issue-2026-11-05",
        "topic": "K-pop current artist activity for Korean readers",
        "root": tmp_path,
        "preflight_dir": tmp_path / "state" / "preflight",
        "package_dir": package or tmp_path / "state" / "research-packages",
    }


def _package(path: Path, *, mode: str = "manual") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "status": "evidence_available",
        "sources": [{"url": "https://example.gov/report", "published_at": "2026-11-04"}],
    }
    if mode == "manual":
        data["manual_run_id"] = "codex-manual:automation-7:123e4567-e89b-12d3-a456-426614174000"
    else:
        data["occurrence_id"] = "codex-slot:automation-7:20261105T0900KST"
    path.write_text(json.dumps(data), encoding="utf-8")


def test_manual_stage_runs_generation_preflight_then_manual_broker_and_preserves_unknown(tmp_path):
    exact_preflight = json.dumps(_preflight(), ensure_ascii=False) + "\n"
    package_path = tmp_path / "state" / "research-packages" / "automation-7-manual-123e4567-e89b-12d3-a456-426614174000.research.json"
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if command[1].endswith("scheduled_duplicate_check.py"):
            return SimpleNamespace(returncode=0, stdout=exact_preflight, stderr="")
        assert command[1].endswith("manual-research-broker.py")
        assert kwargs["input"] == exact_preflight
        _package(package_path)
        return SimpleNamespace(returncode=0, stdout=json.dumps({
            "status": "evidence_available", "path": str(package_path), "source_count": 1,
        }), stderr="")

    result, code = stage.run_stage(**_args(tmp_path), command_runner=fake_run)

    assert code == 0
    assert result["status"] == "evidence_available"
    assert result["execution_mode"] == "manual"
    assert result["local_status"] == "not_found"
    assert result["remote_status"] == "not_checked"
    assert result["overall_status"] == "unknown"
    assert result["article_created"] is False
    assert result["imported"] is False
    assert len(calls) == 2
    assert Path(result["preflight_json_path"]).read_text(encoding="utf-8") == exact_preflight


def test_invalid_blogger_placeholder_is_rejected_before_preflight(tmp_path):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        raise AssertionError("invalid Blogger ID must not reach preflight")

    args = _args(tmp_path)
    args["target_blog_id"] = "<registered Blogger ID>"
    result, code = stage.run_stage(**args, command_runner=fake_run)

    assert code == 2
    assert result["status"] == "blocked"
    assert result["reason"] == "target_blog_id_invalid"
    assert calls == []


def test_scheduled_stage_selects_only_scheduled_broker(tmp_path):
    exact_preflight = json.dumps(_preflight(mode="scheduled")) + "\n"
    package_path = tmp_path / "state" / "research-packages" / "automation-7-20261105T0900KST.research.json"
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command[1])
        if command[1].endswith("scheduled_duplicate_check.py"):
            return SimpleNamespace(returncode=0, stdout=exact_preflight, stderr="")
        assert command[1].endswith("scheduled-research-broker.py")
        assert kwargs["input"] == exact_preflight
        _package(package_path, mode="scheduled")
        return SimpleNamespace(returncode=0, stdout=json.dumps({
            "status": "evidence_available", "path": str(package_path), "source_count": 1,
        }), stderr="")

    result, code = stage.run_stage(
        **_args(tmp_path, package=package_path.parent), command_runner=fake_run,
    )

    assert code == 0
    assert result["execution_mode"] == "scheduled"
    assert commands[-1].endswith("scheduled-research-broker.py")


@pytest.mark.parametrize("local_status", ["unknown", "already_imported", "already_published"])
def test_unclear_or_duplicate_local_preflight_never_calls_research_broker(tmp_path, local_status):
    raw = json.dumps(_preflight(local_status=local_status)) + "\n"
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command[1])
        return SimpleNamespace(returncode=3, stdout=raw, stderr="")

    result, code = stage.run_stage(**_args(tmp_path), command_runner=fake_run)

    assert code == 3
    assert result["status"] == "blocked"
    assert result["local_status"] == local_status
    assert result["remote_status"] == "not_checked"
    assert result["overall_status"] == "unknown"
    assert len(calls) == 1
    assert not (tmp_path / "state" / "preflight").exists()


def test_missing_contract_blocks_broker_and_does_not_guess_mode(tmp_path):
    invalid = _preflight()
    invalid["automation_execution"]["contract"] = None

    def fake_run(_command, **_kwargs):
        return SimpleNamespace(returncode=0, stdout=json.dumps(invalid), stderr="")

    result, code = stage.run_stage(**_args(tmp_path), command_runner=fake_run)

    assert code == 3
    assert result["reason"] == "authoring_contract_unavailable"


def test_existing_preflight_artifact_is_preserved_and_not_overwritten(tmp_path):
    args = _args(tmp_path)
    identity = _preflight()["automation_execution"]["invocation"]["manual_run_id"]
    path = stage._preflight_path("manual", identity, directory=args["preflight_dir"])
    path.parent.mkdir(parents=True)
    path.write_text("preserve original", encoding="utf-8")
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command[1])
        return SimpleNamespace(returncode=0, stdout=json.dumps(_preflight()), stderr="")

    result, code = stage.run_stage(**args, command_runner=fake_run)

    assert code == 3
    assert result["reason"] == "preflight_artifact_already_exists"
    assert path.read_text(encoding="utf-8") == "preserve original"
    assert len(calls) == 1

