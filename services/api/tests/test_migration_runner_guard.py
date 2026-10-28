import re
from pathlib import Path


def test_migration_runner_guard_matches_latest_migration_script() -> None:
    root = Path(__file__).resolve().parents[3]
    runner = (root / "scripts" / "migrate.py").read_text(encoding="utf-8")
    match = re.search(r"MAX_SUPPORTED_SCHEMA_VERSION\s*=\s*(\d+)", runner)
    assert match is not None
    supported_version = int(match.group(1))
    migration_versions = [
        int(path.name.split("_", maxsplit=1)[0])
        for path in (root / "scripts").glob("[0-9][0-9][0-9]_*.sql")
    ]
    assert supported_version == max(migration_versions)
    assert "if current > MAX_SUPPORTED_SCHEMA_VERSION:" in runner
