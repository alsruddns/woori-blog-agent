from pathlib import Path

from scripts.local_ai_process import (
    command_signature,
    option_value,
    process_matches_runtime,
    public_command_arguments,
)


def test_command_signature_omits_api_key_file_and_value() -> None:
    base = [
        "llama-server.exe", "-m", "model.gguf", "-t", "2", "-tb", "2",
        "--api-key-file", "C:/secret/path/inference.key", "--port", "11435",
    ]
    changed_key_path = [*base[:-3], "D:/another/secret.key", *base[-2:]]

    assert command_signature(base) == command_signature(changed_key_path)
    assert "C:/secret/path/inference.key" not in public_command_arguments(base)
    assert option_value(base, "-tb") == "2"


def test_command_signature_binds_model_and_thread_options() -> None:
    base = ["llama-server.exe", "-m", "model.gguf", "-t", "2", "-tb", "2"]

    assert command_signature(base) != command_signature([*base[:-1], "1"])
    assert command_signature(base) != command_signature([*base[:2], "other.gguf", *base[3:]])


def test_process_runtime_requires_verified_project_and_process_group(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    executable = root / ".local" / "llama-b11889-vulkan" / "llama-server.exe"
    model = root / ".local" / "Qwen3-4B-Q4_K_M.gguf"
    key_path = root / ".local" / "inference.key"
    command = [
        str(executable), "-m", str(model), "--host", "127.0.0.1", "--port", "11435",
        "-t", "2", "-tb", "2", "-c", "8192", "-ngl", "20", "-np", "1",
        "--alias", model.name, "--jinja", "--no-webui", "--api-key-file", str(key_path),
    ]
    runtime = {
        "pid": 1234,
        "model": model.name,
        "backend": "vulkan",
        "engine_directory": "llama-b11889-vulkan",
        "threads": 2,
        "threads_batch": 2,
        "gpu_layers": 20,
        "model_sha256": "model-hash",
        "process_create_time": 123.5,
        "executable_path": str(executable),
        "command_sha256": command_signature(command),
        "process_group_id": 1234,
        "process_group_managed": True,
        "project_root": str(root),
    }

    class FakeProcess:
        def exe(self) -> str:
            return str(executable)

        def create_time(self) -> float:
            return 123.5

    process = FakeProcess()
    assert process_matches_runtime(root, runtime, process, command, "model-hash")
    assert not process_matches_runtime(root, {**runtime, "process_group_managed": False}, process, command, "model-hash")
    changed = [*command[:8], "3", *command[9:]]
    assert not process_matches_runtime(root, runtime, process, changed, "model-hash")
