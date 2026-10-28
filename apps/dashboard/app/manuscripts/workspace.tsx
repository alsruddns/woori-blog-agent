"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import styles from "./article-preview.module.css";

type Row = Record<string, unknown>;
type ListResult = { items: Row[]; page: number; page_size: number; total: number; languages: string[]; categories: string[] };
type LocalizedTarget = Row & { language_code: string; blog_id: string; already_published: boolean; recommended: boolean; existing_localization: Row | null; published_posts: Row[] };
type LocalizedPlan = Row & { source: Row; targets: LocalizedTarget[]; requests: Row[]; languages_without_active_blog: Row[]; generation_provider_available: boolean; live_blogger_writes_enabled: false; automatic_publishing_enabled: false };
const value = (row: Row | null | undefined, key: string) => String(row?.[key] ?? "");
const koreanLanguage = (code: string) => ({ ko: "한국어", en: "영어", "zh-CN": "중국어 간체", ja: "일본어" } as Record<string, string>)[code] ?? code;
const recommendationLabel = (reason: string) => reason === "regional_language_and_reader_relevance_require_editorial_selection"
  ? "지역 코드만으로 언어를 정하지 않습니다. 독자 관련성을 직접 검토하세요."
  : reason === "direct_region_language_match" ? "지역·언어 일치 참고 후보이며 독자 관련성을 확인해야 합니다."
    : "지역 정보만으로 게시 언어를 추천하지 않습니다.";
