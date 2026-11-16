"""Run the local API with an identity-bound graceful stop-file channel."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

import uvicorn

PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "api"
RUNTIME = PROJECT_ROOT / ".runtime"
SERVICE = "api"


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    os.replace(temporary, path)


async def _serve() -> None:
    sys.path.insert(0, str(API_ROOT))
    RUNTIME.mkdir(exist_ok=True)
    if RUNTIME.is_symlink() or RUNTIME.resolve() != PROJECT_ROOT / ".runtime":
        raise RuntimeError("project_runtime_directory_invalid")
    pid = os.getpid()
    instance_id = uuid.uuid4().hex
    identity_path = RUNTIME / f"service-identity-{SERVICE}-{pid}.json"
    stop_path = RUNTIME / f"service-stop-{SERVICE}-{pid}.json"
    identity = {
        "pid": pid,
        "service": SERVICE,
        "checkout_root": str(PROJECT_ROOT),
        "instance_id": instance_id,
    }
    _atomic_json(identity_path, identity)
    config = uvicorn.Config(
        "woori.main:app", host="127.0.0.1", port=8100, access_log=False,
    )
    server = uvicorn.Server(config)

    async def watch_stop_request() -> None:
        while not server.should_exit:
            try:
                if stop_path.stat().st_size > 4096:
                    await asyncio.sleep(0.25)
                    continue
                request = json.loads(stop_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                await asyncio.sleep(0.25)
                continue
            if request == identity:
                server.should_exit = True
                try:
                    stop_path.unlink()
                except FileNotFoundError:
                    pass
                return
            await asyncio.sleep(0.25)

    watcher = asyncio.create_task(watch_stop_request())
    try:
        await server.serve()
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)
        try:
            identity_path.unlink()
        except FileNotFoundError:
            pass
        try:
            stop_path.unlink()
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    asyncio.run(_serve())
