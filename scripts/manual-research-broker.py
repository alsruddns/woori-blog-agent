"""Fixed ChatGPT-auth live-research broker for a verified Desktop Run now."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--automation-id", required=True)
    parser.add_argument("--category", required=True, choices=("politics", "economy", "technology", "general"))
    parser.add_argument("--topic", required=True)
    args = parser.parse_args()
    try:
        raw = sys.stdin.buffer.read(20_001)
        if len(raw) > 20_000:
            raise ValueError("preflight_response_too_large")
        preflight = json.loads(raw.decode("utf-8"))
        if not isinstance(preflight, dict):
            raise TypeError("preflight_response_invalid")
        from woori.scheduled_research import run_manual_authorized_research

        result = run_manual_authorized_research(
            automation_id=args.automation_id,
            category=args.category,
            topic=args.topic,
            preflight=preflight,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        print(json.dumps({"status": "blocked", "reason": reason[:160]}, ensure_ascii=True))
        return 3
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0 if result.get("status") == "evidence_available" else 4


if __name__ == "__main__":
    raise SystemExit(main())
