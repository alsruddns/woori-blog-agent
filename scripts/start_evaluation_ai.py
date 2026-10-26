"""Start the existing project-local model with evaluation-only DB audit context."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if not load_dotenv(ROOT / ".env.evaluation", override=True):
    raise SystemExit("Evaluation database settings are required; local AI was not started")
sys.path.insert(0, str(ROOT / "services" / "api"))
sys.path.insert(0, str(ROOT / "scripts"))
runpy.run_path(str(ROOT / "scripts" / "start-local-ai.py"), run_name="__main__")
