"""Deterministic full-article checks; semantic accuracy remains human reviewed."""

import re
from collections import Counter
from typing import Any

from .ai import Draft
from .grounding import inspect

_TREND_LOCALES = {
    "en": "en", "ko": "ko", "ja": "ja", "de": "de", "pt-br": "pt", "pt": "pt",
    "vi": "vi", "zh-cn": "zh", "zh": "zh",
}
_TREND_INTERNAL_PROCESS = {
    "en": re.compile(
        r"\b(?:research package|research worker|publication worker|publish_ready|generation_ready|"
        r"codex (?:generated|wrote|researched)|ai (?:generated|wrote|researched)|"
        r"we (?:searched|collected|analyzed|analysed) (?:the )?(?:web|data|sources)|"
        r"we (?:analyzed|analysed) the collected data|"
        r"this (?:article|draft|manuscript) was (?:generated|written) (?:by|from our research))\b", re.IGNORECASE,
    ),
    "ko": re.compile(
        r"(?:Research Package|Research Worker|Publication Worker|publish_ready|generation_ready|"
        r"Codex가 (?:작성|조사)|AI가 (?:작성|조사)|우리가 (?:웹|자료|출처)를?\s*(?:검색|수집|분석)|"
        r"수집된 데이터를 분석|이번 원고는.{0,30}자료를 기반으로 작성)", re.IGNORECASE,
    ),
    "ja": re.compile(
        r"(?:Research Package|Research Worker|Publication Worker|publish_ready|generation_ready|"
        r"Codexが(?:作成|調査)|AIが(?:作成|調査)|収集したデータを分析|"
        r"この原稿は.{0,30}(?:調査|資料)を基に作成)", re.IGNORECASE,
    ),
    "de": re.compile(
        r"(?:Research Package|Research Worker|Publication Worker|publish_ready|generation_ready|"
        r"Codex (?:hat|erstellte|recherchierte)|KI (?:hat|recherchierte)|"
        r"wir haben (?:Daten|Quellen|das Web) (?:gesammelt|analysiert|durchsucht)|"
        r"dieser (?:Artikel|Entwurf) wurde.{0,30}(?:Recherche|Material) erstellt)", re.IGNORECASE,
    ),
    "pt": re.compile(
        r"(?:Research Package|Research Worker|Publication Worker|publish_ready|generation_ready|"
        r"Codex (?:escreveu|pesquisou|gerou)|IA (?:escreveu|pesquisou|gerou)|"
        r"analisamos os dados coletados|pesquisamos na web|"
        r"este (?:artigo|rascunho) foi (?:gerado|escrito) com base na nossa pesquisa)", re.IGNORECASE,
    ),
    "vi": re.compile(
        r"(?:Research Package|Research Worker|Publication Worker|publish_ready|generation_ready|"
        r"Codex (?:đã viết|đã nghiên cứu)|AI (?:đã viết|đã nghiên cứu)|"
        r"đã phân tích dữ liệu thu thập|chúng tôi đã tìm kiếm trên web|"
        r"bài viết này được (?:tạo|viết) dựa trên quá trình nghiên cứu)", re.IGNORECASE,
    ),
    "zh": re.compile(
        r"(?:Research Package|Research Worker|Publication Worker|publish_ready|generation_ready|"
        r"Codex(?:撰写|调查)|AI(?:撰写|调查)|分析了收集到的数据|我们搜索了网络|"
        r"本文根据(?:以下|上述)研究资料撰写)", re.IGNORECASE,
    ),
}
_TREND_SIGNAL_NARRATION = {
    "en": re.compile(r"\b(?:why .{1,80} is trending|this search (?:term|query|keyword) is trending|search volume (?:surged|rose) on google trends)\b", re.IGNORECASE),
    "ko": re.compile(r"(?:왜.{0,40}(?:검색어|검색어가) 급상승|이번 검색어는.{0,30}(?:관심|인기)|Google Trends에서.{0,30}(?:검색어|검색량).{0,20}(?:급상승|증가))", re.IGNORECASE),
    "ja": re.compile(r"(?:なぜ.{0,40}検索語.{0,20}(?:急上昇|注目)|今回の検索語.{0,30}(?:人気|関心)|Google Trendsで.{0,30}(?:検索語|検索量).{0,20}急上昇)", re.IGNORECASE),
    "de": re.compile(r"(?:warum .{1,80} im trend liegt|dieser suchbegriff ist im trend|suchvolumen.{0,30}(?:stieg|anstieg).{0,20}google trends)", re.IGNORECASE),
    "pt": re.compile(r"(?:por que .{1,80} está em alta|esta palavra-chave está em alta|volume de buscas.{0,30}(?:disparou|aumentou).{0,20}google trends)", re.IGNORECASE),
    "vi": re.compile(r"(?:vì sao .{1,80} đang thịnh hành|từ khóa này đang được quan tâm|lượng tìm kiếm.{0,30}tăng vọt.{0,20}google trends)", re.IGNORECASE),
    "zh": re.compile(r"(?:为什么.{1,40}(?:搜索词|关键词).{0,20}(?:飙升|热门)|本次搜索词.{0,30}(?:热度|关注)|Google Trends显示.{0,30}(?:搜索词|搜索量).{0,20}上升)", re.IGNORECASE),
}
_GENERIC_TREND_TITLE = {
    "en": re.compile(r"^(?:why .{1,100} is trending|why .{1,100} is popular on google trends|what is trending:)", re.IGNORECASE),
    "ko": re.compile(r"^(?:왜 .{1,80} 검색어가 급상승했나|Google Trends에서 주목받는 이유|급상승 검색어 분석)", re.IGNORECASE),
    "ja": re.compile(r"^(?:なぜ.{1,60}が急上昇しているのか|Google Trendsで話題の理由|急上昇検索語の分析)", re.IGNORECASE),
    "de": re.compile(r"^(?:warum .{1,80} im trend liegt|was bei google trends im trend liegt)", re.IGNORECASE),
    "pt": re.compile(r"^(?:por que .{1,80} está em alta|o que está em alta no google trends)", re.IGNORECASE),
    "vi": re.compile(r"^(?:vì sao .{1,80} đang thịnh hành|điều gì đang thịnh hành trên google trends)", re.IGNORECASE),
    "zh": re.compile(r"^(?:为什么.{1,50}搜索热度上升|Google Trends热门搜索词分析)", re.IGNORECASE),
}
_GENERIC_FILLER = {
    "en": re.compile(r"\b(?:it remains to be seen|time will tell|in today's fast-changing world|there are many factors to consider)\b", re.IGNORECASE),
    "ko": re.compile(r"(?:앞으로 지켜볼 필요가 있다|다양한 요인이 작용할 수 있다|관심이 쏠리고 있다)$"),
    "ja": re.compile(r"(?:今後の動向を見守る必要がある|さまざまな要因が影響する可能性がある|注目が集まっている)$"),
    "de": re.compile(r"\b(?:es bleibt abzuwarten|die zeit wird es zeigen|es gibt viele faktoren zu berücksichtigen)\b", re.IGNORECASE),
    "pt": re.compile(r"\b(?:ainda é preciso esperar para ver|o tempo dirá|há muitos fatores a considerar)\b", re.IGNORECASE),
    "vi": re.compile(r"(?:vẫn cần chờ xem|thời gian sẽ trả lời|có nhiều yếu tố cần cân nhắc)$", re.IGNORECASE),
    "zh": re.compile(r"(?:仍有待观察|时间会给出答案|有许多因素需要考虑)$"),
}


