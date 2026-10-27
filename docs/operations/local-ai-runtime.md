# Local AI runtime operations

Use only the project-local llama.cpp binaries and the already verified model under `.local/`. No hosted model fallback is enabled. The pinned llama.cpp build is b11889 (MIT) and Qwen3-4B-Q4_K_M is Apache-2.0; verify the checked-in ignored local manifest hashes before troubleshooting. Do not download another model as part of recovery.

## Start and confirm readiness

From the repository root, check port 11435, available RAM, project disk space, GPU visibility, and the shared pipeline resource gate. Never replace an existing listener. For an evaluation session, use:

```powershell
.\.venv\Scripts\python.exe scripts\start_evaluation_ai.py Qwen3-4B-Q4_K_M.gguf 4 vulkan
```

This selects the evaluation DB for startup audit. It starts the local server on loopback only and writes the runtime PID/model/backend metadata. Confirm `.local/runtime.json` points to a live process whose executable is the project `.local/llama-b11889-vulkan/llama-server.exe`; then use the authorized local health and model-list checks. The inference API key comes from `.local/inference.key`; never print it. llama.cpp exposes `--list-devices` for detecting Vulkan devices; see the [upstream build documentation](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md).

## Diagnosis and stop

`local_engine_unavailable` can mean the runtime PID is stale or its executable is not the expected project-local engine. Check the exact PID and path before acting. If port 11435 belongs to another process, do not stop it. A health response alone does not prove that the model is loaded: also confirm the model list and an audited, quota-bound evaluation run.

Stop an idle project server only when there are no queued/running generation jobs and the PID/path have been revalidated. Stop only that `llama-server.exe` process, then confirm port 11435 is free. Do not terminate other project or system processes. Evaluation runs must use the dedicated evaluation DB, one worker, explicit per-language quota, and shared RAM/CPU/disk gates. Retries reuse the same target; never reset quota to bypass a gate.

The Phase 4-J recovery found stale runtime metadata for an already exited PID; the pinned engine, model, manifest hashes and RX 570 Vulkan visibility were valid. The server was restarted and processed four quota-bound SEC language runs. The one unsupported-number/proper-name failure in the generated localizations remains a content quality issue, not a runtime fault.
