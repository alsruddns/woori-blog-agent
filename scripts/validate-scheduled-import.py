"""Read-only validator using the exact Pydantic contract used by the inbox Worker."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))

from pydantic import ValidationError
from woori.scheduled_import_inbox import validate_envelope


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate one scheduled import envelope without API or DB access")
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    candidate = args.path.resolve(strict=True)
    allowed = (ROOT / ".local" / "gpt-scheduled-import" / "incoming").resolve()
    if allowed not in candidate.parents or candidate.suffix.casefold() not in {".part", ".json"}:
        print(json.dumps({"valid": False, "reason": "path_must_be_inside_scheduled_import_incoming"}))
        return 2
    try:
        if candidate.stat().st_size > 256 * 1024:
            raise ValueError("scheduled_import_file_too_large")
        envelope = validate_envelope(candidate.read_bytes())
    except ValidationError as exc:
        errors = [
            {"location": ".".join(str(part) for part in entry.get("loc", ())),
             "type": entry.get("type", "validation_error"),
             "message": re.sub(r"\s+", " ", entry.get("msg", "Invalid value"))[:240]}
            for entry in exc.errors(include_input=False)[:8]
        ]
        print(json.dumps({"valid": False, "reason": "invalid_envelope", "errors": errors}, ensure_ascii=False))
        return 1
    except (OSError, ValueError) as exc:
        print(json.dumps({"valid": False, "reason": str(exc)[:200]}, ensure_ascii=False))
        return 1
    print(json.dumps({"valid": True, "content_id": envelope.item.content_id,
                      "relation": envelope.item.relation,
                      "labels": envelope.item.blogger_labels}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
