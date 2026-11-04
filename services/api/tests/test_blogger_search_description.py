from __future__ import annotations

from typing import Any

import pytest
from psycopg.types.json import Jsonb
from woori.blogger_search_description import (
    MAX_SEARCH_DESCRIPTION_LENGTH,
    article_revision_sha256,
    generate_search_description,
    load_generated_description,
    persist_generated_description,
)


@pytest.mark.parametrize(
    ("locale", "title", "body"),
    [
        ("ko", "금리 결정", "중앙은행은 기준금리를 동결했다. 정책위원회는 물가 흐름을 계속 살피겠다고 밝혔다."),
        ("en", "Rate decision", "The central bank held its benchmark rate. Officials said they would continue monitoring inflation."),
        ("ja", "金利決定", "中央銀行は政策金利を据え置いた。委員会は物価の動向を引き続き確認するとした。"),
        ("de", "Zinsentscheidung", "Die Zentralbank ließ den Leitzins unverändert. Der Rat will die Preisentwicklung weiter beobachten."),
        ("pt-BR", "Decisão sobre juros", "O banco central manteve a taxa básica. O comitê afirmou que continuará acompanhando a inflação."),
        ("vi", "Quyết định lãi suất", "Ngân hàng trung ương giữ nguyên lãi suất điều hành. Hội đồng cho biết sẽ tiếp tục theo dõi lạm phát."),
    ],
)
def test_generates_description_from_article_lead_for_supported_locales(locale: str, title: str, body: str) -> None:
    result = generate_search_description(title=title, body=body, language_code=locale)
    assert result["description"]
    assert result["language_code"] == locale
    assert result["status"] == "GENERATED"
    assert result["blogger_status"] == "APPLY_PENDING"
    assert result["blogger_api_supported"] is False
    assert result["html_meta_description_verified"] is False


def test_existing_description_is_reused_and_limited() -> None:
    result = generate_search_description(
        title="Market update", body="Unrelated body text.", language_code="en",
        existing_description="The report explains the confirmed market change and its official timing.",
    )
    assert result["generation_source"] == "stored_metadata"
    assert result["description"].startswith("The report explains")
    assert result["status"] == "STORED_LOCALLY"


@pytest.mark.parametrize("body", ["word " * 80, "한국어문장" * 50, "日本語の文章" * 50, "Texto português " * 30])
def test_description_is_limited_to_150_characters(body: str) -> None:
    result = generate_search_description(title="", body=body, language_code="en")
    assert 0 < result["character_count"] <= MAX_SEARCH_DESCRIPTION_LENGTH


def test_lead_cleanup_does_not_expose_internal_process_or_source_markers() -> None:
    result = generate_search_description(
        title="A factual title", body="A factual title. The agency issued its decision today. [source:source-1]\n\nResearch Package says the report is popular.", language_code="en",
    )
    assert "agency issued its decision" in result["description"]
    assert "Research Package" not in result["description"]
    assert "[source:" not in result["description"]


def test_article_revision_hash_changes_when_content_or_locale_changes() -> None:
    original = article_revision_sha256(title="Title", body="First", language_code="en")
    assert original != article_revision_sha256(title="Title", body="Updated", language_code="en")
    assert original != article_revision_sha256(title="Title", body="First", language_code="de")


class _Result:
    def __init__(self, row: dict[str, Any] | None = None) -> None:
        self.row = row

    def fetchone(self) -> dict[str, Any] | None:
        return self.row


class _AuditConn:
    def __init__(self) -> None:
        self.payload: dict[str, Any] | None = None
        self.insert_count = 0

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _Result:
        if "SELECT payload FROM audit_events" in sql:
            return _Result({"payload": self.payload} if self.payload else None)
        if "INSERT INTO audit_events" in sql:
            value = params[-1]
            assert isinstance(value, Jsonb)
            self.payload = value.obj
            self.insert_count += 1
        return _Result()


def test_generated_description_persists_once_and_is_revision_bound() -> None:
    conn = _AuditConn()
    result = generate_search_description(
        title="Policy update", body="The agency published its final schedule today.", language_code="en",
    )
    digest = article_revision_sha256(title="Policy update", body="The agency published its final schedule today.", language_code="en")
    stored = persist_generated_description(
        conn, content_version_id="cv-1", editorial_version_id="ed-1", import_version_id="iv-1",
        article_sha256=digest, result=result,
    )
    assert stored["status"] == "STORED_LOCALLY"
    assert conn.insert_count == 1
    assert conn.payload["content_version_id"] == "cv-1"
    assert conn.payload["editorial_version_id"] == "ed-1"
    assert conn.payload["article_sha256"] == digest
    loaded = load_generated_description(conn, content_version_id="cv-1", article_sha256=digest)
    assert loaded and loaded["description"] == result["description"]
    persist_generated_description(
        conn, content_version_id="cv-1", editorial_version_id="ed-1", import_version_id="iv-1",
        article_sha256=digest, result=result,
    )
    assert conn.insert_count == 1


def test_empty_article_never_fabricates_a_description() -> None:
    result = generate_search_description(title="", body="", language_code="vi")
    assert result["description"] == ""
    assert result["blogger_status"] == "APPLY_FAILED"
    assert result["html_meta_description_verified"] is False
