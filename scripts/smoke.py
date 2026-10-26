"""Start real loopback servers, verify responses, and stop the child process trees."""

import subprocess
import time
from pathlib import Path

import httpx

root = Path(__file__).resolve().parents[1]
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
    print("Real API/dashboard HTTP smoke passed; live audit data rendered; token absent from HTML.")
finally:
    for child in children:
        subprocess.run(
            ["taskkill", "/PID", str(child.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
