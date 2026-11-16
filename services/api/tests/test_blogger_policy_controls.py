from contextlib import contextmanager
from uuid import UUID

import pytest
from fastapi import HTTPException
from woori import blogger_routes

POLICY_ID = UUID("11111111-1111-4111-8111-111111111111")
BLOG_ID = UUID("22222222-2222-4222-8222-222222222222")


class FakeConnection:
    def __init__(self, *, blog_active: bool = True, policy_active: bool = False) -> None:
        self.blog_active = blog_active
        self.policy_active = policy_active
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, query: str, params: tuple[object, ...]):
        self.calls.append((query, params))
        return self

    def fetchone(self):
        return {"id": POLICY_ID, "blog_id": BLOG_ID, "active": self.policy_active,
                "blog_active": self.blog_active}


def _replace_connection(monkeypatch: pytest.MonkeyPatch, fake: FakeConnection) -> None:
    @contextmanager
    def connection():
        yield fake
    monkeypatch.setattr(blogger_routes, "connection", connection)


def test_policy_toggle_changes_only_active_and_appends_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeConnection()
    _replace_connection(monkeypatch, fake)
    result = blogger_routes.change_publication_policy(POLICY_ID,
        blogger_routes.PublicationPolicyChange(active=True, actor_label="관리자", reason="발행 정책을 검토하고 활성화함"))
    assert result == {"id": str(POLICY_ID), "active": True, "changed": True}
    assert len(fake.calls) == 3
    assert "SET active=%s" in fake.calls[1][0]
    assert fake.calls[1][1] == (True, POLICY_ID)
    assert "blogger.publication_policy.changed" in fake.calls[2][0]
    assert fake.calls[2][1][0] == BLOG_ID


def test_inactive_blog_cannot_enable_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeConnection(blog_active=False)
    _replace_connection(monkeypatch, fake)
    with pytest.raises(HTTPException) as error:
        blogger_routes.change_publication_policy(POLICY_ID,
            blogger_routes.PublicationPolicyChange(active=True, actor_label="관리자", reason="발행 정책을 검토하고 활성화함"))
    assert error.value.status_code == 409
    assert len(fake.calls) == 1
