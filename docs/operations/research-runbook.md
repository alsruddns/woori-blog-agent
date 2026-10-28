# Research runbook

## Supported startup

This checkout currently supports the FastAPI service, Next.js Dashboard, and bounded collection Worker. There is no local model setup or inference service. Historical Qwen3/llama.cpp results are retained as records only; Codex/GPT scheduled or unattended manuscript generation has not been implemented.

Start only the project services needed for the task, using their managed scripts from the repository root:

```powershell
./scripts/start.ps1 -Service api
./scripts/start.ps1 -Service dashboard
./scripts/run-worker.ps1
```

Use `./scripts/status.ps1` and `./scripts/stop.ps1` for managed API/Dashboard processes. Do not terminate processes by port alone. Worker startup is separate; check its heartbeat before taking action. Do not restart a service while user work is active.

## Research and generation boundary

Collection schedules may retrieve approved bounded sources. Topic assessment, source review, Research Packages, and deterministic quality checks remain available. Automatic generation schedules and collection-to-generation handoff are disabled because no production writer is attached. Existing generation jobs configured for the retired local provider fail closed. Test Mock output is synthetic and is never a publishable article.

Do not change a held Research Package or manuscript to `generation_ready` or `publish_ready` to work around the missing provider. Manual editorial review, sanitized HTML preview, SEO checks, approval history, and publication preparation remain available for already stored content. Blogger writes remain governed by their own approval and provider policy.

## Data and safety

Do not apply migrations to an operations database without the project's separate reviewed procedure. Keep operations, evaluation, and test database identities separate. Preserve content versions, quality evaluations, and append-only audit events. External collection goes only through the fixed provider allowlist and its bounded quotas; do not add arbitrary fetches or paid fallbacks.