const dateLabel = (raw: string) => { const date = new Date(raw); return Number.isNaN(date.valueOf()) ? "—" : new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Seoul" }).format(date); };
const statusLabel = (raw: string, passed: boolean) => {
  if (raw === "editorial_review_passed") return "편집 검토 통과";
  if (raw === "in_review") return "검토 중";
  if (raw === "revision_needed") return "수정 필요";
  if (raw === "failed") return "처리 실패";
  return passed ? "사람 검토 대기" : "품질 검토 필요";
};
const escapeHtml = (s: string) => s.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#39;");

function markdownHtml(source: string) {
  const blocks = source.split(/\n\s*\n/).map(part => part.trim()).filter(Boolean);
  return blocks.map(block => {
    if (/^###\s/.test(block)) return `<h3>${escapeHtml(block.replace(/^###\s+/, ""))}</h3>`;
    if (/^##\s/.test(block)) return `<h2>${escapeHtml(block.replace(/^##\s+/, ""))}</h2>`;
    const lines = block.split("\n");
    if (lines.every(line => /^\s*[-*]\s/.test(line))) return `<ul>${lines.map(line => `<li>${escapeHtml(line.replace(/^\s*[-*]\s/, ""))}</li>`).join("")}</ul>`;
    if (lines.every(line => /^\s*\d+\.\s/.test(line))) return `<ol>${lines.map(line => `<li>${escapeHtml(line.replace(/^\s*\d+\.\s/, ""))}</li>`).join("")}</ol>`;
    return `<p>${escapeHtml(block).replaceAll("\n", "<br>")}</p>`;
  }).join("");
}

type SeoCheck = { key: string; status: "ready" | "review" | "not_measured"; message: string };
type RenderedPreview = { title: string; language_code: string; post_html: string; labels: string[]; title_in_body: boolean; publication_performed: boolean; renderer_version: string; design_system_version: string; seo_metadata: Row; seo_checks: SeoCheck[]; publication_package?: Row };

function HtmlPreview({ html, title, lang }: { html: string; title: string; lang: string }) {
  const previewHtml = html.replace(/<img\b([^>]*)>/gi, (_tag, attributes: string) => {
    const alt = attributes.match(/\balt="([^"]*)"/i)?.[1] ?? "이미지";
    return `<div class="wb-image-placeholder" role="img" aria-label="${alt}">${alt}<small>이미지 미리보기에서는 외부 요청을 보내지 않습니다.</small></div>`;
  });
  const source = `<!doctype html><html lang="${escapeHtml(lang)}"><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'self';"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/blogger-editorial.css"></head><body><main class="wb-preview-shell"><h1 class="wb-post-title">${escapeHtml(title)}</h1>${previewHtml}</main></body></html>`;
  return <iframe className={styles.iframe} title="게시 화면 미리보기. 제목은 Blogger 게시글 제목 영역을 나타냅니다." sandbox="" srcDoc={source} />;
}

export default function ManuscriptWorkspace() {
  const [filters, setFilters] = useState({ q: "", language: "", category: "", status: "", sort: "newest", page: 1 });
  const [pageSize, setPageSize] = useState(25);
  const [searchText, setSearchText] = useState("");
  const [data, setData] = useState<ListResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<Row | null>(null);
  const [detail, setDetail] = useState<Row | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [tab, setTab] = useState("body");
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  const [googleTrendsBased, setGoogleTrendsBased] = useState(false);
  const [localizedPlan, setLocalizedPlan] = useState<LocalizedPlan | null>(null);
  const [localizedPlanLoading, setLocalizedPlanLoading] = useState(false);
  const [localizedSelection, setLocalizedSelection] = useState<Record<string, boolean>>({});
  const [oneTimeAutoPublishRequested, setOneTimeAutoPublishRequested] = useState(false);
  const [localizedRequester, setLocalizedRequester] = useState("");
  const [localizedSelectionReason, setLocalizedSelectionReason] = useState("");
  const [previewMode, setPreviewMode] = useState<"rendered" | "source" | "seo" | "package">("rendered");
  const [targetBlogRecordId, setTargetBlogRecordId] = useState("");
  const [renderedPreviewState, setRenderedPreviewState] = useState<{ key: string; result: RenderedPreview } | null>(null);
  const [previewErrorState, setPreviewErrorState] = useState<{ key: string; message: string } | null>(null);
  const dialog = useRef<HTMLElement>(null);
  const previousFocus = useRef<HTMLElement | null>(null);
  const requestSequence = useRef(0);
  const detailSequence = useRef(0);
  const deepLinkOpened = useRef(false);

  useEffect(() => { const timer = setTimeout(() => setFilters(current => ({ ...current, q: searchText, page: 1 })), 250); return () => clearTimeout(timer); }, [searchText]);
  useEffect(() => {
    const controller = new AbortController();
    const id = ++requestSequence.current;
    const params = new URLSearchParams({ page: String(filters.page), page_size: String(pageSize), sort: filters.sort });
    if (filters.q.trim()) params.set("q", filters.q.trim());
    if (filters.language) params.set("language", filters.language);
    if (filters.category) params.set("category", filters.category);
    if (filters.status) params.set("status", filters.status);
    fetch(`/api/research/manuscripts?${params}`, { cache: "no-store", signal: controller.signal })
      .then(async response => { if (!response.ok) throw new Error("원고 목록을 불러오지 못했습니다."); return await response.json() as ListResult; })
      .then(result => { if (requestSequence.current === id) setData(result); })
      .catch(() => { if (!controller.signal.aborted && requestSequence.current === id) setError("원고 목록을 불러오지 못했습니다. 연결 상태를 확인한 뒤 다시 시도해 주세요."); })
      .finally(() => { if (requestSequence.current === id) setLoading(false); });
    return () => controller.abort();
  }, [filters, pageSize]);

  const openDetail = useCallback(async (row: Row, trigger: HTMLElement) => {
    const requestId = ++detailSequence.current;
    previousFocus.current = trigger;
    setSelected(row); setDetail(null); setTab("body"); setMessage(""); setDetailLoading(true); setPreviewMode("rendered"); setRenderedPreviewState(null); setGoogleTrendsBased(false); setTargetBlogRecordId(""); setLocalizedPlan(null); setLocalizedSelection({}); setOneTimeAutoPublishRequested(false); setLocalizedRequester(""); setLocalizedSelectionReason("");
    document.body.classList.add("sheet-open");
    try {
      const response = await fetch(`/api/research/manuscripts/${encodeURIComponent(value(row, "evaluation_id"))}/${encodeURIComponent(value(row, "content_version_id"))}`, { cache: "no-store" });
      if (!response.ok) throw new Error("원고 상세 정보를 불러오지 못했습니다.");
      const result = await response.json() as Row;
      if (detailSequence.current === requestId) {
        setDetail(result);
        const localeLabel = ({ ko: "이슈", en: "Issues", ja: "話題", "zh-CN": "热点" } as Record<string, string>)[value(result, "language_code")];
        const existingLabels = ((result.editorial_versions as Row[] | undefined)?.[0]?.blogger_labels as string[] | undefined) ?? [];
        setTargetBlogRecordId(value((result.editorial_versions as Row[] | undefined)?.[0] ?? {}, "target_blog_id"));
        setGoogleTrendsBased(Boolean(result.google_trends_based) || Boolean(localeLabel && existingLabels.includes(localeLabel)));
      }
      requestAnimationFrame(() => { if (detailSequence.current === requestId) dialog.current?.focus(); });
    } catch { setMessage("선택한 원고 상세 정보를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요."); }
    finally { setDetailLoading(false); }
  }, []);
  useEffect(() => {
    if (!data || deepLinkOpened.current) return;
    const params = new URLSearchParams(window.location.search);
    const evaluationId = params.get("open_evaluation_id");
    const versionId = params.get("open_content_version_id");
    if (!evaluationId || !versionId) return;
    deepLinkOpened.current = true;
    const row = data.items.find(item => value(item, "evaluation_id") === evaluationId && value(item, "content_version_id") === versionId)
      ?? { evaluation_id: evaluationId, content_version_id: versionId, title: "원고 상세" };
    const frame = window.requestAnimationFrame(() => void openDetail(row, document.body));
    return () => window.cancelAnimationFrame(frame);
  }, [data, openDetail]);
  const closeDetail = useCallback(() => {
    detailSequence.current += 1;
    setSelected(null); setDetail(null); document.body.classList.remove("sheet-open");
    requestAnimationFrame(() => previousFocus.current?.focus());
  }, []);
  const loadLocalizedPlan = async () => {
    if (!detail) return;
    setLocalizedPlanLoading(true); setMessage("");
    try {
      const response = await fetch(`/api/research/localized-publications/targets/${encodeURIComponent(value(detail, "id"))}/${encodeURIComponent(value(detail, "content_version_id"))}`, { cache: "no-store" });
      const payload = await response.json() as LocalizedPlan & Row;
      if (!response.ok) throw new Error(String(payload.detail ?? payload.error ?? "다국어 게시 대상을 불러오지 못했습니다."));
      setLocalizedPlan(payload);
      setLocalizedSelection({});
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : "다국어 게시 대상을 불러오지 못했습니다."); }
    finally { setLocalizedPlanLoading(false); }
  };

  const submitLocalizedRequests = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!detail || !localizedPlan) return;
    const form = new FormData(event.currentTarget);
    const requester = String(form.get("requester") ?? "").trim();
    const targets = localizedPlan.targets.filter(target => localizedSelection[`${target.language_code}:${target.blog_id}`]).map(target => ({ language_code: target.language_code, blog_id: target.blog_id, selection_reason: localizedSelectionReason.trim() }));
    if (!targets.length || requester.length < 2 || localizedSelectionReason.trim().length < 10) { setMessage("요청자, 대상 언어·블로그와 독자 관련성 사유(10자 이상)를 입력하세요."); return; }
    setSaving(true); setMessage("");
    try {
      const response = await fetch("/api/research/localized-publications/requests", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ evaluation_id: value(detail, "id"), source_content_version_id: value(detail, "content_version_id"), targets, requester, idempotency_key: crypto.randomUUID(), explicit_confirmation: true, one_time_auto_publish_requested: oneTimeAutoPublishRequested }),
      });
      const payload = await response.json() as Row;
      if (!response.ok) throw new Error(String(payload.detail ?? payload.error ?? "요청을 저장하지 못했습니다."));
      const items = Array.isArray(payload.items) ? payload.items as Row[] : [];
      setMessage(items.map(item => `${value(item, "language_code")}: ${value(item, "state")}${item.duplicate ? " (기존 요청 또는 게시글)" : ""}`).join(" · ") || "요청 상태를 확인할 수 없습니다.");
      await loadLocalizedPlan();
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : "요청을 저장하지 못했습니다."); }
    finally { setSaving(false); }
  };
  const cancelLocalizedRequest = async (requestId: string) => {
    if (localizedRequester.trim().length < 2) { setMessage("요청을 취소하려면 요청자 이름을 입력하세요."); return; }
    setSaving(true); setMessage("");
    try {
      const response = await fetch(`/api/research/localized-publications/requests/${encodeURIComponent(requestId)}/cancel`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ actor: localizedRequester.trim(), reason: "사용자가 다국어 원고 요청을 취소했습니다.", idempotency_key: crypto.randomUUID() }),
      });
      const payload = await response.json() as Row;
      if (!response.ok) throw new Error(String(payload.detail ?? payload.error ?? "요청을 취소하지 못했습니다."));
      setMessage(`다국어 요청 상태: ${value(payload, "state")}`);
      await loadLocalizedPlan();
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : "요청을 취소하지 못했습니다."); }
    finally { setSaving(false); }
  };
  useEffect(() => {
    if (!selected) return;
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") closeDetail();
      if (event.key === "Tab" && dialog.current) {
        const focusables = [...dialog.current.querySelectorAll<HTMLElement>('button:not([disabled]),a[href],input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex="0"]')];
        if (!focusables.length) { event.preventDefault(); return; }
        const first = focusables[0], last = focusables[focusables.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
    };
    window.addEventListener("keydown", onKey); return () => window.removeEventListener("keydown", onKey);
  }, [selected, closeDetail]);

  const submit = useCallback(async (path: string, body: Row) => {
    setSaving(true); setMessage("");
    try {
      const response = await fetch(`/api/research/${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const payload = await response.json() as Row;
      if (!response.ok) throw new Error(String(payload.detail ?? payload.error ?? "저장 요청이 거부되었습니다."));
      setMessage(path === "publication-approvals" ? "승인 기록을 저장했습니다. 실제 Blogger 게시와 자동 발행은 차단되어 있습니다." : "검토 기록을 저장했습니다.");
      if (selected) {
        const response = await fetch(`/api/research/manuscripts/${encodeURIComponent(value(selected, "evaluation_id"))}/${encodeURIComponent(value(selected, "content_version_id"))}`, { cache: "no-store" });
        if (response.ok) setDetail(await response.json() as Row);
      }
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : "저장 실패"); }
    finally { setSaving(false); }
  }, [selected]);

  const submitRevision = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); if (!detail) return;
    const form = new FormData(event.currentTarget);
    const languageLabel = ({ ko: "이슈", en: "Issues", ja: "話題", "zh-CN": "热点" } as Record<string, string>)[value(detail, "language_code")];
    const selectedLabels = String(form.get("labels") ?? "").split(",").map(item => item.trim()).filter(Boolean);
    const bloggerLabels = googleTrendsBased && languageLabel
      ? [languageLabel, ...selectedLabels.filter(label => label.toLocaleLowerCase() !== languageLabel.toLocaleLowerCase())]
      : selectedLabels;
    await submit("article-revisions", {
      evaluation_id: value(detail, "id"), content_version_id: value(detail, "content_version_id"),
      base_editorial_version_id: value((detail.editorial_versions as Row[] | undefined)?.[0], "id") || null,
      idempotency_key: crypto.randomUUID(), reviewer_name: String(form.get("reviewer") ?? ""), reason: String(form.get("reason") ?? ""),
      title: String(form.get("title") ?? ""), body: "", html_body: String(form.get("html_body") ?? ""),
      summary: String(form.get("summary") ?? ""), seo_description: String(form.get("summary") ?? ""),
      keywords: String(form.get("keywords") ?? "").split("|").map(item => item.trim()).filter(Boolean),
      blogger_labels: bloggerLabels,
      seo_metadata: {
        language_code: value(detail, "language_code"), target_region: String(form.get("target_region") ?? "").trim() || null,
        search_intent: String(form.get("search_intent") ?? "") || null,
        primary_keyword: String(form.get("primary_keyword") ?? "").trim() || null,
        related_terms: String(form.get("keywords") ?? "").split("|").map(item => item.trim()).filter(Boolean).slice(1),
        seo_title_candidates: String(form.get("seo_title_candidates") ?? "").split("|").map(item => item.trim()).filter(Boolean),
        seo_title: String(form.get("title") ?? "").trim(), search_description: String(form.get("summary") ?? "").trim(),
        core_question: String(form.get("core_question") ?? "").trim() || null,
        core_answer: String(form.get("core_answer") ?? "").trim() || null,
        category: value(detail, "category_slug") || null, blogger_labels: bloggerLabels,
        official_sources: [], author: null, fact_verified_at: null, editorial_status: "unknown",
      },
      target_blog_id: null, publication_mode: "manual", planned_publish_at: null,
    });
  };

  const reviews = (detail?.review_history as Row[] | undefined) ?? [];
  const revisions = (detail?.editorial_versions as Row[] | undefined) ?? [];
  const approvals = (detail?.publication_approval_events as Row[] | undefined) ?? [];
  const latestRevision = revisions[0];
  const latestSeo = (latestRevision?.seo_metadata as Row | undefined) ?? {};
  const bloggerTargets = (detail?.blogger_targets as Row[] | undefined) ?? [];
  const machinePassed = Boolean(latestRevision ? latestRevision.machine_passed : detail?.machine_passed);
  const latestReview = reviews[0];
  const body = value(detail, "saved_body") || value(detail, "body");
  const htmlBody = value(latestRevision ?? {}, "html_body") || (value(detail, "body_format") === "html" ? value(detail, "safe_body_html") : markdownHtml(body));
  const latestApproval = approvals[0];
  const publicationApproved = value(latestApproval ?? {}, "action") === "approved";
  const previewKey = JSON.stringify([
    value(selected, "content_version_id"), value(latestRevision ?? {}, "id"), googleTrendsBased, targetBlogRecordId,
  ]);
  const renderedPreview = renderedPreviewState?.key === previewKey ? renderedPreviewState.result : null;
  const previewError = previewErrorState?.key === previewKey ? previewErrorState.message : "";
  const previewLoading = Boolean(detail && tab === "body" && !renderedPreview && !previewError);

  useEffect(() => {
    if (!detail || tab !== "body") return;
    const controller = new AbortController();
    const revision = ((detail.editorial_versions as Row[] | undefined) ?? [])[0];
    const revisionSeo = (revision?.seo_metadata as Row | undefined) ?? {};
    const revisionHtml = value(revision ?? {}, "html_body");
    const bodyValue = revisionHtml || value(detail, "saved_body") || value(detail, "body");
    const bodyFormat = revisionHtml || value(detail, "body_format") === "html" ? "html" : "markdown";
    const labels = (revision?.blogger_labels as string[] | undefined) ?? [];
    fetch("/api/research/editorial-preview", {
      method: "POST", headers: { "Content-Type": "application/json" }, signal: controller.signal,
      body: JSON.stringify({
        title: value(revision ?? {}, "title") || value(detail, "saved_title") || value(detail, "title"),
        body: bodyValue, body_format: bodyFormat,
        summary: value(revision ?? {}, "seo_description") || value(detail, "summary"),
        language_code: value(detail, "language_code"), google_trends_based: googleTrendsBased, labels,
        target_blog_record_id: targetBlogRecordId || null,
        content_version_id: value(detail, "content_version_id") || null,
        editorial_revision_id: value(revision ?? {}, "id") || null,
        revision_number: revision?.revision_number ?? null,
        seo_metadata: {
          language_code: value(detail, "language_code"),
          target_region: value(revisionSeo, "target_region") || null,
          search_intent: value(revisionSeo, "search_intent") || null,
          primary_keyword: value(revisionSeo, "primary_keyword") || ((detail.keywords as string[] | undefined) ?? [])[0] || null,
          related_terms: (revisionSeo.related_terms as string[] | undefined) ?? ((detail.keywords as string[] | undefined) ?? []).slice(1),
          seo_title_candidates: (revisionSeo.seo_title_candidates as string[] | undefined) ?? [],
          seo_title: value(revision ?? {}, "title") || value(detail, "saved_title") || value(detail, "title"),
          search_description: value(revision ?? {}, "seo_description") || value(detail, "summary"),
          core_question: value(revisionSeo, "core_question") || null,
          core_answer: value(revisionSeo, "core_answer") || null,
          category: value(revisionSeo, "category") || value(detail, "category_slug") || null,
          blogger_labels: labels,
          author: revisionSeo.author ?? null,
          official_sources: (revisionSeo.official_sources as Row[] | undefined) ?? ((detail.sources as Row[] | undefined) ?? []).map(source => ({ title: value(source, "source_name"), url: value(source, "url"), official_status: "unverified" })),
          fact_verified_at: revisionSeo.fact_verified_at ?? null,
          editorial_status: value(detail, "editorial_status") || "unknown",
        },
      }),
    }).then(async response => {
      if (!response.ok) throw new Error("게시용 HTML 미리보기를 만들지 못했습니다.");
      return await response.json() as RenderedPreview;
    }).then(result => {
      if (!controller.signal.aborted) {
        setPreviewErrorState(null);
        setRenderedPreviewState({ key: previewKey, result });
      }
    }).catch(reason => {
      if (!controller.signal.aborted) setPreviewErrorState({ key: previewKey, message: reason instanceof Error ? reason.message : "미리보기 변환 실패" });
    });
    return () => controller.abort();
  }, [detail, tab, googleTrendsBased, targetBlogRecordId, previewKey]);

  const pageCount = Math.max(1, Math.ceil((data?.total ?? 0) / pageSize));
  const empty = !loading && !error && (data?.items.length ?? 0) === 0;
  const categories = data?.categories ?? [];
  const languages = data?.languages ?? [];
  const rowStatus = useMemo(() => new Map((data?.items ?? []).map(item => [value(item, "content_version_id"), statusLabel(value(item, "editorial_status"), Boolean(item.machine_passed))])), [data]);

  return <>
    <section className="workspace-panel" aria-label="원고 검색 및 목록">
      <div className="toolbar">
        <label className="search-field">제목 검색<input type="search" value={searchText} onChange={event => { setLoading(true); setError(""); setSearchText(event.target.value); }} placeholder="원고 제목 또는 주제" /></label>
        <label>카테고리<select value={filters.category} onChange={event => { setLoading(true); setError(""); setFilters(current => ({ ...current, category: event.target.value, page: 1 })); }}><option value="">전체</option>{categories.map(item => <option key={item} value={item}>{item === "stocks" ? "주식" : item === "finance" ? "금융" : item}</option>)}</select></label>
        <label>언어<select value={filters.language} onChange={event => { setLoading(true); setError(""); setFilters(current => ({ ...current, language: event.target.value, page: 1 })); }}><option value="">전체</option>{languages.map(item => <option key={item} value={item}>{koreanLanguage(item)}</option>)}</select></label>
        <label>품질 상태<select value={filters.status} onChange={event => { setLoading(true); setError(""); setFilters(current => ({ ...current, status: event.target.value, page: 1 })); }}><option value="">전체</option><option value="quality_held">품질 검토 필요</option><option value="machine_checked">기계 검사 통과</option><option value="failed">처리 실패</option></select></label>
        <label>작성일<select value={filters.sort} onChange={event => { setLoading(true); setError(""); setFilters(current => ({ ...current, sort: event.target.value, page: 1 })); }}><option value="newest">최신순</option><option value="oldest">오래된 순</option></select></label>
        <label>페이지당 표시<select value={pageSize} onChange={event => { setLoading(true); setError(""); setPageSize(Number(event.target.value)); setFilters(current => ({ ...current, page: 1 })); }}><option value={10}>10개</option><option value={25}>25개</option><option value={50}>50개</option></select></label>
      </div>
      <div className="grid-meta"><span>{data ? `${data.total.toLocaleString("ko-KR")}개 원고` : "원고 불러오는 중"}</span>{loading && <span aria-live="polite">목록 갱신 중…</span>}</div>
      {error && <p className="error-state" role="alert">{error}</p>}
      {empty && <div className="empty-state"><strong>표시할 원고가 없습니다.</strong><span>검색어나 필터를 바꾸거나 새로고침해 주세요.</span></div>}
      {data && data.items.length > 0 && <div className="data-grid-scroll"><table className="data-grid"><thead><tr><th>원고 제목</th><th>카테고리</th><th>언어</th><th>AI 모델</th><th>작성일</th><th>검토 상태</th><th>게시 상태</th></tr></thead>
        <tbody>{data.items.map(row => <tr key={value(row, "content_version_id")} tabIndex={0} onClick={event => void openDetail(row, event.currentTarget)} onKeyDown={(event: KeyboardEvent<HTMLTableRowElement>) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); void openDetail(row, event.currentTarget); } }} aria-label={`${value(row, "title")} 상세 보기`}>
          <td className="title-cell" title={value(row, "title")}>{value(row, "title") || value(row, "topic")}</td><td>{value(row, "category_slug") === "stocks" ? "주식" : value(row, "category_slug") === "finance" ? "금융" : value(row, "category_slug")}</td><td>{koreanLanguage(value(row, "language_code"))}</td><td>{value(row, "model") || "—"}</td><td>{dateLabel(value(row, "created_at"))}</td><td><span className="status-text">{rowStatus.get(value(row, "content_version_id"))}</span></td><td>{value(row, "publication_status") === "published" ? "게시됨" : value(row, "publication_status") === "mock" ? "모의 완료" : "미게시"}</td>
        </tr>)}</tbody></table></div>}
      <nav className="pagination" aria-label="원고 페이지 이동"><button disabled={filters.page <= 1 || loading} onClick={() => { setLoading(true); setFilters(current => ({ ...current, page: current.page - 1 })); }}>이전</button><span>{filters.page} / {pageCount} 페이지</span><button disabled={filters.page >= pageCount || loading} onClick={() => { setLoading(true); setFilters(current => ({ ...current, page: current.page + 1 })); }}>다음</button></nav>
    </section>

    {selected && <div className="sheet-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) closeDetail(); }}>
      <section className="detail-sheet" role="dialog" aria-modal="true" aria-labelledby="detail-title" tabIndex={-1} ref={dialog}>
        <header className="sheet-header"><div><p className="eyebrow">원고 상세</p><h2 id="detail-title">{value(selected, "title") || value(selected, "topic")}</h2><p>{value(selected, "category_slug") === "stocks" ? "주식" : "금융"} · {koreanLanguage(value(selected, "language_code"))} · {value(selected, "model") || "모델 정보 없음"}</p></div><button className="icon-button" type="button" onClick={closeDetail} aria-label="상세 패널 닫기">닫기 <span aria-hidden="true">×</span></button></header>
        {detailLoading ? <p className="sheet-loading" role="status">원고와 근거를 불러오는 중…</p> : detail ? <>
          <div className="detail-summary"><span>{statusLabel(value(detail, "editorial_status"), machinePassed)}</span><span>작성 {dateLabel(value(detail, "created_at"))}</span><span>발행 준비 안 됨</span></div>
          <nav className="detail-tabs" aria-label="원고 상세 탭" role="tablist">{[["body", "본문"], ["sources", "출처·근거"], ["quality", "품질 검사"], ["history", "변경 이력"]].map(([id, label]) => <button key={id} id={`manuscript-tab-${id}`} type="button" role="tab" aria-controls="manuscript-panel" aria-selected={tab === id} tabIndex={tab === id ? 0 : -1} onClick={() => setTab(id)}>{label}</button>)}</nav>
          <div className="sheet-content" id="manuscript-panel" role="tabpanel" aria-labelledby={`manuscript-tab-${tab}`} tabIndex={0}>
            {tab === "body" && <div className="body-tab"><p className="article-summary"><strong>검색 설명 (게시 본문 HTML에는 포함되지 않음)</strong><br />{value(latestRevision ?? {}, "seo_description") || value(detail, "summary")}</p>
              <section className={styles.publicationPreview} aria-label="게시용 미리보기"><div className={styles.toolbar}><div><h3>게시용 미리보기</h3><p>제목은 Blogger 제목 영역에 표시되며 게시 본문 HTML에는 중복하지 않습니다.</p></div><label className={styles.trendLabelToggle}><input type="checkbox" checked={googleTrendsBased} onChange={event => setGoogleTrendsBased(event.target.checked)} /> Google Trends 기반 원고</label></div>
                <label className={styles.targetSelector}>대상 블로그 (등록 정보만 조회)
                  <select value={targetBlogRecordId} onChange={event => setTargetBlogRecordId(event.target.value)}>
                    <option value="">선택 안 함</option>
                    {bloggerTargets.map(target => <option key={value(target, "id")} value={value(target, "id")} disabled={!target.active}>{value(target, "display_name")} · {value(target, "url")}{target.blog_id ? ` · Blog ID ${value(target, "blog_id")}` : " · ID 미검증"}</option>)}
                  </select>
                </label>
                <div className={styles.controls} role="group" aria-label="미리보기 보기 선택"><button type="button" aria-pressed={previewMode === "rendered"} onClick={() => setPreviewMode("rendered")}>화면 미리보기</button><button type="button" aria-pressed={previewMode === "source"} onClick={() => setPreviewMode("source")}>게시용 HTML</button><button type="button" aria-pressed={previewMode === "seo"} onClick={() => setPreviewMode("seo")}>SEO 점검</button><button type="button" aria-pressed={previewMode === "package"} onClick={() => setPreviewMode("package")}>발행 준비 자료</button></div>
                {previewLoading && <p role="status">게시용 HTML을 준비하고 있습니다…</p>}{previewError && <p className="quality-held" role="alert">{previewError}</p>}
                {renderedPreview && <><div className={styles.labels}><strong>게시 라벨</strong>{renderedPreview.labels.length ? renderedPreview.labels.map(label => <span key={label}>{label}</span>) : <small>지정된 라벨 없음</small>}</div>
                  {previewMode === "rendered" ? <HtmlPreview html={renderedPreview.post_html} lang={renderedPreview.language_code} title={renderedPreview.title} /> : previewMode === "source" ? <pre className={styles.htmlSource}>{renderedPreview.post_html}</pre> : previewMode === "seo" ? <SeoReadiness result={renderedPreview} /> : renderedPreview.publication_package ? <PublicationPackageView result={renderedPreview} /> : <p role="status">현재 API 응답에 게시 준비 자료가 없습니다. Dashboard와 API 버전을 함께 확인하세요.</p>}
                  <p className={styles.limitation}>미리보기는 저장소의 공통 칼럼 CSS를 적용한 근사 화면입니다. Blogger 테마의 전역 CSS, 위젯, 글꼴과 폭은 실제 게시 화면과 다를 수 있습니다.</p></>}
                <details className={styles.metadata}><summary>원고와 출처 보기</summary><h4>원고 원문</h4><pre>{body}</pre><h4>연결된 출처</h4>{((detail.sources as Row[] | undefined) ?? []).length ? <ul>{(detail.sources as Row[]).map(source => <li key={value(source, "id")}><a href={value(source, "url")} target="_blank" rel="noreferrer">{value(source, "source_name") || value(source, "url")}</a></li>)}</ul> : <p>연결된 출처가 없습니다.</p>}</details>
              </section>
              {detail.review_actions_allowed ? <details className="edit-article"><summary>새 원고 버전 편집</summary><form onSubmit={event => void submitRevision(event)}>
                <label>작성자<input name="reviewer" required minLength={2} maxLength={80} /></label><label>변경 사유<input name="reason" required minLength={10} maxLength={2000} /></label><label>제목<input name="title" required maxLength={500} defaultValue={value(latestRevision ?? {}, "title") || value(detail, "title")} /></label><label>요약 및 SEO 설명<textarea name="summary" required minLength={1} maxLength={500} defaultValue={value(latestRevision ?? {}, "seo_description") || value(detail, "summary")} /></label><label>검색 키워드 (| 구분)<input name="keywords" required defaultValue={((detail.keywords as string[] | undefined) ?? []).join(" | ")} /></label><label>SEO 제목 후보 (| 구분)<input name="seo_title_candidates" maxLength={1000} defaultValue={((latestSeo.seo_title_candidates as string[] | undefined) ?? []).join(" | ")} /></label><label>핵심 검색어<input name="primary_keyword" maxLength={80} defaultValue={value(latestSeo, "primary_keyword") || ((detail.keywords as string[] | undefined) ?? [])[0] || ""} /></label><label>대상 지역<input name="target_region" maxLength={80} placeholder="근거가 있을 때만 입력" defaultValue={value(latestSeo, "target_region")} /></label><label>검색 의도<select name="search_intent" defaultValue={value(latestSeo, "search_intent")}><option value="">미기록</option><option value="informational">정보 탐색</option><option value="navigational">특정 사이트 탐색</option><option value="transactional">거래·행동</option><option value="commercial">상업 정보 비교</option></select></label><label>핵심 질문<input name="core_question" maxLength={500} defaultValue={value(latestSeo, "core_question")} /></label><label>핵심 답변<textarea name="core_answer" maxLength={2000} defaultValue={value(latestSeo, "core_answer")} /></label><label>Blogger 라벨 (, 구분)<input name="labels" defaultValue={((latestRevision?.blogger_labels as string[] | undefined) ?? []).join(", ")} /></label><label>원고 HTML<textarea name="html_body" rows={14} required maxLength={100000} defaultValue={value(latestRevision ?? {}, "html_body") || htmlBody} /></label><p>저장 시 서버 허용 목록으로 HTML을 정화하고 새 버전에서 품질 검사를 다시 실행합니다.</p><button disabled={saving}>새 버전 저장</button></form></details> : <p className="notice">이 원고는 읽기 전용입니다. 현재 편집·검토 권한 정책에서 이 원고의 버전은 승인 대상에 포함되지 않습니다.</p>}
            </div>}
            {tab === "body" && <section className="detail-section localized-expansion" aria-labelledby="localized-expansion-title">
              <h3 id="localized-expansion-title">다른 언어로 발행</h3>
              <p>원본 자료의 지역과 언어를 기준으로 후보를 안내합니다. 번역이 아닌 현지 독자용 칼럼을 준비하도록 요청하며, 생성 Provider가 없으면 작업은 대기 상태로 남습니다.</p>
              {!localizedPlan && <button type="button" disabled={localizedPlanLoading} onClick={() => void loadLocalizedPlan()}>{localizedPlanLoading ? "대상 확인 중…" : "언어와 Blogger 블로그 선택"}</button>}
              {localizedPlan && <>
                <p>원본 지역: {value(localizedPlan.source, "target_country") || "미확인"} · 원문 언어: {koreanLanguage(value(localizedPlan.source, "source_language"))} · 사실 자료 {value(localizedPlan.source, "source_count")}건 · 근거 사실 {value(localizedPlan.source, "fact_count")}건</p>
                {localizedPlan.source.evaluation_only && <p className="quality-held" role="status">평가 전용 원고입니다. 이 자료에서는 새 원고 생성과 발행 요청을 진행할 수 없습니다.</p>}
                {!localizedPlan.generation_provider_available && <p className="notice">원고 생성 Provider가 연결되지 않았습니다. 요청은 생성되지 않으며 대기 또는 차단 상태로만 기록됩니다.</p>}
                <form onSubmit={event => void submitLocalizedRequests(event)}>
                  <label>요청자 이름<input name="requester" minLength={2} maxLength={80} required value={localizedRequester} onChange={event => setLocalizedRequester(event.target.value)} /></label>
                  <fieldset><legend>추가 언어와 대상 블로그</legend>
                    {localizedPlan.targets.map(target => {
                      const key = `${target.language_code}:${target.blog_id}`;
                      const unavailable = Boolean(localizedPlan.source.evaluation_only) || target.already_published || Boolean(target.existing_localization);
                      const reason = target.already_published ? "이미 게시됨" : target.existing_localization ? `기존 현지화 원고 v${value(target.existing_localization, "version")}가 있음` : localizedPlan.source.evaluation_only ? "평가 전용 원고" : "";
                      return <label key={key} className="localized-target-option"><input type="checkbox" disabled={unavailable} checked={Boolean(localizedSelection[key])} onChange={event => setLocalizedSelection(current => ({ ...current, [key]: event.target.checked }))} />
                        <span><strong>{koreanLanguage(target.language_code)} · {value(target, "blog_name")}</strong><small>{value(target, "blog_url")} · Blog ID {value(target, "blogger_blog_id") || "미확인"} · 게시 모드 {value(target, "publication_mode") === "auto" ? "Auto 설정(실행 차단)" : "Manual"}</small>
                          {target.recommended && <small>{recommendationLabel(value(target, "recommendation_reason"))}</small>}{reason && <small className="quality-held">{reason}</small>}
                          {target.published_posts.map((post, index) => <small key={`${value(post, "remote_post_id")}-${index}`}>기존 Blogger 글 · Post ID {value(post, "remote_post_id")} · 블로그 URL {value(post, "url")}</small>)}</span></label>;
                    })}
                  </fieldset>
                  {localizedPlan.languages_without_active_blog.length > 0 && <p className="notice">활성 Blogger 연결이 없어 선택할 수 없는 언어: {localizedPlan.languages_without_active_blog.map(language => koreanLanguage(value(language, "language_code"))).join(", ")}</p>}
                  {["TW", "HK", "SG"].includes(value(localizedPlan.source, "target_country").toUpperCase()) && <p className="notice">대만·홍콩·싱가포르 자료는 지역 코드만으로 중국어 간체 대상이라고 판단하지 않습니다. 원고별 독자 관련성과 언어를 사람이 선택해야 합니다.</p>}
                  <label>선택한 언어 독자에게 제공할 가치와 대상 이유<textarea value={localizedSelectionReason} onChange={event => setLocalizedSelectionReason(event.target.value)} minLength={10} maxLength={1000} required placeholder="사건의 영향 지역, 대상 독자의 배경, 검색 의도와 선택 이유를 적으세요." /></label>
                  <label className="localized-consent"><input type="checkbox" checked={oneTimeAutoPublishRequested} onChange={event => setOneTimeAutoPublishRequested(event.target.checked)} /> 이 선택 작업에 한해 원고 생성 후 자동 게시 의사를 명시합니다. 현재 게시 잠금과 전체 Manual/Auto 설정은 변경되지 않습니다.</label>
                  <p>처리 순서: 기존 자료·출처 확인 → 현지화 원고 작성 → 사실·언어·중복·SEO 검사 → HTML 검증 → Manual 검토 또는 사전 Auto 조건 확인. 모든 단계가 통과해도 실제 Blogger 쓰기는 별도 운영 잠금이 해제되기 전까지 차단됩니다.</p>
                  <button type="submit" disabled={saving || localizedSelectionReason.trim().length < 10 || !Object.values(localizedSelection).some(Boolean)}>선택한 언어 작업 요청</button>
                </form>
                {localizedPlan.requests.length > 0 && <div><h4>이 원고의 다국어 요청 이력</h4><ul>{localizedPlan.requests.map(item => { const state = value(item, "latest_state") || value(item, "initial_state"); return <li key={value(item, "id")}>{value(item, "target_language_code")} · {state} · {dateLabel(value(item, "created_at"))} {!["cancelled", "published"].includes(state) && <button type="button" disabled={saving} onClick={() => void cancelLocalizedRequest(value(item, "id"))}>요청 취소</button>}</li>; })}</ul></div>}
              </>}
            </section>}
            {tab === "sources" && <div className="detail-section">{((detail.sources as Row[] | undefined) ?? []).length === 0 ? <p className="empty-state">연결된 출처가 없습니다.</p> : (detail.sources as Row[]).map(source => <article className="source-card" key={value(source, "id")}><h3>{value(source, "source_name")}</h3><p>게시 {dateLabel(value(source, "published_at"))} · 수집 {dateLabel(value(source, "collected_at"))} · 권리 {value(source, "rights") || "확인 필요"}</p><a href={value(source, "url")} target="_blank" rel="noreferrer">원문 열기 ↗</a></article>)}<h3>검증된 사실</h3>{((detail.facts as Row[] | undefined) ?? []).map(fact => <article className="source-card" key={value(fact, "id")}><strong>{value(fact, "fact_key")}</strong><p>{value(fact, "source_excerpt")}</p><small>검증 상태: {value(fact, "verification_status")}</small></article>)}</div>}
            {tab === "quality" && <div className="detail-section"><p className={machinePassed ? "quality-ok" : "quality-held"}>{machinePassed ? "기계 검사 통과 · 의미 정확성과 자연스러움은 사람 검토가 필요합니다." : "품질 검토가 필요합니다. 이 상태에서는 발행할 수 없습니다."}</p><QualityChecks value={detail.checks} />
              <details><summary>기계 검사 원본 데이터</summary><pre>{JSON.stringify(detail.checks ?? {}, null, 2)}</pre></details>
              {detail.review_actions_allowed ? <>
              <form onSubmit={event => { event.preventDefault(); const form = new FormData(event.currentTarget); void submit("article-review-events", { evaluation_id: value(detail, "id"), content_version_id: value(detail, "content_version_id"), idempotency_key: crypto.randomUUID(), reviewer_name: String(form.get("reviewer") ?? "") }); }}><h3>편집 검토 시작</h3><label>검토자<input name="reviewer" required minLength={2} maxLength={80} /></label><button disabled={saving}>검토 시작 기록</button></form>
              <form onSubmit={event => { event.preventDefault(); const form = new FormData(event.currentTarget); const disposition = String(form.get("disposition")); void submit("article-reviews", { evaluation_id: value(detail, "id"), content_version_id: value(detail, "content_version_id"), editorial_version_id: value(latestRevision ?? {}, "id") || null, idempotency_key: crypto.randomUUID(), reviewer_name: String(form.get("reviewer") ?? ""), factual_accuracy: String(form.get("facts")), translation_naturalness: String(form.get("naturalness")), reader_value: String(form.get("reader_value")), disposition, comments: String(form.get("comments")), requested_changes: String(form.get("requested_changes")) }); }}><h3>사람 검토 결과</h3><label>검토자<input name="reviewer" required minLength={2} maxLength={80} /></label><label>사실 정확성<select name="facts"><option value="not_assessed">미평가</option><option value="verified">확인</option><option value="issue_found">문제 발견</option><option value="uncertain">불확실</option></select></label><label>번역 자연스러움<select name="naturalness"><option value="not_assessed">미평가</option><option value="acceptable">수용 가능</option><option value="issue_found">문제 발견</option><option value="uncertain">불확실</option></select></label><label>독자 가치<select name="reader_value"><option value="not_assessed">미평가</option><option value="useful">유용</option><option value="insufficient">부족</option><option value="uncertain">불확실</option></select></label><label>검토 결과<select name="disposition"><option value="reviewed">검토 기록</option><option value="revision_requested">수정 요청</option><option value="rejected">반려</option><option value="approved">편집 검토 통과</option></select></label><label>의견<textarea name="comments" required minLength={10} maxLength={2000} /></label><label>수정 요청<textarea name="requested_changes" maxLength={2000} /></label><button disabled={saving}>검토 결과 저장</button></form>
              <section className="approval-box"><h3>발행 승인 기록</h3><p>사람 편집 검토와 기계 품질 검사를 통과한 정확한 버전에만 기록됩니다. 승인 기록은 실제 Blogger 게시를 실행하지 않습니다.</p><form onSubmit={event => { event.preventDefault(); const form = new FormData(event.currentTarget); void submit("publication-approvals", { evaluation_id: value(detail, "id"), content_version_id: value(detail, "content_version_id"), editorial_version_id: value(latestRevision ?? {}, "id") || null, event_key: crypto.randomUUID(), actor: String(form.get("actor")), reason: String(form.get("reason")), action: "approved", supersedes_event_id: null }); }}><label>승인자<input name="actor" required minLength={2} maxLength={80} /></label><label>승인 사유<input name="reason" required minLength={10} maxLength={2000} /></label><button disabled={saving || !machinePassed || value(latestReview ?? {}, "disposition") !== "approved" || publicationApproved}>승인 기록</button></form>
                {publicationApproved && <form onSubmit={event => { event.preventDefault(); const form = new FormData(event.currentTarget); void submit("publication-approvals", { evaluation_id: value(detail, "id"), content_version_id: value(detail, "content_version_id"), editorial_version_id: value(latestRevision ?? {}, "id") || null, event_key: crypto.randomUUID(), actor: String(form.get("actor")), reason: String(form.get("reason")), action: "revoked", supersedes_event_id: value(latestApproval ?? {}, "id") }); }}><label>취소자<input name="actor" required minLength={2} maxLength={80} /></label><label>취소 사유<input name="reason" required minLength={10} maxLength={2000} /></label><button disabled={saving}>승인 취소</button></form>}</section>
              </> : <p className="notice">이 원고의 편집 검토 및 발행 승인 작업은 현재 권한 정책상 허용되지 않습니다. 기록 조회만 가능합니다.</p>}
            </div>}
            {tab === "history" && <div className="detail-section"><h3>원고 버전</h3>{revisions.length ? revisions.map(revision => <article className="history-card" key={value(revision, "id")}><h4>{value(revision, "title")} · v{value(revision, "revision_number")}</h4><p>{dateLabel(value(revision, "created_at"))} · 작성 {value(revision, "reviewer_name")} · {value(revision, "quality_status")}</p><details><summary>변경 이유와 본문 확인</summary><p>{value(revision, "reason")}</p><pre>{value(revision, "body") || value(revision, "html_body")}</pre></details></article>) : <p>수정 버전이 없습니다.</p>}<h3>검토 및 승인 이력</h3>{reviews.map(review => <article className="history-card" key={value(review, "id")}><strong>{value(review, "reviewer_name")} · {value(review, "disposition")}</strong><p>{dateLabel(value(review, "created_at"))} · 사실 {value(review, "factual_accuracy")} · 번역 {value(review, "translation_naturalness")} · 독자 가치 {value(review, "reader_value")}</p><p>{value(review, "comments")} {value(review, "requested_changes")}</p></article>)}{approvals.map(event => <article className="history-card" key={value(event, "id")}>발행 승인 {value(event, "action")} · {value(event, "actor")} · {dateLabel(value(event, "created_at"))}</article>)}</div>}
          </div>
          {message && <p role="status" className="sheet-message">{message}</p>}
        </> : <p className="error-state" role="alert">{message || "상세 정보를 표시할 수 없습니다."}</p>}
      </section>
    </div>}
  </>;
}

function SeoReadiness({ result }: { result: RenderedPreview }) {
  const metadata = result.seo_metadata;
  const stateLabel = (status: SeoCheck["status"]) => status === "ready" ? "준비됨" : status === "review" ? "검토 필요" : "미측정";
  return <section className={styles.seoPanel} aria-label="게시 전 SEO 점검">
    <h4>게시 전 SEO 점검</h4>
    <p>검색 순위나 방문자 수를 예측하지 않습니다. 이 결과는 작성자가 확인할 구체적인 항목이며 게시 승인과 별개입니다.</p>
    <dl><dt>언어 / 지역</dt><dd>{koreanLanguage(value(metadata, "language_code") || result.language_code)} / {value(metadata, "target_region") || "지역 미지정"}</dd>
      <dt>검색 의도</dt><dd>{value(metadata, "search_intent") || "미기록"}</dd><dt>제목</dt><dd>{value(metadata, "seo_title") || result.title}{Array.isArray(metadata.seo_title_candidates) && metadata.seo_title_candidates.length ? ` · 후보: ${(metadata.seo_title_candidates as string[]).join(" / ")}` : ""}</dd>
      <dt>검색 설명</dt><dd>{value(metadata, "search_description") || "미입력"}</dd><dt>핵심 표현</dt><dd>{value(metadata, "primary_keyword") || "미지정"}</dd>
      <dt>핵심 질문 / 답</dt><dd>{value(metadata, "core_question") || "미기록"}{value(metadata, "core_answer") ? ` — ${value(metadata, "core_answer")}` : ""}</dd>
      <dt>카테고리 / 라벨</dt><dd>{value(metadata, "category") || "미지정"} / {result.labels.join(", ") || "없음"}</dd>
      <dt>출처</dt><dd>{Array.isArray(metadata.official_sources) ? metadata.official_sources.length : 0}건 · 공식성 확인 필요</dd>
      <dt>사실 확인 시각</dt><dd>{metadata.fact_verified_at ? dateLabel(String(metadata.fact_verified_at)) : "미기록"}</dd>
      <dt>작성자 / 검토 상태</dt><dd>{value(metadata, "author") || "작성자 연결 미확인"} / {value(metadata, "editorial_status") || "미확인"}</dd></dl>
    <ul className={styles.seoChecks}>{result.seo_checks.map(check => <li key={check.key} data-status={check.status}><span>{stateLabel(check.status)}</span><p>{check.message}</p></li>)}</ul>
    <p className={styles.gscNote}>Search Console 연결 없음 · 노출수, 클릭수, CTR, 평균 순위, 실제 검색어 및 색인 상태는 미측정입니다.</p>
    <small>렌더러 {result.renderer_version} · 디자인 {result.design_system_version}</small>
  </section>;
}

function PublicationPackageView({ result }: { result: RenderedPreview }) {
  const pkg = result.publication_package ?? {};
  const json = JSON.stringify(pkg, null, 2);
  const blockers = Array.isArray(pkg.blockers) ? pkg.blockers as string[] : [];
  const seo = (pkg.seo && typeof pkg.seo === "object" ? pkg.seo : {}) as Row;
  const sources = Array.isArray(pkg.sources) ? pkg.sources as Row[] : [];
  const titleCandidates = Array.isArray(seo.title_candidates) ? seo.title_candidates as string[] : [];
  const saveJson = () => {
    const url = URL.createObjectURL(new Blob([json], { type: "application/json;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `woori-publication-preparation-${String(pkg.package_sha256 ?? "").slice(0, 12)}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  };
  return <section className={styles.packageView} aria-label="Blogger 발행 준비 자료">
    <h4>발행 준비 자료 · 미전송</h4>
    <p>이 파일은 비공개 준비 결과입니다. Blogger API 요청, 승인, 저장, 예약 또는 게시를 실행하지 않습니다.</p>
    <dl><dt>대상 블로그</dt><dd>{value((pkg.target_blog as Row | null) ?? {}, "url") || "미선택 또는 등록 정보 없음"}{value((pkg.target_blog as Row | null) ?? {}, "blog_id") ? ` · Blog ID ${value((pkg.target_blog as Row | null) ?? {}, "blog_id")}` : ""}</dd>
      <dt>언어 / 라벨</dt><dd>{result.language_code} · {result.labels.join(", ") || "라벨 없음"}</dd>
      <dt>렌더러 / 디자인</dt><dd>{result.renderer_version} / {result.design_system_version}</dd>
      <dt>자료 생성 / 지문</dt><dd>{dateLabel(value(pkg, "generated_at"))} · {value(pkg, "package_sha256")}</dd>
      <dt>승인 상태</dt><dd>별도 검토 대상 · publish_ready=false</dd>
      <dt>미완료 항목</dt><dd>{blockers.length ? blockers.map(item => ({
        target_blog_not_selected_or_registered: "대상 Blogger를 선택하고 등록 정보를 확인해야 합니다.",
        target_blog_inactive: "대상 블로그가 비활성 상태입니다.",
        target_blog_language_mismatch: "원고 언어와 대상 블로그 언어가 다릅니다.",
        target_blog_mapping_not_verified: "등록 Blog ID 매핑 확인이 필요합니다.",
        live_blogger_access_not_rechecked: "현재 Blogger 접근 권한은 실조회하지 않았습니다.",
        content_version_identity_missing: "원고 버전 식별자가 없습니다.",
      } as Record<string, string>)[item] ?? item).join(" · ") : "등록 매핑 조회됨. 별도 운영 승인과 전송 구현이 필요합니다."}</dd>
      <dt>SEO 제목</dt><dd>{value(seo, "title") || "미입력"}{titleCandidates.length > 0 && <ul>{titleCandidates.map(candidate => <li key={candidate}>{candidate}</li>)}</ul>}</dd>
      <dt>검색 설명</dt><dd>{value(seo, "search_description") || "미입력"} · API 전송 대상이 아니며 Blogger 관리자에서 수동 확인</dd>
      <dt>실제 테마</dt><dd>{value((pkg.theme_compatibility as Row) ?? {}, "status") === "live_theme_not_inspected" ? "미조회 · 테마별 확인 필요" : "확인 상태 미기록"}</dd>
      <dt>출처</dt><dd>{sources.length ? <ul>{sources.map((source, index) => <li key={`${value(source, "url")}-${index}`}><a href={value(source, "url")} target="_blank" rel="noreferrer">{value(source, "title") || value(source, "url")}</a> · 검증 상태: 미확인</li>)}</ul> : "출처 정보 없음"}</dd></dl>
    <button type="button" onClick={saveJson}>준비 자료 JSON 저장</button>
    <details><summary>전체 패키지 JSON 보기</summary><pre className={styles.htmlSource}>{json}</pre></details>
  </section>;
}

function QualityChecks({ value }: { value: unknown }) {
  const object = (value && typeof value === "object" ? value : {}) as Row;
  const checks = object.checks && typeof object.checks === "object" ? object.checks as Row : object;
  const entries = Object.entries(checks).filter(([, result]) => typeof result === "boolean");
  return entries.length ? <ul className="check-list">{entries.map(([name, passed]) => <li key={name}><span>{name.replaceAll("_", " ")}</span><strong>{passed ? "확인" : "보류"}</strong></li>)}</ul> : <p>세부 기계 검사 결과가 없습니다.</p>;
}
