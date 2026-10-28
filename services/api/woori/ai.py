"""Closed provider registry. Mock is synthetic; local never falls back to paid/cloud AI."""

import json
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr


class EngineFailure(RuntimeError):
    def __init__(
        self, category: str, retryable: bool = False, retry_after_seconds: int = 30,
        failure_artifact: dict[str, Any] | None = None,
        metrics: dict[str, Any] | None = None,
    ) -> None:
        self.category, self.retryable = category, retryable
        self.retry_after_seconds = max(1, min(86400, retry_after_seconds))
        self.failure_artifact = failure_artifact
        self.metrics = metrics or {}
        self.attempts = 1
        super().__init__(category)


class Draft(BaseModel):
    _metrics: dict[str, Any] = PrivateAttr(default_factory=dict)
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=20, max_length=20000)
    summary: str = Field(min_length=10, max_length=500)
    keywords: list[str] = Field(min_length=1, max_length=20)
    source_ids: list[str] = Field(min_length=1, max_length=20)


class Provider(Protocol):
    def generate(self, context: dict[str, Any], policy: dict[str, Any]) -> Draft: ...


class MockProvider:
    def generate(self, context: dict[str, Any], policy: dict[str, Any]) -> Draft:
        keyword = context["keyword"]
        # This tests stage persistence/orchestration, never pretends to be fluent translation.
        section = context.get("plan", {}).get("section_number", 1)
        label = f"MOCK TEST ONLY [{context['language_code']}/{context['target_country']}] section {section}"
        facts = "\n".join(f"- {s['evidence']} [source:{s['id']}]" for s in context["sources"])
        return Draft(
            title=f"{keyword} | {label}",
            body=f"{label}\n## {keyword} {section}\n{facts}",
            summary=f"{keyword}: {label}. Not publishable; synthetic pipeline validation.",
            keywords=[keyword],
            source_ids=[str(s["id"]) for s in context["sources"]],
        )


class LocalProvider:
    """CPU-only Ollama; fixed loopback, no redirects/proxies or automatic downloads."""

    def generate(self, context: dict[str, Any], policy: dict[str, Any]) -> Draft:
        if policy.get("engine") == "llamacpp":
            from .local_inference import LlamaCppProvider

            return LlamaCppProvider().generate(context, policy)
        if not policy["language_verified"]:
            raise EngineFailure("language_support_unverified")
        model = policy["model"]
        if not model or "cloud" in model.lower() or any(c in model for c in ("/", "@", "?")):
            raise EngineFailure("cloud_or_invalid_model_blocked")
        try:
            with httpx.Client(
                timeout=policy["timeout_seconds"], trust_env=False, follow_redirects=False
            ) as client:
                tags = client.get("http://127.0.0.1:11434/api/tags")
                tags.raise_for_status()
                matches = [m for m in tags.json().get("models", []) if m.get("name") == model]
                if not matches or matches[0].get("remote_host") or matches[0].get("remote_model"):
                    raise EngineFailure("local_model_not_installed")
                if (
                    matches[0].get("size", 0) <= 0
                    or matches[0].get("details", {}).get("format") != "gguf"
                ):
                    raise EngineFailure("local_model_file_unverified")
                if matches[0].get("size", 0) > 4 * 1024**3:
                    raise EngineFailure("model_memory_budget_exceeded")
                response = client.post(
                    "http://127.0.0.1:11434/api/generate",
                    json={
                        "model": model,
                        "system": context["instructions"],
                        "prompt": json.dumps(
                            {k: v for k, v in context.items() if k != "instructions"}, default=str
                        ),
                        "format": Draft.model_json_schema(),
                        "stream": False,
                        "keep_alive": 0,
                        "options": {
                            "num_gpu": 0,
                            "num_thread": policy["threads"],
                            "num_ctx": 2048,
                            "num_predict": 1024,
                            "temperature": 0.2,
                        },
                    },
                )
                response.raise_for_status()
                if len(response.content) > 150000:
                    raise EngineFailure("model_response_too_large")
                return Draft.model_validate_json(response.json()["response"])
        except (httpx.TimeoutException, httpx.NetworkError):
            raise EngineFailure("local_model_unavailable", True) from None
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise EngineFailure("invalid_local_model_response") from None


def provider(name: str) -> Provider:
    if name == "mock":
        return MockProvider()
    if name == "local":
        return LocalProvider()
    raise EngineFailure("paid_or_unknown_provider_blocked")
