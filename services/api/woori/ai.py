"""Common manuscript provider contract; no production generator is currently attached."""

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

PRODUCTION_GENERATOR_CONFIGURED = False


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


def provider(name: str) -> Provider:
    if name == "mock":
        return MockProvider()
    if name == "local":
        raise EngineFailure("generation_provider_unavailable")
    raise EngineFailure("paid_or_unknown_provider_blocked")
