"""Validate UTF-8 JSON before atomically publishing an immutable local snapshot."""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))
from woori.research_snapshot import write_snapshot


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path, help="UTF-8 JSON staging file; never an existing research artifact")
    parser.add_argument("filename", help="Fresh basename ending in .research.json")
    args = parser.parse_args()
    research = ROOT / ".local" / "gpt-scheduled-import" / "research"
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.research\.json", args.filename):
        parser.error("destination_must_be_a_research_json_basename")
    try:
        digest = write_snapshot(args.source, research / args.filename)
    except (OSError, ValueError, UnicodeError) as error:
        # No raw source text, credentials or exception content in diagnostics.
        print(json.dumps({"valid": False, "reason": type(error).__name__, "snapshot_created": False}))
        return 1
    print(json.dumps({"valid": True, "path": str(research / args.filename), "sha256": digest}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
