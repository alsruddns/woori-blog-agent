"""Compare real secret values in memory; never serialize credentials or provider errors."""

import os
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

import httpx
import psycopg
from dotenv import dotenv_values
from woori.db import connection
from woori.google_oauth import decrypt
from woori.secret_scan import contains_secret, contains_secret_in_http_response

root = Path(__file__).resolve().parents[1]
secrets = []
local_key = root / ".local/inference.key"
if local_key.exists():
    secrets.append(local_key.read_text(encoding="utf-8").strip())
for name in (
    ".env", ".env.bootstrap", ".env.migration", ".env.evaluation",
    ".env.evaluation-migration", ".env.evaluation-readonly", ".env.test",
    "apps/dashboard/.env.local",
):
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
evaluation_url = dotenv_values(root / ".env.evaluation-readonly").get("EVALUATION_DATABASE_URL", "")
if evaluation_url:
    with psycopg.connect(evaluation_url, connect_timeout=3) as evaluation:
        history = str(evaluation.execute("SELECT payload FROM audit_events").fetchall())
        history += str(evaluation.execute("SELECT title,body FROM content_versions").fetchall())
        history += str(evaluation.execute("SELECT result_metadata,source_snapshot FROM generation_results").fetchall())
        assert not any(contains_secret(history, value) for value in secrets), (
            "Plaintext secret found in isolated evaluation history"
        )
        write_rights = evaluation.execute(
            """SELECT has_table_privilege(current_user,'blogger_blogs','INSERT'),
                has_table_privilege(current_user,'blogger_blogs','UPDATE'),
                has_table_privilege(current_user,'blogger_blogs','DELETE'),
                has_table_privilege(current_user,'publishing_policies','UPDATE'),
                has_table_privilege(current_user,'language_execution_limits','UPDATE'),
                has_table_privilege(current_user,'generation_results','INSERT'),
                has_table_privilege(current_user,'generation_stage_runs','UPDATE'),
                has_table_privilege(current_user,'audit_events','UPDATE'),
                has_table_privilege(current_user,'content_versions','INSERT')"""
        ).fetchone()
        assert not any(write_rights), "Evaluation dashboard role has operational write privileges"
with connection() as conn:
    for row in conn.execute(
        "SELECT access_ciphertext,refresh_ciphertext FROM google_connections WHERE status='connected'"
    ).fetchall():
        secrets.extend(decrypt(value) for value in row.values() if value)
    history = str(conn.execute("SELECT payload FROM audit_events").fetchall())
    history += str(conn.execute("SELECT * FROM blogger_api_calls").fetchall())
    history += str(conn.execute("SELECT * FROM generation_attempts").fetchall())
    assert not any(contains_secret(history, value) for value in secrets), (
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


def staged_content_has_secret(name: str, content: bytes) -> bool:
    try:
        decoded = content.decode("utf-8")
    except UnicodeDecodeError:
        if Path(name).suffix.lower() != ".png" or not content.startswith(b"\x89PNG\r\n\x1a\n"):
            raise SystemExit("Unsupported binary staged artifact in secret scan")
        # Playwright screenshots must not contain ancillary text metadata.
        offset = 8
        while offset + 12 <= len(content):
            length = int.from_bytes(content[offset : offset + 4], "big")
            chunk_type = content[offset + 4 : offset + 8]
            end = offset + 12 + length
            if end > len(content):
                raise SystemExit("Invalid PNG structure in staged screenshot")
            if chunk_type in {b"tEXt", b"zTXt", b"iTXt"}:
                raise SystemExit("PNG text metadata requires manual secret review")
            offset = end
            if chunk_type == b"IEND":
                break
        return any(len(value) >= 16 and value.encode("utf-8") in content for value in secrets)
    return any(contains_secret(decoded, value) for value in secrets)


for name in filter(None, names):
    basename = Path(name).name
    assert not (basename.startswith(".env") and basename != ".env.example"), "Unexpected staged dotenv"
    content = subprocess.check_output(["git", "show", ":" + name], cwd=root)
    assert not staged_content_has_secret(name, content), (
        "Secret found in staged content"
    )
dashboard_base = os.environ.get("WOORI_VERIFY_DASHBOARD_BASE_URL", "http://127.0.0.1:3100")
if dashboard_base not in {"http://127.0.0.1:3100"} and not (
    os.environ.get("WOORI_TEST_MODE") == "1"
    and dashboard_base == "http://127.0.0.1:13100"
):
    raise SystemExit("Dashboard verification target is not an approved loopback URL")
with httpx.Client(timeout=15, trust_env=False, follow_redirects=True) as client:
    outputs = []
    for path in ("/", "/research", "/blogger"):
        response = client.get(dashboard_base + path)
        assert response.status_code == 200
        if path == "/research":
            assert response.url.path == "/manuscripts", "Research compatibility route did not reach manuscripts"
        outputs.append(response.text)
    for path in ("research/state", "blogger/status"):
        response = client.get(
            dashboard_base + "/api/" + path,
            headers={"Origin": dashboard_base},
        )
        assert response.status_code == 200
        outputs.append(response.text)
    assert not any(contains_secret_in_http_response("\n".join(outputs), value) for value in secrets), (
        "Plaintext secret in HTTP response"
    )
print(
    "Secret exclusion/staged content/history/HTTP scans passed; publication flags remain disabled."
)
