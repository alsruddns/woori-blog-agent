"""Append the fail-closed P5-CODEX-091 run-mode contract to saved local tasks.

This changes prompts only. Automation IDs, schedule, model, project and status
are checked before and after. A backup is retained outside the repository.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import time
import tomllib
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_IDS = (
    "ai", "automation", "automation-2", "automation-3", "automation-4",
    "automation-5", "automation-6", "automation-7", "automation-8",
    "automation-9", "automation-10", "fed-sec", "it-ai", "k-beauty", "k-pop",
)
MARKER = "P5-CODEX-091 RUN MODE AND MANUAL RECOVERY"
MANUAL_RUN_BLOCK = """P5-CODEX-091 RUN MODE AND MANUAL RECOVERY (authoritative execution switch):
Before any duplicate check or research, resolve this exact invocation using the current Automation ID supplied in the invocation header:
  .\\.venv\\Scripts\\python.exe .\\scripts\\resolve-codex-automation-run.py --automation-id <actual-automation-id>
Proceed only if the command returns resolved=true. It inspects the current Codex Desktop session trigger; do not infer mode from the clock, prompt, or missing occurrence metadata.

If execution_mode=scheduled, continue the existing scheduled workflow unchanged. Copy the returned scheduled occurrence fields exactly, validate the configured slot, and use chatgpt_scheduled_export plus the existing scheduled envelope. Preserve this task's ID, RRULE, topic, target blog/language, research rules, validation and approved scheduled Auto policy.

If execution_mode=manual, this is an explicit Desktop Run now. Use the returned manual_origin verbatim; do not create or guess occurrence_id, scheduled_slot, or scheduled provenance. Run the same local duplicate preflight and fresh web research before drafting. Use generation_method=manual_codex_import and schema woori-manual-automation-content-import/1.0 with the ordinary validated content item and returned manual_origin. Set a stable content_id from manual_run_id, target blog ID and language so a retry of this same invocation reuses the identity; a new Run now has a different manual_run_id. If the helper returned the complete recovery_of_* fields for a confirmed usage_limit_exceeded scheduled run, preserve them exactly; otherwise omit the recovery link. Do not replace or mark the failed scheduled run successful.

For both modes, preserve this automation's article topic, language, target, source/claim/rights checks and JSON validation. Skip on an existing matching import/publication or ambiguous local duplicate state. Never import insufficient_evidence, fabricate claims, alter history, create a Publishing Job, enable Auto, approve content, or call Blogger. Manual imports remain human-review only and do not inherit scheduled Auto permission. Save incoming/*.part, validate with scripts/validate-scheduled-import.py, then atomically move to ready/*.ready.json. If the resolver is unresolved or the mode is unknown, stop before research and report the reason."""


def _load(path: Path) -> dict[str, object]:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _replace_prompt_and_time(raw: str, prompt: str, updated_at: int) -> str:
    encoded = json.dumps(prompt, ensure_ascii=False)
    changed, count = re.subn(
        r'(?m)^prompt\s*=\s*"(?:\\.|[^"\\])*"\s*$',
        lambda _match: f"prompt = {encoded}",
        raw,
        count=1,
    )
    if count != 1:
        raise ValueError("automation_prompt_field_not_found_or_ambiguous")
    changed, count = re.subn(r"(?m)^updated_at\s*=\s*\d+\s*$", f"updated_at = {updated_at}", changed, count=1)
    if count != 1:
        raise ValueError("automation_updated_at_field_not_found_or_ambiguous")
    return changed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--automations-root", type=Path, default=Path.home() / ".codex" / "automations")
    parser.add_argument("--backup-root", type=Path, default=Path.home() / ".codex" / "automation-backups")
    parser.add_argument("--manifest", type=Path, default=ROOT / "docs" / "development" / "P5-CODEX-091-prompt-hashes.json")
    args = parser.parse_args()
    paths = {p.parent.name: p for p in args.automations_root.glob("*/automation.toml")}
    if tuple(sorted(paths)) != tuple(sorted(EXPECTED_IDS)):
        raise SystemExit("automation_set_mismatch_refusing_prompt_update")
    timestamp = datetime.now(UTC).isoformat()
    backup = args.backup_root / f"P5-CODEX-091-{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
    report: dict[str, object] = {"work_id": "P5-CODEX-091", "recorded_at": timestamp,
        "automation_ui_crosscheck": "unavailable_native_control_pipe", "automations": []}
    planned: list[tuple[Path, str, dict[str, object], dict[str, object], str, str]] = []
    for automation_id in EXPECTED_IDS:
        path = paths[automation_id]
        raw = path.read_text(encoding="utf-8")
        before = _load(path)
        prompt = str(before.get("prompt", ""))
        if MARKER in prompt:
            if prompt.count(MARKER) != 1:
                raise SystemExit(f"prompt_marker_duplicate:{automation_id}")
            after_prompt = prompt
        else:
            after_prompt = f"{prompt.rstrip()}\n\n{MANUAL_RUN_BLOCK}"
        after_raw = _replace_prompt_and_time(raw, after_prompt, int(time.time() * 1000))
        after = tomllib.loads(after_raw)
        for key in ("id", "kind", "name", "status", "rrule", "model", "reasoning_effort",
                    "execution_environment", "target", "cwds", "created_at"):
            if after.get(key) != before.get(key):
                raise SystemExit(f"automation_field_changed:{automation_id}:{key}")
        if after.get("prompt", "").count(MARKER) != 1:
            raise SystemExit(f"prompt_update_failed:{automation_id}")
        planned.append((path, after_raw, before, after, hashlib.sha256(prompt.encode()).hexdigest(),
                        hashlib.sha256(str(after["prompt"]).encode()).hexdigest()))
    if args.apply:
        backup.mkdir(parents=True, exist_ok=False)
        for path, after_raw, before, after, before_hash, after_hash in planned:
            shutil.copy2(path, backup / f"{path.parent.name}.automation.toml")
            path.write_text(after_raw, encoding="utf-8", newline="\n")
            reread = _load(path)
            if reread != after:
                raise SystemExit(f"saved_automation_verification_failed:{path.parent.name}")
            report["automations"].append({
                "id": path.parent.name, "name": before.get("name"), "status": before.get("status"),
                "rrule": before.get("rrule"), "model": before.get("model"),
                "prompt_sha256_before": before_hash, "prompt_sha256_after": after_hash,
                "prompt_chars_before": len(str(before["prompt"])),
                "prompt_chars_after": len(str(after["prompt"])),
            })
        report["backup_directory"] = str(backup)
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        for path, _, before, after, before_hash, after_hash in planned:
            report["automations"].append({"id": path.parent.name,
                "prompt_sha256_before": before_hash, "prompt_sha256_after": after_hash,
                "rrule": before.get("rrule"), "status": after.get("status")})
    print(json.dumps({"apply": args.apply, "count": len(planned),
                      "backup_directory": str(backup) if args.apply else None,
                      "manifest": str(args.manifest) if args.apply else None,
                      "items": [{"id": x["id"], "prompt_sha256_before": x["prompt_sha256_before"],
                                 "prompt_sha256_after": x["prompt_sha256_after"]} for x in report["automations"]]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
