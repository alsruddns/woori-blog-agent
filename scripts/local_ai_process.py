"""Credential-safe identity helpers for the project-local llama.cpp process."""

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path


def public_command_arguments(command: Sequence[str]) -> list[str]:
    """Return command arguments without the API-key file option or its value."""
    result: list[str] = []
    skip_value = False
    for argument in command:
        if skip_value:
            skip_value = False
            continue
        if argument == "--api-key-file":
            skip_value = True
            continue
        result.append(str(argument))
    return result


def command_signature(command: Sequence[str]) -> str:
    encoded = json.dumps(public_command_arguments(command), separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def option_value(command: Sequence[str], option: str) -> str | None:
    try:
        index = command.index(option)
        return str(command[index + 1])
    except (ValueError, IndexError):
        return None


def process_matches_runtime(
    root: Path,
    runtime: dict[str, object],
    process: object,
    command: Sequence[str],
    model_sha256: str,
) -> bool:
    """Require matching checkout, binary, model, launch options and process group."""
    try:
        backend = str(runtime["backend"])
        if backend not in {"cpu", "vulkan"}:
            return False
        engine_directory = str(runtime["engine_directory"])
        expected_directory = "llama-b11889-vulkan" if backend == "vulkan" else "llama-b11889"
        if engine_directory != expected_directory:
            return False
        pid = int(runtime["pid"])
        threads = int(runtime["threads"])
        threads_batch = int(runtime["threads_batch"])
        gpu_layers = 0 if backend == "cpu" else 20
        model_path = (root / ".local" / str(runtime["model"])).resolve()
        executable = (root / ".local" / engine_directory / "llama-server.exe").resolve()
        key_path = (root / ".local" / "inference.key").resolve()
        options = {
            "-m": str(model_path), "--host": "127.0.0.1", "--port": "11435",
            "-t": str(threads), "-tb": str(threads_batch), "-c": "8192",
            "-ngl": str(gpu_layers), "-np": "1", "--alias": str(runtime["model"]),
        }
        return bool(
            threads in range(1, 5)
            and threads_batch in range(1, 5)
            and int(runtime["gpu_layers"]) == gpu_layers
            and Path(str(runtime["project_root"])).resolve() == root.resolve()
            and Path(process.exe()).resolve() == executable
            and Path(str(runtime["executable_path"])).resolve() == executable
            and abs(process.create_time() - float(runtime["process_create_time"])) <= 0.05
            and command_signature(command) == runtime["command_sha256"]
            and str(runtime["model_sha256"]) == model_sha256
            and all(option_value(command, key) == value for key, value in options.items())
            and option_value(command, "--api-key-file") is not None
            and Path(str(option_value(command, "--api-key-file"))).resolve() == key_path
            and "--jinja" in command
            and "--no-webui" in command
            and runtime.get("process_group_managed") is True
            and int(runtime["process_group_id"]) == pid
        )
    except (KeyError, TypeError, ValueError, OSError, AttributeError):
        return False
