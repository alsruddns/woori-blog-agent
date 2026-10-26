"""Start real loopback servers, verify responses, and stop the child process trees."""

import socket
import subprocess
import time
from pathlib import Path

import httpx

root = Path(__file__).resolve().parents[1]
# Never test or terminate an unrelated server already using the configured ports.
for port in (8000, 3000):
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            raise SystemExit("Smoke test requires free loopback ports 8000 and 3000")
children = []
try:
    for args, cwd in [
        (
            [
                str(root / ".venv/Scripts/python.exe"),
                "-m",
                "uvicorn",
                "woori.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8000",
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
                "3000",
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
            )
        )
    for _ in range(50):
        if any(child.poll() is not None for child in children):
            raise SystemExit("A smoke test server exited before startup")
        try:
            assert httpx.get("http://127.0.0.1:8000/health").status_code == 200
            page = httpx.get("http://127.0.0.1:3000/", timeout=5)
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
    assert httpx.get("http://127.0.0.1:8000/admin/summary").status_code == 401
    config = httpx.get("http://127.0.0.1:3000/config", timeout=10)
    assert config.status_code == 200
    assert "다국어 운영 설정" in config.text
    assert "https://trend-journal-en.blogspot.com" in config.text
    assert "https://trend-zh.blogspot.com" in config.text
    assert token not in config.text
    proxy = "http://127.0.0.1:3000/api/config/languages"
    invalid = {"code": "en_US", "display_name": "Invalid test"}
    assert httpx.post(proxy, json=invalid).status_code == 403
    assert (
        httpx.post(proxy, json=invalid, headers={"Origin": "https://untrusted.example"}).status_code
        == 403
    )
    forwarded = httpx.post(proxy, json=invalid, headers={"Origin": "http://127.0.0.1:3000"})
    assert forwarded.status_code == 422, (forwarded.status_code, forwarded.text)
    print("Real API/dashboard/config HTTP smoke passed; proxy origin checks passed; tokens absent.")
finally:
    for child in children:
        subprocess.run(
            ["taskkill", "/PID", str(child.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
