"""Append the P131/P140 recovery contracts to active project Automation prompts.

Dry-run is the default. This edits prompt text only; it never registers a task
or changes its ID, schedule, model, target, status, or working directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tomllib
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKER = "P5-CODEX-131 VERIFIED AUTHORING RECOVERY"
PRIORITY_MARKER = "P5-CODEX-131 EXECUTE THE AUTHORING RUN"
SEARCH_MARKER = "P5-CODEX-140 CODEX CLI LIVE RESEARCH"
TARGET_ID_HINTS = {
    "automation-2": (
        "For automation-2 (Japan market close, ja/JP), the current active Blogger mapping is "
        "7562596540375659150. Use that numeric ID only while the active ja/JP mapping still "
        "matches; if it changes, verify the current registered mapping before running."
    ),
}
UNRESOLVED_TOPIC_HINTS = {
    "automation-16": (
        "The most recent automation-16 preflight (2026-11-04 20:20 KST) passed local duplicate "
        "checks for the still-unfinished topic `Brazil fiscal framework and inflation-interest "
        "rate outlook`, with event-group ID `br-economy-2026-11-04`; it created no research "
        "package, manuscript or Import. When continuing that exact unresolved topic, pass that "
        "topic and event-group ID unchanged to the research-stage command, then verify it with "
        "current sources before drafting. Do not replace the ID with a new slot/date ID. If a "
        "new, distinct topic is explicitly selected, give it its own stable issue-based ID."
    ),
}
PRIORITY = fr"""{PRIORITY_MARKER} (highest-priority execution order):
This turn must execute the current Automation, not only diagnose it. Automation memory is optional. If CODEX_HOME is unset, look only at `$env:USERPROFILE/.codex/automations/<this Automation ID>/memory.md` when it exists; a missing variable or file is never a reason to stop. Keep pre-work short and do not reread long policy documents.

The first work command after reading this prompt MUST be one call to `scripts/automation-research-stage.py` using this Automation's exact ID, category, language, target country, registered Blogger ID, stable event-group ID, and exact topic. Example PowerShell shape:
`& ./.venv/Scripts/python.exe ./scripts/automation-research-stage.py --automation-id "<ID>" --category "<politics|economy|technology|general>" --language-code "<BCP-47>" --target-country "<ISO>" --target-blog-id "<registered Blogger ID>" --event-group-id "<stable issue key>" --topic "<exact topic>"`
The angle-bracket values above are examples only: replace every placeholder before running. `--target-blog-id` must be the exact registered Blogger numeric ID (5–32 digits) for this Automation's existing language/blog mapping; never pass the literal `<registered Blogger ID>`, a blog name, URL, or a guessed value. Confirm the ID from this Automation's existing saved task details or a prior successful Import for the same target. If the exact registered ID cannot be established, stop before the request and report `target_blog_id_unavailable`; do not attempt the preflight with a placeholder. The local CLI rejects nonnumeric IDs before sending an HTTP request.
This fixed command performs the exact-trigger resolver, generation duplicate preflight, saves the exact eligible preflight response, and invokes the scheduled or manual ChatGPT-auth Codex research broker in the SAME Automation turn. Do not separately run the resolver or duplicate preflight first. Keep the returned process/session ID and poll that same command to its terminal JSON result. Do not stop after a clear preflight: continue only when the command returns `status=evidence_available`; then read its `research_package_path` and `preflight_json_path`, write the correctly typed envelope, validate it, and hand it off. If the stage returns blocked, report its exact reason and create no unsupported article. A `remote_status=not_checked` or overall `unknown` is preserved and remains a publication-time recheck; it does not block an eligible local draft. The scheduled and manual envelopes must retain their distinct resolver-issued identities. The broker creates evidence only; it does not create an article, Import, Publishing Job or Blogger write.

