"""Evidence-first experimental rendering that never invents factual prose."""

from datetime import UTC, date, datetime
from typing import Any

from .ai import Draft
from .grounding import extract_facts, inspect


def build_evidence_template(
    sources: list[dict[str, Any]], language: str, keyword: str, as_of: str | None = None
) -> tuple[Draft, dict[str, Any]]:
    facts = extract_facts(sources)
    if not facts:
        raise ValueError("verified_evidence_required")
    if language not in {"en", "ko"}:
        raise ValueError("template_language_not_evaluated")
    unique_facts: dict[str, dict[str, Any]] = {}
    for fact in facts:
        key = fact["text"].casefold()
        unique_facts.setdefault(key, {"text": fact["text"], "source_ids": []})
        if fact["source_id"] not in unique_facts[key]["source_ids"]:
            unique_facts[key]["source_ids"].append(fact["source_id"])
    rendered_facts = list(unique_facts.values())
    source_ids = list(dict.fromkeys(fact["source_id"] for fact in facts))
    if language == "ko":
        title = f"{keyword}: 공식 자료로 확인한 내용"
        summary = "검증된 출처의 원문 근거만 정리한 검토용 초안입니다."
        body = f"## {keyword}\n\n## 공식 자료의 근거\n\n" + "\n\n".join(
            "> " + fact["text"] + " " + " ".join(
                f"[source:{source_id}]" for source_id in fact["source_ids"]
            ) for fact in rendered_facts
        )
        body += "\n\n## 출처\n" + "\n".join(
            f"- {source.get('source_name', 'Source')}: {source['url']} [source:{source['id']}]"
            for source in sources
        )
        body += f"\n\n자료 기준일: {as_of or date.today().isoformat()}"
    else:
        title = f"{keyword}: Verified source notes"
        summary = "Review draft containing only evidence text from the recorded sources."
        body = f"## {keyword}\n\n## Evidence from the reviewed source\n\n" + "\n\n".join(
            "> " + fact["text"] + " " + " ".join(
                f"[source:{source_id}]" for source_id in fact["source_ids"]
            ) for fact in rendered_facts
        )
        body += "\n\n## Sources\n" + "\n".join(
            f"- {source.get('source_name', 'Source')}: {source['url']} [source:{source['id']}]"
            for source in sources
        )
        body += f"\n\nEvidence checked as of {as_of or date.today().isoformat()}."
    draft = Draft(
        title=title,
        body=body,
        summary=summary,
        keywords=[keyword],
        source_ids=source_ids,
    )
    return draft, {"fact_count": len(rendered_facts), "source_ids": source_ids, "ai_calls": 0}


def build_localized_evidence_template(
    sources: list[dict[str, Any]], localized_facts: list[dict[str, Any]], language: str,
    title: str, summary: str, keywords: list[str],
) -> tuple[Draft, dict[str, Any]]:
    """Compose only already checked localized fact spans into a new review draft."""
    import langcodes

    if not langcodes.tag_is_valid(language):
        raise ValueError("invalid_target_language")
    if not sources or not localized_facts:
        raise ValueError("verified_evidence_required")
    if any(item.get("target_language") != language or item.get("status") != "machine_passed"
           for item in localized_facts):
        raise ValueError("localization_quality_held")
    allowed_ids = {str(source["id"]) for source in sources}
    used_ids = list(dict.fromkeys(
        str(source_id) for item in localized_facts for source_id in item.get("source_ids", [])
    ))
    if not used_ids or not set(used_ids).issubset(allowed_ids):
        raise ValueError("localization_source_link_invalid")
    body = "\n\n".join(
        str(item["text"]).strip() + " " + " ".join(
            f"[source:{source_id}]" for source_id in item["source_ids"]
        ) for item in localized_facts
    )
    draft = Draft(title=title, body=body, summary=summary, keywords=keywords, source_ids=used_ids)
    checks = inspect(draft, sources, language, datetime.now(UTC).date().isoformat())
    if not checks["rule_pass"]:
        raise ValueError("localized_draft_quality_held")
    return draft, {
        "fact_count": len(localized_facts), "source_ids": used_ids,
        "ai_calls": sum(int(item.get("ai_calls", 0)) for item in localized_facts),
        "checks": checks, "human_review_required": True, "publish_ready": False,
    }
