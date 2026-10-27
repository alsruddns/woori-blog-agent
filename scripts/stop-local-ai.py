"""Gracefully request shutdown of the verified project-local llama.cpp process."""

import ctypes
import json
import socket
import sys
import time
from pathlib import Path

import psutil

root = Path(__file__).resolve().parents[1]
runtime_path = root / ".local" / "runtime.json"
if not runtime_path.is_file():
    print("No project-local AI runtime record exists.")
    raise SystemExit(0)
try:
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    pid = int(runtime["pid"])
    if Path(runtime["project_root"]).resolve() != root.resolve():
        raise ValueError
    process = psutil.Process(pid)
    expected_executable = root / runtime["engine_directory"] / "llama-server.exe"
    actual_executable = Path(process.exe()).resolve()
    command = process.cmdline()
    model_path = root / runtime["model"]
    if actual_executable != expected_executable.resolve() or str(model_path.resolve()).casefold() not in " ".join(command).casefold():
        raise ValueError
except (KeyError, ValueError, OSError, psutil.Error, json.JSONDecodeError):
    print("AI runtime identity could not be verified; no process was stopped and the record was retained.")
    raise SystemExit(2)

with socket.socket() as probe:
    if probe.connect_ex(("127.0.0.1", 11435)) != 0:
        if process.is_running():
            print("Verified AI process is running but its port is not ready; refusing to signal it automatically.")
            raise SystemExit(2)
        runtime_path.unlink()
        print("Stale AI runtime record cleared after confirming the process has exited.")
        raise SystemExit(0)

try:
    listener_pids = {
        item.pid for item in psutil.net_connections(kind="inet")
        if item.status == psutil.CONN_LISTEN and item.laddr and item.laddr.port == 11435
    }
except psutil.Error:
    print("Could not verify local AI port ownership; process left running.")
    raise SystemExit(2)
if pid not in listener_pids:
    print("Port 11435 is owned by a different or unverified process; no process was stopped.")
    raise SystemExit(2)

if sys.platform != "win32" or not runtime.get("process_group_managed"):
    print("This AI process has no verified graceful-control channel. Stop it from its original terminal.")
    raise SystemExit(2)

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
if not kernel32.FreeConsole():
    # ERROR_INVALID_HANDLE means this shell was not attached to a console.
    error = ctypes.get_last_error()
    if error not in (0, 6):
        print("Could not detach the controller console; process left running.")
        raise SystemExit(2)
if not kernel32.AttachConsole(pid):
    print("Could not attach to the verified model console; process left running.")
    raise SystemExit(2)
kernel32.SetConsoleCtrlHandler(None, True)
if not kernel32.GenerateConsoleCtrlEvent(1, pid):  # CTRL_BREAK_EVENT, process group == pid
    print("Graceful shutdown signal failed; process left running.")
    raise SystemExit(2)
deadline = time.monotonic() + 12
while time.monotonic() < deadline and process.is_running():
    time.sleep(0.25)
if process.is_running():
    print("AI process did not exit gracefully; no force-stop was attempted and runtime record was retained.")
    raise SystemExit(2)
runtime_path.unlink()
print("Verified project-local AI process stopped gracefully; stale runtime record cleared.")