"""
CONTRACT = f"""\n\n{MARKER} (authoritative for this invocation):
First use the one-command research stage above; it internally runs `scripts/resolve-codex-automation-run.py` through the generation preflight and chooses the matching fixed broker. Only the exact current resolver-confirmed `automation_cron_scheduled` or official Desktop `automation_cron_run_now` is valid. A composer/development turn, old session or claimed trigger is not an Automation run. Scheduled mode retains the exact occurrence and uses `chatgpt_scheduled_export`; Run now retains the exact `manual_origin` and uses `manual_codex_import` with `woori-manual-automation-content-import/1.0`, never a scheduled slot. The common `scripts/validate-scheduled-import.py` validates both envelope types.
Only local `not_found` or `failed_only` with `draft_import_allowed=true` permits a new draft. Preserve `remote_status=not_checked` and overall `unknown`; remote uniqueness is not established and must be rechecked before publication. Do not use the historical pending saver for a new article. If an exact same-run research package already exists, the fixed stage reuses it without invoking Codex again. Existing same-run preflight artifacts are immutable; never overwrite them.
Use current evidence from the returned package. Never invent sources, dates, excerpts, facts or claims. If no useful verified facts remain, do not create an article. Otherwise write the complete UTF-8 envelope with source metadata and claim links to a unique `incoming/<name>.part`, validate it with `scripts/validate-scheduled-import.py`, and invoke `scripts/handoff-automation-manuscript.py <incoming.part> --preflight-json <returned preflight_json_path>`. The handoff rechecks the current invocation and exclusive ready delivery. A ready file is not Research Import; verify its Import receipt separately. Do not overwrite files, replay old slots, create a second original, make a Publishing Job or call Blogger. Preserve this task's ID, topic, language, target, RRULE, model and operating policy; do not create, delete, pause or reschedule any Automation.
"""

SEARCH_CONTRACT = f"""\n\n{SEARCH_MARKER} (mandatory live-research stage):
The fixed research command is available in this repository. Do not wait for a browser search tool or report the CLI unavailable without running `scripts/automation-research-stage.py`. It invokes the official installed Codex CLI with `--search` using the existing ChatGPT login through the fixed isolated broker. No API key, metered API, paid credit, arbitrary HTTP client, alternate provider or guessed browser command is permitted.
Select `politics` only for U.S. policy topics relevant to the White House feed, `economy` only for U.S. BLS/Federal Reserve topics, `technology` only for U.S. NIST cybersecurity topics, and `general` otherwise. The stage chooses `scripts/scheduled-research-broker.py` only for its resolver-confirmed scheduled trigger and `scripts/manual-research-broker.py` only for the exact official Desktop Run now trigger. It preserves the exact execution identity and the preflight's original remote/overall statuses.
Continue in the SAME turn after `status=evidence_available`. Use the returned immutable Research Package, `preflight_json_path`, and actual `research_engine`. Every selected source URL must have been opened by the CLI research session. The excerpt is a CLI-reported quote until the Import Worker retrieves the exact page and verifies it; do not label it independently verified before that check. Do not stop after research: finish the article envelope, validation, exclusive handoff and confirm Import Receipt. The Publication Worker separately evaluates eligible new scheduled Imports and may publish them under the active scoped policy; never create a Publishing Job or call Blogger from this Desktop task. If the CLI reports an account usage limit, authentication, capacity or timeout failure, stop with its concrete reason; do not retry automatically, switch to RSS except where the existing broker explicitly returns an approved fallback, use an API key, purchase credits or disguise the failure. Preserve all IDs, schedules, topic, language, target and policy; never replay an old occurrence.
"""


def _load(path: Path) -> dict[str, object]:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _replace_prompt(raw: str, prompt: str, updated_at: int) -> str:
    encoded = json.dumps(prompt, ensure_ascii=False)
    changed, count = re.subn(
        r'(?m)^prompt\s*=\s*"(?:\\.|[^"\\])*"\s*$',
        lambda _match: f"prompt = {encoded}",
        raw,
        count=1,
    )
    if count != 1:
        raise ValueError("automation_prompt_field_not_found_or_ambiguous")
    changed, count = re.subn(
        r"(?m)^updated_at\s*=\s*\d+\s*$", f"updated_at = {updated_at}", changed, count=1
    )
    if count != 1:
        raise ValueError("automation_updated_at_field_not_found_or_ambiguous")
    return changed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--automations-root", type=Path, default=Path.home() / ".codex" / "automations"
    )
    parser.add_argument(
        "--backup-root", type=Path, default=Path.home() / ".codex" / "automation-backups"
    )
    args = parser.parse_args()
    configs: list[tuple[Path, bytes, dict[str, object]]] = []
    seen: set[str] = set()
    for path in args.automations_root.rglob("automation.toml"):
        raw = path.read_bytes()
        config = tomllib.loads(raw.decode("utf-8"))
        cwds = config.get("cwds")
        if not isinstance(cwds, list) or not any(
            isinstance(cwd, str) and Path(cwd).resolve(strict=False) == ROOT.resolve()
            for cwd in cwds
        ):
            continue
        automation_id = config.get("id")
        if (
            not isinstance(automation_id, str)
            or path.parent.name != automation_id
            or automation_id in seen
        ):
            raise ValueError("automation_id_missing_or_ambiguous")
        seen.add(automation_id)
        if config.get("kind") == "cron" and config.get("status") == "ACTIVE":
            configs.append((path, raw, config))
    if not configs:
        raise ValueError("no_active_project_automations_found")

    timestamp = int(datetime.now(UTC).timestamp() * 1000)
    planned: list[tuple[Path, bytes, dict[str, object], bytes, str, str]] = []
    immutable_fields = (
        "id",
        "kind",
        "name",
        "status",
        "rrule",
        "model",
        "reasoning_effort",
        "execution_environment",
        "target",
        "cwds",
        "created_at",
    )
    for path, raw, before in configs:
        prompt = before.get("prompt")
        if not isinstance(prompt, str):
            raise TypeError(f"automation_prompt_missing:{path.parent.name}")
        if prompt.count(PRIORITY_MARKER) > 1:
            raise ValueError(f"automation_priority_marker_duplicate:{path.parent.name}")
        if prompt.count(MARKER) > 1:
            raise ValueError(f"automation_contract_marker_duplicate:{path.parent.name}")
        if prompt.count(SEARCH_MARKER) > 1:
            raise ValueError(f"automation_search_marker_duplicate:{path.parent.name}")
        updated_prompt = prompt
        if updated_prompt.startswith(PRIORITY_MARKER):
            old_priority_end = updated_prompt.find(
                "Don't claim success without verifying files and Import receipt."
            )
            if old_priority_end < 0:
                # Newer prompt revisions may already have replaced the older
                # fixed prose boundary. Use the next explicit contract marker
                # so the authoring priority can still be refreshed safely.
                contract_boundary = updated_prompt.find("\n\n" + MARKER)
                if contract_boundary < 0:
                    contract_boundary = updated_prompt.find("\n\n" + SEARCH_MARKER)
                if contract_boundary < 0:
                    raise ValueError(f"automation_priority_boundary_missing:{path.parent.name}")
                updated_prompt = PRIORITY + updated_prompt[contract_boundary + 2 :]
            else:
                old_priority_end += len("Don't claim success without verifying files and Import receipt.")
                updated_prompt = PRIORITY + updated_prompt[old_priority_end:].lstrip("\r\n")
        elif updated_prompt.startswith("P5-CODEX-139 RUN THROUGH THE AUTHORING HANDOFF"):
            p131_start = updated_prompt.find(PRIORITY_MARKER)
            if p131_start >= 0:
                old_priority_end = updated_prompt.find(
                    "Don't claim success without verifying files and Import receipt.", p131_start
                )
                if old_priority_end < 0:
                    raise ValueError(f"automation_priority_boundary_missing:{path.parent.name}")
                old_priority_end += len("Don't claim success without verifying files and Import receipt.")
                updated_prompt = PRIORITY + updated_prompt[old_priority_end:].lstrip("\r\n")
            else:
                task_start = updated_prompt.find("\n\nTask code:")
                if task_start < 0:
                    task_start = updated_prompt.find("\n\nYou are a Codex desktop Scheduled task")
                if task_start < 0:
                    raise ValueError(f"automation_priority_boundary_missing:{path.parent.name}")
                updated_prompt = PRIORITY + updated_prompt[task_start + 2 :]
        elif PRIORITY_MARKER not in updated_prompt:
            updated_prompt = PRIORITY + updated_prompt

        if MARKER in updated_prompt:
            contract_start = updated_prompt.index(MARKER)
            search_start = updated_prompt.find(SEARCH_MARKER, contract_start)
            if search_start < 0:
                raise ValueError(f"automation_search_contract_missing:{path.parent.name}")
            prefix_start = contract_start - 2 if updated_prompt[max(0, contract_start - 2) : contract_start] == "\n\n" else contract_start
            updated_prompt = updated_prompt[:prefix_start] + CONTRACT + updated_prompt[search_start:]
        else:
            updated_prompt = updated_prompt.rstrip() + CONTRACT

        if SEARCH_MARKER in updated_prompt:
            search_start = updated_prompt.index(SEARCH_MARKER)
            prefix_start = search_start - 2 if updated_prompt[max(0, search_start - 2) : search_start] == "\n\n" else search_start
            updated_prompt = updated_prompt[:prefix_start].rstrip() + SEARCH_CONTRACT
        else:
            updated_prompt = updated_prompt.rstrip() + SEARCH_CONTRACT
        target_hint = TARGET_ID_HINTS.get(str(before.get("id")))
        if target_hint and target_hint not in updated_prompt:
            updated_prompt = updated_prompt.rstrip() + "\n\n" + target_hint
        topic_hint = UNRESOLVED_TOPIC_HINTS.get(str(before.get("id")))
        if topic_hint and topic_hint not in updated_prompt:
            updated_prompt = updated_prompt.rstrip() + "\n\n" + topic_hint
        if updated_prompt == prompt:
            continue
        after_raw = _replace_prompt(raw.decode("utf-8"), updated_prompt, timestamp).encode("utf-8")
        after = tomllib.loads(after_raw.decode("utf-8"))
        if any(after.get(key) != before.get(key) for key in immutable_fields):
            raise ValueError(f"automation_non_prompt_setting_changed:{path.parent.name}")
        if after.get("prompt", "").count(SEARCH_MARKER) != 1:
            raise ValueError(f"automation_search_contract_invalid:{path.parent.name}")
        planned.append(
            (
                path,
                raw,
                before,
                after_raw,
                hashlib.sha256(raw).hexdigest(),
                hashlib.sha256(after_raw).hexdigest(),
            )
        )

    backup = args.backup_root / f"P5-CODEX-147-{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
    item_results: list[dict[str, object]] = []
    report: dict[str, object] = {
        "work_id": "P5-CODEX-147",
        "applied": args.apply,
        "automation_ui_crosscheck": "unavailable_native_control_pipe",
        "items": item_results,
    }
    if args.apply:
        backup.mkdir(parents=True, exist_ok=False)
        for path, raw, before, after_raw, before_hash, after_hash in planned:
            shutil.copy2(path, backup / f"{path.parent.name}.automation.toml")
            staged = path.with_name(path.name + ".p147.tmp")
            with staged.open("xb") as out:
                out.write(after_raw)
                out.flush()
                os.fsync(out.fileno())
            os.replace(staged, path)
            if _load(path).get("prompt") != tomllib.loads(after_raw.decode("utf-8")).get("prompt"):
                raise ValueError(f"automation_prompt_saved_verification_failed:{path.parent.name}")
            item_results.append(
                {
                    "id": before.get("id"),
                    "status": before.get("status"),
                    "before_sha256": before_hash,
                    "after_sha256": after_hash,
                }
            )
        report["backup_directory"] = str(backup)
        (backup / "manifest.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    else:
        report["items"] = [
            {
                "id": before.get("id"),
                "status": before.get("status"),
                "before_sha256": before_hash,
                "after_sha256": after_hash,
            }
            for _, _, before, _, before_hash, after_hash in planned
        ]
    print(
        json.dumps({"active_project_automation_count": len(planned), **report}, ensure_ascii=True)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
