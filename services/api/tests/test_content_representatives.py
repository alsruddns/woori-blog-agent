from __future__ import annotations

from woori.content_representatives import dedupe_manuscript_rows, same_manuscript_content


def test_identical_title_and_revision_body_keep_newest_but_different_body_survives() -> None:
    base = "The agency published a reporting schedule that explains the planned implementation date. " * 6
    revised = "The agency published a reporting schedule that explains the planned implementation date. " * 5 + (
        "Organizations should use the current notice for the exact reporting requirements. "
    )
    newest = {"id": "new", "title": "Official Agency policy change and reporting schedule",
              "language_code": "en", "target_blog_id": "blog-en", "received_at": 3,
              "body_markdown": revised}
    older_copy = {**newest, "id": "old", "received_at": 2, "body_markdown": base}
    separate_article = {**newest, "id": "separate", "received_at": 1,
                        "body_markdown": "A different policy notice concerns unrelated licensing rules. " * 8}

    representatives, suppressed = dedupe_manuscript_rows([newest, older_copy, separate_article])

    assert [row["id"] for row in representatives] == ["new", "separate"]
    assert suppressed == 1


def test_same_title_alone_does_not_dedupe_and_target_blog_is_a_boundary() -> None:
    body_a = "The agency schedule explains reporting requirements and implementation dates. " * 4
    body_b = "Readers can review the agency notice to understand a separate reporting process. " * 4
    rows = [
        {"id": "a", "title": "Same title", "language_code": "en", "target_blog_id": "blog-1", "body_markdown": body_a},
        {"id": "b", "title": "Same title", "language_code": "en", "target_blog_id": "blog-1", "body_markdown": body_b},
        {"id": "c", "title": "Same title", "language_code": "en", "target_blog_id": "blog-2", "body_markdown": body_a},
    ]
    representatives, suppressed = dedupe_manuscript_rows(rows)
    assert len(representatives) == 3
    assert suppressed == 0
    assert not same_manuscript_content("Same title", body_a, "Same title", body_b)
