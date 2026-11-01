"""Append one shared recovery instruction, preserving all 15 saved schedules.

Dry run is default. Does not register/run/reschedule Automations or edit memories.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKER = "P5-CODEX-102 SHARED OUTAGE CONTRACT"
APPEND = """\n\nP5-CODEX-102 SHARED OUTAGE CONTRACT (authoritative; supersedes older outage-stop wording only):
Before authoring, read docs/operations/scheduled-outage-recovery.md and follow that shared contract for this invocation. Keep this task's existing ID, RRULE, schedule, model, target blog, language, topic/research instructions and the exact resolver-confirmed scheduled/manual provenance. The existing generation duplicate CLI now owns approved local fallback; never read .env, credentials, execute SQL or call API/Blogger yourself. If it explicitly returns research_allowed=true, local_save_allowed=true and import_status=pending, continue evidence-led research/writing even on exit 3, but never deliver to ready or Import. Validate the incoming envelope, then use scripts/save-pending-manuscript.py for immutable pending storage (manual Run now also supplies the real --target-blog-id). Preserve unknown duplicate status and draft_import_allowed=false. Confirmed duplicates/pending matches still block another original. Record actual progress with scripts/scheduled-progress.py, including real usage_limit_waiting. Research Worker owns recovery checks and Import. Do not claim downstream success without a receipt. Blogger automatic Draft/Publish/Update, Publishing Jobs, Auto, Google API restrictions and emergency stop must remain untouched. Historical failures are preserved; this contract does not authorize inventing a current scheduled trigger for an old slot.
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument('--controls',action='store_true',help='Append the P103 automatic authoring gate')
    args = parser.parse_args()
    marker = 'P5-CODEX-103 AUTHORING POLICY' if args.controls else MARKER
    appendix = """\n\nP5-CODEX-103 AUTHORING POLICY (authoritative for automatic authoring):
Before research and again before writing, use the current shared resolver and scripts/automation-policy-check.py. Scheduled executions require allowed=true from this trusted helper. If OFF or unavailable, do not research/start Codex authoring or guess ON; record policy_waiting and keep the occurrence unchanged. The resolver enforces this gate for actual scheduled triggers. Explicit Desktop Run now remains manual under its existing user authorization. Dashboard availability is irrelevant: the helper uses authenticated loopback API then the same DB policy through fixed service code. Never read credentials or execute SQL in model instructions. Preserve written files, existing Import, edit/quality/export functions and all 15 schedules. P102 research-when-duplicate-check-unavailable applies only after authoring policy was confirmed ON. Recheck the policy before writing. Scheduled authoring never creates Publishing Jobs or calls Blogger; it ends at Import.
""" if args.controls else APPEND
    candidates = []
    for path in (Path.home() / ".codex/automations").rglob("automation.toml"):
        raw = path.read_bytes()
        config = tomllib.loads(raw.decode("utf-8"))
        if str(ROOT) not in config.get("cwds", []):
            continue
        if config.get("status") != "ACTIVE" or config.get("kind") != "cron":
            raise ValueError("expected_active_project_automation")
        candidates.append((path, raw, config))
    if len(candidates) != 15:
        raise ValueError("expected_exactly_15_project_automations")
    backup = ROOT / ('.local/p103-automation-contract-backup' if args.controls else '.local/p102-automation-contract-backup')
    if args.apply:
        backup.mkdir(exist_ok=True)
    evidence = []
    for path, raw, config in candidates:
        if marker in config["prompt"]:
            continue
        text = raw.decode("utf-8")
        updated, count = re.subn(
            r'^prompt = "(?:\\.|[^"\\])*"\r?$',
            lambda _, config=config, appendix=appendix: (
                "prompt = " + json.dumps(config["prompt"] + appendix, ensure_ascii=False)
            ),
            text,
            flags=re.MULTILINE,
        )
        if count != 1:
            raise ValueError("expected_one_json_compatible_prompt_field")
        after = tomllib.loads(updated)
        if {k: v for k, v in after.items() if k != "prompt"} != {
            k: v for k, v in config.items() if k != "prompt"
        }:
            raise ValueError("non_prompt_settings_changed")
        if args.apply:
            snapshot = backup / (config["id"] + ".toml")
            with snapshot.open("xb") as out:
                out.write(raw)
            staged = path.with_suffix(".p102.tmp")
            with staged.open("x", encoding="utf-8", newline="") as out:
                out.write(updated)
                out.flush()
                os.fsync(out.fileno())
            staged.replace(path)
        evidence.append(
            {
                "automation_id": config["id"],
                "before_sha256": hashlib.sha256(raw).hexdigest(),
                "after_sha256": hashlib.sha256(updated.encode()).hexdigest(),
                "non_prompt_settings_equal": True,
            }
        )
    result = {"applied": args.apply, "count": len(evidence), "automations": evidence}
    if args.apply and evidence:
        (backup / "manifest.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
