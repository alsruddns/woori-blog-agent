"""Fail closed unless pytest is explicitly connected to the isolated test database."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values

root = Path(__file__).resolve().parents[3]
test_values = dotenv_values(root / ".env.test")
required = ("DATABASE_URL", "MIGRATION_DATABASE_URL")
missing = [name for name in required if not test_values.get(name)]
if missing:
    raise RuntimeError("pytest requires a provisioned .env.test with isolated DB credentials")

for key in required:
    os.environ[key] = str(test_values[key])

for key, database, role in (
    ("DATABASE_URL", "woori_blog_agent_test", "woori_test_app"),
    ("MIGRATION_DATABASE_URL", "woori_blog_agent_test", "woori_test_owner"),
):
    parsed = urlsplit(os.environ[key])
    host = parsed.hostname or ""
    if (
        parsed.path.lstrip("/") != database
        or parsed.username != role
        or host not in {"localhost", "127.0.0.1", "::1"}
        or parsed.port != 5432
    ):
        raise RuntimeError("pytest database identity does not match the isolated local test database")
