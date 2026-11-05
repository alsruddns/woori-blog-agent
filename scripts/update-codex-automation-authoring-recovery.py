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
PRIORITY = f"""{PRIORITY_MARKER} (highest-priority execution order):
This Automation turn must perform the work, not only diagnose or restate policy. Keep the initial inspection short: read this task prompt, memory.md if present, and only the specific schema/contract section needed. Do not print or reread whole long policy documents; this prompt and docs/operations/scheduled-outage-recovery.md already define the required safeguards. Resolve the exact run once, run generation duplicate preflight once, then use the rest of the available run to open current sources, write the research snapshot and article envelope, validate, and hand off to ready. The scheduled resolver's automation_policy.allowed=true is the pre-research policy check; perform the existing policy recheck once immediately before writing. Do not stop merely because preflight's overall status is unknown when its local status is not_found/failed_only, draft_import_allowed=true, and remote status is not_checked. Do stop for unclear local duplicate status, unsupported evidence, a real usage limit, unresolved identity, or an actual command failure. Don't claim success without verifying files and Import receipt.\n\n"""
CONTRACT = f"""\n\n{MARKER} (authoritative for this invocation):
Read docs/operations/scheduled-outage-recovery.md and follow its evidence, source-rights, idempotency and no-Blogger rules. First run scripts/resolve-codex-automation-run.py with this task's exact Automation ID; proceed only on resolved=true. Accepted triggers are only the resolver-confirmed automation_cron_scheduled and official Desktop Run now automation_cron_run_now. A composer/development turn, old session or claimed trigger is not an Automation run. Scheduled mode uses the returned scheduled occurrence and chatgpt_scheduled_export envelope. Run now uses the exact returned manual_origin, generation_method=manual_codex_import and woori-manual-automation-content-import/1.0; it has no scheduled slot/provenance. The existing scripts/validate-scheduled-import.py validates BOTH envelope types; do not stop because its filename says scheduled.
Run scripts/scheduled_duplicate_check.py --stage generation for the exact target/language/topic. Only local_status=not_found or failed_only AND draft_import_allowed=true permits a new Import. local_status=unknown, a duplicate, disallowed draft, unresolved run identity or a live matching run blocks. Preserve remote_status=not_checked; it is not proof of remote uniqueness and the normal publication-time check remains mandatory. Do not use the outage pending saver for a clear, eligible preflight.
Use current, directly reviewed web sources; never fabricate evidence, facts, source excerpts, research snapshots or claims. If research is insufficient, record a blocked/skipped result and create no article envelope. Save the evidence metadata/excerpts and claim links in a fresh staging JSON, then run scripts/write-research-snapshot.py <staging.json> <unique-name>.research.json. Stop if it fails; never overwrite a snapshot.
Only after a successful snapshot, write the complete UTF-8 envelope to a new incoming/<unique-name>.part. For a retry, inspect the exact invocation and all existing artifacts first; do not overwrite files, replay old slots or create a second original. Run scripts/validate-scheduled-import.py on the .part and require valid=true. Save the exact generation-preflight JSON response as a temporary local file and run scripts/handoff-automation-manuscript.py <incoming.part> --preflight-json <preflight.json>. This helper rechecks the current Desktop invocation, the complete Pydantic envelope, clear local preflight and exclusive ready handoff; it never calls an API/Blogger or creates a Publishing Job. A successful result means file handoff only. Research Worker Import receipt, quality/review state, publication queue and Blogger publication are distinct later outcomes. Record the real path/hash and each completed stage; never report completion for an unsaved or invalid article. Preserve this task's existing Automation ID, prompt topic, language, target, RRULE, model and operating policy. Do not create, delete, pause or reschedule any Automation.
"""

SEARCH_CONTRACT = f"""\n\n{SEARCH_MARKER} (required after a clear generation preflight):
The task environment's own tool list is not assumed to contain web search. Use the installed ChatGPT-auth Codex CLI live web search through the fixed broker for the exact resolver-confirmed invocation; do not switch to API keys, metered endpoints, paid credits, arbitrary HTTP clients or guessed browser tools. Use politics only for U.S. policy where the White House feed is relevant, economy only for U.S. BLS/Federal Reserve topics, technology only for U.S. NIST cybersecurity topics, and general for all other topics.

For execution_mode=scheduled, save the exact generation-preflight JSON and pass it on stdin to scripts/scheduled-research-broker.py with this Automation ID, exact topic and category. It rechecks the current scheduled identity and authoring policy, requires clear local duplicate eligibility, calls `codex --search exec` using the current ChatGPT login, and saves an immutable scheduled Research Snapshot.

For execution_mode=manual from the official Desktop Run now trigger, preserve the exact `manual_origin` and `manual_run_id`; do not invent scheduled fields or call the scheduled broker. Save the exact generation-preflight JSON and pass it on stdin to scripts/manual-research-broker.py with this Automation ID, exact topic and category. It rechecks the current manual trigger and the matching manual_codex_import contract, requires local_status=not_found or failed_only with draft_import_allowed=true, and preserves remote_status=not_checked. It calls the same isolated `codex --search exec` with the current ChatGPT login and saves an immutable manual Research Snapshot keyed to that manual_run_id.

For either mode, require evidence_available with source URLs, publication dates and excerpts matched to actual web-search results before drafting. Read the saved package and use its retained evidence in the article snapshot and claim links. Do not fabricate a package, date, source or claim. If the CLI reports account usage limit, authentication, capacity or timeout failure, stop this run; do not use an API key, metered API, purchase credits or disguise the failure. Never treat package creation as article creation, Import, review approval or publication. Continue the same invocation through the matching envelope, validation and exclusive handoff, and report each stage separately. Manual Run now remains manual_codex_import and review-held; it receives no Scheduled Auto authority and creates no Publishing Job or Blogger write. Preserve Automation ID, schedule, topic, language, target, operation policy and all previous idempotency checks. Do not create or replay an occurrence.
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
        if MARKER not in updated_prompt:
            updated_prompt = updated_prompt.rstrip() + CONTRACT
        if PRIORITY_MARKER not in updated_prompt:
            updated_prompt = PRIORITY + updated_prompt
        if SEARCH_MARKER in updated_prompt:
            updated_prompt = updated_prompt.split(SEARCH_MARKER, 1)[0].rstrip() + SEARCH_CONTRACT
        else:
            updated_prompt = updated_prompt.rstrip() + SEARCH_CONTRACT
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

    backup = args.backup_root / f"P5-CODEX-140-RETRY-{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
    item_results: list[dict[str, object]] = []
    report: dict[str, object] = {
        "work_id": "P5-CODEX-140-RETRY",
        "applied": args.apply,
        "automation_ui_crosscheck": "unavailable_native_control_pipe",
        "items": item_results,
    }
    if args.apply:
        backup.mkdir(parents=True, exist_ok=False)
        for path, raw, before, after_raw, before_hash, after_hash in planned:
            shutil.copy2(path, backup / f"{path.parent.name}.automation.toml")
            staged = path.with_name(path.name + ".p140.tmp")
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
