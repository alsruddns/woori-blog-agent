"""Save one validated incoming manuscript; no config, DB, API or publication access."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))

if __name__ == "__main__":
    from woori.scheduled_import_inbox import _is_reparse_point
    from woori.scheduled_pending import save_pending

    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument(
        "--target-blog-id", help="Required for manual Run now; scheduled target is in the envelope"
    )
    args = parser.parse_args()
    try:
        incoming = ROOT / ".local" / "gpt-scheduled-import" / "incoming"
        path = args.path
        if (
            any(
                _is_reparse_point(p)
                for p in [incoming.parent.parent, incoming.parent, incoming, path]
            )
            or path.resolve(strict=True).parent != incoming.resolve(strict=True)
            or path.suffix != ".part"
            or not 0 < path.stat().st_size <= 262144
        ):
            raise ValueError("requires_safe_incoming_part")
        result = save_pending(incoming.parent, path.read_bytes(), args.target_blog_id)
    except (OSError, ValueError, TypeError) as exc:
        print(json.dumps({"saved": False, "reason": type(exc).__name__}))
        raise SystemExit(2) from None
    print(json.dumps({"saved": True, **result}, ensure_ascii=True, default=str))
