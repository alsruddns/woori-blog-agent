"""Start only a verified project-local CPU model; never replace another listener."""

import hashlib
import json
import secrets
import socket
import subprocess
import sys
from pathlib import Path

import psutil

root = Path(__file__).resolve().parents[1]
folder = root / ".local"
key_path = folder / "inference.key"
if not key_path.exists():
    key_path.write_text(secrets.token_urlsafe(48), encoding="utf-8")
manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
name = sys.argv[1] if len(sys.argv) > 1 else "Qwen3-1.7B-Q8_0.gguf"
threads = int(sys.argv[2]) if len(sys.argv) > 2 else 4
if threads not in range(1, 5):
    raise SystemExit("CPU thread policy must be between 1 and 4")
model = next((m for m in manifest["models"] if m["name"] == name), None)
if not model or psutil.virtual_memory().available < 6 * 1024**3:
    raise SystemExit("Unknown model or insufficient RAM")
with socket.socket() as probe:
    if probe.connect_ex(("127.0.0.1", 11435)) == 0:
        raise SystemExit("Port 11435 occupied; no existing process was stopped")
with (folder / name).open("rb") as weights:
    if hashlib.file_digest(weights, "sha256").hexdigest() != model["sha256"]:
        raise SystemExit("Model checksum mismatch")
process = subprocess.Popen(
    [
        str(folder / "llama-b11889/llama-server.exe"),
        "-m",
        str(folder / name),
        "--host",
        "127.0.0.1",
        "--port",
        "11435",
        "-t",
        str(threads),
        "-tb",
        str(threads),
        "-c",
        "8192",
        "-ngl",
        "0",
        "-np",
        "1",
        "--alias",
        name,
        "--jinja",
        "--chat-template-kwargs",
        json.dumps({"enable_thinking": False}),
        "--no-webui",
        "--log-disable",
        "--api-key-file",
        str(key_path),
    ],
    cwd=root,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    creationflags=subprocess.CREATE_NO_WINDOW,
)
(folder / "runtime.json").write_text(
    json.dumps(
        {"pid": process.pid, "model": name, "engine": manifest["engine"], "threads": threads}
    ),
    encoding="utf-8",
)
print("Project-local CPU inference started; PID", process.pid, "model", name)
from psycopg.types.json import Jsonb
from woori.db import connection

with connection() as conn:
    conn.execute(
        "INSERT INTO audit_events(event_type,payload) VALUES ('research.local.started',%s)",
        (
            Jsonb(
                {
                    "pid": process.pid,
                    "model": name,
                    "engine": manifest["engine"],
                    "threads": threads,
                    "gpu_layers": 0,
                    "api_key_file": True,
                }
            ),
        ),
    )
