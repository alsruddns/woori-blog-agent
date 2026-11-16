import pytest
from woori.editorial_html import resolve_blogger_labels
from woori.language_codes import normalize_language_tag
from woori.multilingual import GENERATION_ADAPTERS, QUALITY_ADAPTERS, TRANSLATION_ADAPTERS


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("de", "de"),
        ("pt-BR", "pt-BR"),
        ("pt-br", "pt-BR"),
        ("vi", "vi"),
        ("zh-cn", "zh-CN"),
        ("EN", "en"),
    ],
)
def test_language_tag_uses_bcp47_canonicalization(value: str, expected: str) -> None:
    assert normalize_language_tag(value) == expected


@pytest.mark.parametrize("value", ["", "en_US", "not a tag"])
def test_language_tag_rejects_invalid_or_unsupported_shape(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_language_tag(value)


@pytest.mark.parametrize(
    ("language", "expected_issue"),
    [("de", "Aktuelles"), ("pt-BR", "Atualidades"), ("vi", "Tin tức")],
)
def test_new_language_trends_label_is_available_without_enabling_trends_collection(
    language: str, expected_issue: str
) -> None:
    assert resolve_blogger_labels(language, True, []) == [expected_issue]


def test_no_generation_translation_or_quality_adapter_is_enabled_by_language_registration() -> None:
    assert GENERATION_ADAPTERS == {}
    assert TRANSLATION_ADAPTERS == {}
    assert QUALITY_ADAPTERS == {}
