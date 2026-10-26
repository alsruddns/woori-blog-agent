"""Start real loopback servers, verify responses, and stop the child process trees."""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx

root = Path(__file__).resolve().parents[1]
# Never test or terminate an unrelated server already using the configured ports.
for port in (8100, 3100):
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            raise SystemExit("Smoke test requires free loopback ports 8100 and 3100")
mock_oauth = "--mock-oauth" in sys.argv
children = []
try:
    for args, cwd in [
        (
            [
                str(root / ".venv/Scripts/python.exe"),
                "-m",
                "uvicorn",
                "oauth_mock_server:app" if mock_oauth else "woori.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8100",
                "--no-access-log",
            ],
            root,
        ),
        (
            [
                "node",
                str(root / "apps/dashboard/node_modules/next/dist/bin/next"),
                "start",
                "--hostname",
                "127.0.0.1",
                "--port",
                "3100",
            ],
            root / "apps/dashboard",
        ),
    ]:
        children.append(
            subprocess.Popen(
                args,
                cwd=cwd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
                env={**os.environ, "PYTHONPATH": str(root / "services/api/tests")},
            )
        )
    for _ in range(50):
        if any(child.poll() is not None for child in children):
            raise SystemExit("A smoke test server exited before startup")
        try:
            assert httpx.get("http://127.0.0.1:8100/health").status_code == 200
            page = httpx.get("http://127.0.0.1:3100/", timeout=5)
            if page.status_code == 200:
                break
        except (httpx.HTTPError, AssertionError):
            pass
        time.sleep(0.2)
    else:
        raise SystemExit("Servers did not become ready")
    assert "블로그 운영 현황" in page.text
    assert "run.completed" in page.text
    assert "API 연결 또는" not in page.text
    from dotenv import dotenv_values

    token = dotenv_values(root / ".env")["ADMIN_TOKEN"]
    assert token not in page.text
    assert httpx.get("http://127.0.0.1:8100/admin/summary").status_code == 401
    config = httpx.get("http://127.0.0.1:3100/config", timeout=10)
    assert config.status_code == 200
    assert "다국어 운영 설정" in config.text
    assert "https://trend-journal-en.blogspot.com" in config.text
    assert "https://trend-zh.blogspot.com" in config.text
    assert token not in config.text
    proxy = "http://127.0.0.1:3100/api/config/languages"
    invalid = {"code": "en_US", "display_name": "Invalid test"}
    assert httpx.post(proxy, json=invalid).status_code == 403
    assert (
        httpx.post(proxy, json=invalid, headers={"Origin": "https://untrusted.example"}).status_code
        == 403
    )
    forwarded = httpx.post(proxy, json=invalid, headers={"Origin": "http://127.0.0.1:3100"})
    assert forwarded.status_code == 422, (forwarded.status_code, forwarded.text)
    blogger = httpx.get("http://127.0.0.1:3100/blogger", timeout=10)
    assert blogger.status_code == 200 and "Blogger" in blogger.text
    assert token not in blogger.text
    api_status = httpx.get(
        "http://127.0.0.1:3100/api/blogger/status", headers={"Origin": "http://127.0.0.1:3100"}
    )
    assert api_status.status_code == 200 and not api_status.json()["writes_enabled"]
    assert (
        httpx.get(
            "http://127.0.0.1:3100/api/blogger/status", headers={"Origin": "http://127.0.0.1:3000"}
        ).status_code
        == 403
    )
    cors = httpx.options(
        "http://127.0.0.1:8100/admin/blogger/status",
        headers={"Origin": "http://127.0.0.1:3100", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in cors.headers
    callback = "http://127.0.0.1:3100/api/blogger/callback"
    invalid_callback = httpx.get(
        callback, params={"state": "invalid", "code": "mock-code"}, follow_redirects=False
    )
    assert (
        invalid_callback.status_code == 303
        and invalid_callback.headers["location"] == "http://127.0.0.1:3100/blogger?oauth=failed"
    )
    assert "no-referrer" == invalid_callback.headers["referrer-policy"]
    if mock_oauth:
        with httpx.Client(follow_redirects=False) as browser:
            start = browser.post(
                "http://127.0.0.1:3100/api/blogger/oauth/start",
                headers={"Origin": "http://127.0.0.1:3100"},
            )
            assert start.status_code == 200
            assert "HttpOnly" in start.headers["set-cookie"]
            query = parse_qs(urlsplit(start.json()["authorization_url"]).query)
            assert query["redirect_uri"] == [callback]
            result = browser.get(
                callback, params={"state": query["state"][0], "code": "mock-smoke-code"}
            )
            assert result.status_code == 303 and result.headers["location"].endswith(
                "/blogger?oauth=connected"
            )
            assert "Max-Age=0" in result.headers["set-cookie"]
            replay = browser.get(
                callback, params={"state": query["state"][0], "code": "mock-smoke-code"}
            )
            assert replay.headers["location"].endswith("oauth=failed")
            status = browser.get(
                "http://127.0.0.1:3100/api/blogger/status",
                headers={"Origin": "http://127.0.0.1:3100"},
            ).json()
            assert any(c["status"] == "connected" for c in status["connections"])
            assert "mock-smoke-access" not in str(status) and "mock-smoke-refresh" not in str(
                status
            )
        print(
            "MOCK provider: real 3100->8100 OAuth start/cookie/callback/state/replay flow passed; DB changes rolled back."
        )
    print(
        "Real API/dashboard/Blogger HTTP smoke passed on 3100/8100; CORS/origin boundaries and token non-disclosure passed."
    )
finally:
    for child in children:
        subprocess.run(
            ["taskkill", "/PID", str(child.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
