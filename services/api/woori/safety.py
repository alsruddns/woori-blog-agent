class DisabledCapability(RuntimeError):
    pass


def call_ai(provider: str, prompt: str) -> str:
    # No network client exists in Phase 1. Environment flags cannot bypass this gate.
    raise DisabledCapability("AI execution is disabled in Phase 1")


def publish_blogger(content_id: str) -> None:
    raise DisabledCapability("Blogger publishing is disabled in Phase 1")
