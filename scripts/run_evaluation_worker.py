"""Launch one isolated evaluation Worker with no administrator credentials."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if not load_dotenv(ROOT / ".env.evaluation", override=True):
    raise SystemExit("Evaluation DB settings are required; Worker was not started")
# Settings validates this field even though the Worker has no admin API surface.
# Use a non-secret placeholder instead of loading the dashboard/API administrator token.
os.environ["ADMIN_TOKEN"] = "evaluation-worker-internal-placeholder-token"
sys.path.insert(0, str(ROOT / "services" / "api"))
from woori.worker import main

main()
