"""Run a bounded, append-only deterministic quality evaluation of stored C1 articles."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))
sys.path.insert(0, str(ROOT / "scripts"))

from recheck_article_quality import main

if __name__ == "__main__":
    main(phase="3.9", output_prefix="P3-9-quality-recheck")
