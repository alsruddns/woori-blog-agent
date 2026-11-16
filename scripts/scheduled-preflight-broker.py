"""Fixed local generation preflight broker. No arbitrary endpoint or SQL input."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))

if __name__ == "__main__":
    from woori.scheduled_preflight import check_generation, unavailable

    try:
        raw = sys.stdin.buffer.read(8193)
        if len(raw) > 8192:
            raise ValueError("request_too_large")
        result = check_generation(json.loads(raw))
    except (OSError, ValueError, TypeError):
        result = unavailable("local_broker_unavailable")
    print(json.dumps(result, ensure_ascii=True, default=str))
