"""Compare real secret values in memory; never serialize credentials or provider errors."""

import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

import httpx
from dotenv import dotenv_values
from woori.db import connection
from woori.google_oauth import decrypt

root = Path(__file__).resolve().parents[1]
secrets = []
for name in (".env", ".env.bootstrap", ".env.migration", "apps/dashboard/.env.local"):
    for key, value in dotenv_values(root / name).items():
        if not value:
            continue
        if any(part in key for part in ("TOKEN", "SECRET", "ENCRYPTION_KEY")):
            secrets.append(value)
        if "DATABASE_URL" in key and urlsplit(value).password:
            secrets.append(unquote(urlsplit(value).password or ""))
    assert (
        subprocess.run(["git", "check-ignore", "--quiet", name], cwd=root, check=False).returncode
        == 0
    )
with connection() as conn:
    for row in conn.execute(
        "SELECT access_ciphertext,refresh_ciphertext FROM google_connections WHERE status='connected'"
    ).fetchall():
        secrets.extend(decrypt(value) for value in row.values() if value)
    history = str(conn.execute("SELECT payload FROM audit_events").fetchall())
    history += str(conn.execute("SELECT * FROM blogger_api_calls").fetchall())
    history += str(conn.execute("SELECT * FROM generation_attempts").fetchall())
    assert not any(value and value in history for value in secrets), (
        "Plaintext secret found in history"
    )
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM publishing_policies WHERE auto_publish_allowed"
        ).fetchone()["n"]
        == 0
    )
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM language_execution_limits WHERE publishing_enabled"
        ).fetchone()["n"]
        == 0
    )
names = (
    subprocess.check_output(["git", "diff", "--cached", "--name-only", "-z"], cwd=root)
    .decode()
    .split("\0")
)
for name in filter(None, names):
    assert not Path(name).name.startswith(".env"), "Unexpected staged dotenv"
    content = subprocess.check_output(["git", "show", ":" + name], cwd=root)
    assert not any(value and value.encode() in content for value in secrets), (
        "Secret found in staged content"
    )
with httpx.Client(timeout=15, trust_env=False) as client:
    outputs = []
    for path in ("/", "/research", "/blogger"):
        response = client.get("http://127.0.0.1:3100" + path)
        assert response.status_code == 200
        outputs.append(response.text)
    for path in ("research/state", "blogger/status"):
        response = client.get(
            "http://127.0.0.1:3100/api/" + path, headers={"Origin": "http://127.0.0.1:3100"}
        )
        assert response.status_code == 200
        outputs.append(response.text)
    assert not any(value and value in "\n".join(outputs) for value in secrets), (
        "Plaintext secret in HTTP response"
    )
print(
    "Secret exclusion/staged content/history/HTTP scans passed; publication flags remain disabled."
)