def inspect_trend_article(title: str, body: str, language: str) -> dict[str, Any]:
    """Deterministic reader-facing checks; never establish event truth or semantic support."""
    locale = _TREND_LOCALES.get(language.casefold()) or _TREND_LOCALES.get(language.split("-", 1)[0].casefold())
    if locale is None:
        return {"supported_locale": False, "checks": {}, "issues": ["trend_locale_not_configured"],
                "semantic_verification": "not_performed"}
    text = f"{title}\n{body}"
    internal_leak = bool(_TREND_INTERNAL_PROCESS[locale].search(text))
    signal_narration = bool(_TREND_SIGNAL_NARRATION[locale].search(text))
    # Google Trends can itself be the reported subject. Explicit reporting of a
    # product/report release is distinct from narration of our discovery process.
    trends_story = bool(re.search(
        r"(?is)google trends.{0,90}(?:launch|release|publish|announce|report|update|introduc|rolled out|"
        r"발표|출시|공개|報告|発表|公開|veröffentlicht|vorgestellt|lanc|publicou|anunci|"
        r"công bố|ra mắt|发布|推出)", title + " " + body[:900]))
    signal_narration = signal_narration and not trends_story
    title_is_keyword_report = bool(_GENERIC_TREND_TITLE[locale].search(title.strip()))
    prose = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip() and not re.match(r"^#{1,3}\s", p.strip())]
    normalized = [re.sub(r"\s+", " ", re.sub(r"\[source:[^\]]+\]", "", p)).casefold() for p in prose]
    duplicates = sum(count - 1 for count in Counter(normalized).values() if count > 1)
    filler_paragraphs = [p for p in prose if _GENERIC_FILLER[locale].search(p.strip(" \t.,:;!?。！？"))]
    duplicate_ratio = duplicates / max(1, len(prose))
    checks = {
        "no_internal_process_leakage": not internal_leak,
        "event_not_keyword_report": not signal_narration and not title_is_keyword_report,
        "information_density": duplicate_ratio <= 0.2 and len(filler_paragraphs) <= max(0, len(prose) // 5),
    }
    issues = [key for key, passed in checks.items() if not passed]
    return {
        "supported_locale": True,
        "checks": checks,
        "issues": issues,
        "prose_paragraph_count": len(prose),
        "duplicate_paragraph_count": duplicates,
        "generic_filler_paragraph_count": len(filler_paragraphs),
        "semantic_verification": "not_performed",
        "trends_service_is_reported_subject": trends_story,
    }


def search_intent_phrase(keyword: str) -> str:
    """Drop an appended date qualifier from a long topic label without inventing a query."""
    value = " ".join(keyword.split())
    value = re.split(
        r"\s+(?:on|dated|as of)\s+(?=(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|"
        r"Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|"
        r"Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?|\d{4}\b))",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    return value if 1 <= len(value) <= 80 else ""


def _tokens(value: str) -> list[str]:
    tokens: list[str] = []
    for segment in re.findall(
        r"[A-Za-z0-9]+|[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]+", value.casefold()
    ):
        if re.search(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]", segment):
            tokens.extend(segment[i : i + 2] for i in range(max(1, len(segment) - 1)))
        else:
            tokens.append(segment)
    return tokens


def longest_source_overlap(body: str, sources: list[dict[str, Any]]) -> int:
    """Largest consecutive word run copied verbatim from one source excerpt."""
    body_tokens = _tokens(body)
    longest = 0
    for source in sources:
        source_tokens = _tokens(str(source.get("evidence", "")))
        if not body_tokens or not source_tokens:
            continue
        # Bound the check while detecting short excerpt copying.
        for start in range(len(source_tokens)):
            matched = 0
            for body_start in range(len(body_tokens)):
                count = 0
                while (
                    start + count < len(source_tokens)
                    and body_start + count < len(body_tokens)
                    and source_tokens[start + count] == body_tokens[body_start + count]
                ):
                    count += 1
                    if count >= 30:
                        break
                matched = max(matched, count)
                if matched >= 30:
                    break
            longest = max(longest, matched)
            if longest >= 30:
                return longest
    return longest


def evaluate(
    draft: Draft, sources: list[dict[str, Any]], language: str, as_of: str, fact_count: int,
    *, google_trends_based: bool = False,
) -> dict[str, Any]:
    grounded = inspect(draft, sources, language, as_of)
    headings = re.findall(r"(?m)^\s*#{2,3}\s+.+$", draft.body)
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", draft.body) if len(_tokens(p)) >= 5]
    title_tokens = {token for token in _tokens(draft.title) if len(token) >= 2}
    body_tokens = set(_tokens(draft.body))
    keyword_tokens = {
        token for keyword in draft.keywords for token in _tokens(keyword) if len(token) >= 2
    }
    keyword_coverage = bool(keyword_tokens & (set(_tokens(draft.title)) | body_tokens))
    # A filing date can be a legitimate part of a search query. Reject identifiers,
    # not date-shaped factual qualifiers (which were previously misclassified).
    keyword_metadata_clean = len(draft.keywords) <= 6 and not any(
        re.search(
            r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b"
            r"|\b(?:phase\d+(?:\.\d+)?|source|fact|run|evaluation|version)[-_:/][a-z0-9-]{6,}\b",
            keyword,
            re.IGNORECASE,
        )
        for keyword in draft.keywords
    )
    source_text = " ".join(str(source.get("evidence", "")) for source in sources).casefold()
    legal_access_phrases = re.findall(
        r"\b(?:public record|publicly available|publicly accessible|free to (?:access|reuse)|copyright(?:ed)?)\b",
        (draft.title + "\n" + draft.body + "\n" + draft.summary).casefold(),
    )
    source_rights_claims_supported = all(phrase in source_text for phrase in legal_access_phrases)
    source_overlap = longest_source_overlap(draft.body, sources)
    user_text = "\n".join((draft.title, draft.summary, draft.body, *draft.keywords))
    user_text_without_citations = re.sub(r"\[source:[^\]]+\]", "", user_text)
    no_internal_ids = not re.search(
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
        user_text_without_citations,
        re.IGNORECASE,
    )
    scripts = {
        "hangul": len(re.findall(r"[\uac00-\ud7af]", user_text)),
        "kana": len(re.findall(r"[\u3040-\u30ff]", user_text)),
        "cyrillic": len(re.findall(r"[\u0400-\u04ff]", user_text)),
        "arabic": len(re.findall(r"[\u0600-\u06ff]", user_text)),
    }
    forbidden_script = (
        scripts["cyrillic"] > 0 or scripts["arabic"] > 0
        or (language == "ko" and scripts["kana"] > 0)
        or (language.startswith("zh") and (scripts["hangul"] > 0 or scripts["kana"] > 0))
        or (language == "ja" and scripts["hangul"] > 0)
        or (language == "en" and any(scripts[key] > 0 for key in ("hangul", "kana")))
    )
    target_script_present = (
        scripts["hangul"] > 0 if language == "ko"
        else scripts["kana"] > 0 if language == "ja"
        else bool(re.search(r"[\u3400-\u9fff]", user_text)) if language.startswith("zh")
        else bool(re.search(r"[A-Za-z]", user_text)) if language == "en"
        else True
    )
    # Adapt length to available evidence. Narrow filing metadata is not padded
    # to a generic SEO word target; sections and support still have to be present.
    threshold = 3 if fact_count >= 4 else 2
    checks = {
        **grounded["rule_checks"],
        "no_internal_fact_markers": not re.search(
            r"\bFACT-F(?:\d+|n)\s*:", user_text, re.IGNORECASE
        ),
        "article_structure": len(headings) >= threshold and len(paragraphs) >= threshold,
        "title_body_alignment": bool(title_tokens & body_tokens) if title_tokens else False,
        "keyword_search_intent_coverage": keyword_coverage,
        "keywords_are_search_terms_not_internal_ids": keyword_metadata_clean,
        "no_internal_ids_in_user_text": no_internal_ids,
        "keyword_list_is_bounded_and_unique": (
            1 <= len(draft.keywords) <= 6
            and len({" ".join(keyword.casefold().split()) for keyword in draft.keywords})
            == len(draft.keywords)
            and all(1 <= len(keyword.strip()) <= 80 for keyword in draft.keywords)
        ),
        "no_forbidden_foreign_script_mixing": not forbidden_script,
        "target_writing_system_present": target_script_present,
        "legal_access_claims_grounded_in_supplied_source": source_rights_claims_supported,
        "no_mass_direct_quote": source_overlap < 25,
    }
    trend_quality = inspect_trend_article(draft.title, draft.body, language) if google_trends_based else None
    if trend_quality:
        checks.update({f"trend_{name}": passed for name, passed in trend_quality["checks"].items()})
    return {
        "checks": checks,
        "trend_article_quality": trend_quality,
        "machine_passed": all(checks.values()),
        "grounding_details": {
            key: grounded[key]
            for key in (
                "proper_name_candidates",
                "missing_proper_names",
                "unsupported_proper_names",
                "unexpected_numbers",
                "uncited_paragraphs",
                "invalid_source_urls",
            )
            if key in grounded
        },
        "human_review_required": True,
        "semantic_accuracy": "human_review_required",
        "naturalness": "human_review_required",
        "rights_review": "human_review_required",
        "publish_ready": False,
        "word_count": len(_tokens(draft.body)),
        "section_count": len(headings),
        "paragraph_count": len(paragraphs),
        "source_overlap_words_max": source_overlap,
        "fact_count": fact_count,
        "script_counts": scripts,
        "search_intent": "Summarize and explain the supplied official filing/release; not investment advice",
    }
