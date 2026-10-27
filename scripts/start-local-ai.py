"""Start only a verified project-local CPU model; never replace another listener."""

import hashlib
import json
import secrets
import socket
import subprocess
import sys
import time
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
backend = sys.argv[3].lower() if len(sys.argv) > 3 else "cpu"
if threads not in range(1, 5):
    raise SystemExit("CPU thread policy must be between 1 and 4")
if backend not in {"cpu", "vulkan"}:
    raise SystemExit("Backend must be cpu or vulkan")
engine_directory = "llama-b11889-vulkan" if backend == "vulkan" else "llama-b11889"
engine = folder / engine_directory
if backend == "vulkan":
    gpu_manifest_path = folder / "vulkan-manifest.json"
    if not gpu_manifest_path.is_file() or not (engine / "llama-server.exe").is_file():
        raise SystemExit("Project-local Vulkan engine is not installed and verified")
    try:
        gpu_manifest = json.loads(gpu_manifest_path.read_text(encoding="utf-8"))
        with (folder / gpu_manifest["archive"]).open("rb") as archive:
            if hashlib.file_digest(archive, "sha256").hexdigest() != gpu_manifest["sha256"]:
                raise SystemExit("Vulkan engine archive checksum mismatch")
    except (OSError, KeyError, ValueError):
        raise SystemExit("Vulkan engine manifest is invalid") from None
model = next((m for m in manifest["models"] if m["name"] == name), None)
minimum_ram = (model.get("size_bytes", 0) if model else 0) + 3 * 1024**3
if not model or psutil.virtual_memory().available < max(6 * 1024**3, minimum_ram):
    raise SystemExit("Unknown model or insufficient RAM")
with socket.socket() as probe:
    if probe.connect_ex(("127.0.0.1", 11435)) == 0:
        raise SystemExit("Port 11435 occupied; no existing process was stopped")
with (folder / name).open("rb") as weights:
    if hashlib.file_digest(weights, "sha256").hexdigest() != model["sha256"]:
        raise SystemExit("Model checksum mismatch")
command = [
        str(engine / "llama-server.exe"),
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
        "0" if backend == "cpu" else "20",
        "-np",
        "1",
        "--alias",
        name,
        "--jinja",
        "--no-webui",
        "--log-disable",
        "--api-key-file",
        str(key_path),
    ]
if name != "Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf":
    command[command.index("--no-webui"):command.index("--no-webui")] = [
        "--chat-template-kwargs", json.dumps({"enable_thinking": False}),
    ]
process = subprocess.Popen(
    command,
    cwd=root,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
)
time.sleep(1.5)
if process.poll() is not None:
    raise SystemExit("Project-local inference engine exited during startup")
(folder / "runtime.json").write_text(
    json.dumps(
        {
            "pid": process.pid,
            "model": name,
            "engine": manifest["engine"],
            "threads": threads,
            "backend": backend,
            "engine_directory": engine_directory,
            "gpu_layers": 0 if backend == "cpu" else 20,
            "project_root": str(root.resolve()),
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "process_group_managed": sys.platform == "win32",
        }
    ),
    encoding="utf-8",
)
print("Project-local", backend, "inference started; PID", process.pid, "model", name)
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
                    "gpu_layers": 0 if backend == "cpu" else 20,
                    "backend": backend,
                    "engine_directory": engine_directory,
                    "api_key_file": True,
                }
            ),
        ),
    )
