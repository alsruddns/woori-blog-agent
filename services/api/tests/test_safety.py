import pytest
from fastapi.testclient import TestClient
from woori.main import app
from woori.safety import DisabledCapability, call_ai, publish_blogger


@pytest.mark.parametrize("provider", ["openai", "anthropic", "local", "", "unknown"])
def test_ai_fail_closed(provider: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAID_AI_ENABLED", "true")
    with pytest.raises(DisabledCapability):
        call_ai(provider, "test")


def test_publish_disabled() -> None:
    with pytest.raises(DisabledCapability):
        publish_blogger("test")


def test_health_and_access() -> None:
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/admin/summary").status_code == 401
        assert client.post("/admin/runs", json={"idempotency_key": "test"}).status_code == 401
