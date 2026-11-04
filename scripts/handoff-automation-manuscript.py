"""Verify the live Desktop invocation and duplicate preflight, then hand off one file."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))

from woori.automation_invocation import resolve_current_invocation
from woori.automation_ready_handoff import handoff_incoming
from woori.content_imports import ScheduledImportEnvelope
from woori.scheduled_import_inbox import validate_envelope


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate and exclusively deliver one Automation envelope to ready/"
    )
    parser.add_argument("incoming_part", type=Path)
    parser.add_argument(
        "--preflight-json",
        type=Path,
        required=True,
        help="UTF-8 JSON file containing the exact generation preflight response",
    )
    args = parser.parse_args()
    try:
        source = args.incoming_part.resolve(strict=True)
        raw = source.read_bytes()
        envelope = validate_envelope(raw)
        origin = (
            envelope.scheduled_origin
            if isinstance(envelope, ScheduledImportEnvelope)
            else envelope.manual_origin
        )
        invocation = resolve_current_invocation(str(origin.automation_id), project_root=ROOT)
        preflight = json.loads(args.preflight_json.read_text(encoding="utf-8"))
        if not isinstance(preflight, dict):
            raise TypeError("preflight_result_must_be_object")
        result = handoff_incoming(
            ROOT / ".local" / "gpt-scheduled-import",
            source,
            invocation=invocation,
            preflight=preflight,
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        print(json.dumps({"handed_off": False, "reason": reason[:180]}, ensure_ascii=True))
        return 2
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
