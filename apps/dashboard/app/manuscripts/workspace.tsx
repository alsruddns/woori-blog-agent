"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import styles from "./article-preview.module.css";

type Row = Record<string, unknown>;
type ListResult = { items: Row[]; page: number; page_size: number; total: number; languages: string[]; categories: string[] };
const value = (row: Row | null | undefined, key: string) => String(row?.[key] ?? "");
const koreanLanguage = (code: string) => ({ ko: "한국어", en: "영어", "zh-CN": "중국어 간체", ja: "일본어" } as Record<string, string>)[code] ?? code;
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

type RenderedPreview = { title: string; language_code: string; post_html: string; labels: string[]; title_in_body: boolean; publication_performed: boolean };

function HtmlPreview({ html, title, lang }: { html: string; title: string; lang: string }) {
  const previewCss = `:root{color-scheme:light dark}*{box-sizing:border-box}body{margin:0;background:#fff;color:#26342e;font:400 17px/1.82 system-ui,-apple-system,"Segoe UI",sans-serif;overflow-wrap:anywhere;word-break:normal}.wb-preview-shell{max-width:780px;margin:0 auto;padding:28px clamp(16px,4vw,36px) 44px}.wb-post-title{margin:0 0 26px;font-size:clamp(25px,4vw,34px);line-height:1.32;letter-spacing:-.025em}.wb-article p{margin:0 0 1.18em}.wb-article .wb-lead{font-size:1.06em;line-height:1.86}.wb-article h2{margin:2.1em 0 .72em;font-size:1.48em;line-height:1.42;letter-spacing:-.02em}.wb-article h3{margin:1.7em 0 .62em;font-size:1.2em;line-height:1.45}.wb-article a{color:#176b56;text-decoration-thickness:1px;text-underline-offset:3px;overflow-wrap:anywhere}.wb-article blockquote{margin:1.5em 0;padding:.25em 0 .25em 1em;border-left:3px solid #9ab7a8;color:#52645b}.wb-article .wb-summary{margin:0 0 1.7em;padding:16px 18px;border:1px solid #dce9e1;border-left:4px solid #48836a;border-radius:8px;background:#f5f9f6;font-weight:600}.wb-article .wb-table-wrap{max-width:100%;margin:1.4em 0;overflow-x:auto;overscroll-behavior-inline:contain}.wb-article table{width:100%;border-collapse:collapse;font-size:.94em}.wb-article th,.wb-article td{min-width:88px;padding:10px 12px;border:1px solid #dbe3de;text-align:left;vertical-align:top}.wb-article th{background:#f2f6f3;font-weight:700}.wb-article .wb-stat-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,180px),1fr));gap:12px;margin:1.3em 0}.wb-article .wb-stat-card{padding:16px;border:1px solid #dce6df;border-radius:10px;background:#f8faf8}.wb-article figure{max-width:100%;margin:1.4em auto;text-align:center}.wb-article img{display:block;width:auto;height:auto;max-width:100%;margin:auto}.wb-article figcaption{margin-top:.5em;color:#68766e;font-size:.88em}.wb-article ul,.wb-article ol{margin:.6em 0 1.2em;padding-left:1.5em}.wb-article li{margin:.35em 0}.wb-article code{max-width:100%;overflow-wrap:anywhere}.wb-article hr{margin:2em 0;border:0;border-top:1px solid #dbe3de}@media(max-width:480px){body{font-size:16px}.wb-preview-shell{padding:20px 16px 32px}.wb-post-title{margin-bottom:20px}.wb-article h2{margin-top:1.8em;font-size:1.36em}.wb-article th,.wb-article td{padding:8px;font-size:.9em}}@media(prefers-color-scheme:dark){body{background:#111a16;color:#e3ebe6}.wb-article .wb-summary,.wb-article th,.wb-article .wb-stat-card{background:#1b2922;border-color:#35473d}.wb-article th,.wb-article td{border-color:#394b41}.wb-article blockquote{color:#b9c9bf}.wb-article figcaption{color:#b1beb6}}`;
  const previewHtml = html.replace(/<img\b([^>]*)>/gi, (_tag, attributes: string) => {
    const alt = attributes.match(/\balt="([^"]*)"/i)?.[1] ?? "이미지";
    return `<div class="wb-image-placeholder" role="img" aria-label="${alt}">${alt}<small>이미지 미리보기에서는 외부 요청을 보내지 않습니다.</small></div>`;
  });
  const source = `<!doctype html><html lang="${escapeHtml(lang)}"><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline';"><meta name="viewport" content="width=device-width,initial-scale=1"><style>${previewCss}.wb-image-placeholder{display:grid;gap:4px;place-items:center;max-width:100%;min-height:110px;padding:16px;border:1px dashed #9cad9f;border-radius:8px;color:#52645b;overflow-wrap:anywhere;text-align:center}.wb-image-placeholder small{font-size:11px}</style></head><body><main class="wb-preview-shell"><h1 class="wb-post-title">${escapeHtml(title)}</h1>${previewHtml}</main></body></html>`;
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
  const [previewMode, setPreviewMode] = useState<"rendered" | "source">("rendered");
  const [renderedPreviewState, setRenderedPreviewState] = useState<{ key: string; result: RenderedPreview } | null>(null);
  const [previewErrorState, setPreviewErrorState] = useState<{ key: string; message: string } | null>(null);
  const dialog = useRef<HTMLElement>(null);
  const previousFocus = useRef<HTMLElement | null>(null);
  const requestSequence = useRef(0);
  const detailSequence = useRef(0);

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
    setSelected(row); setDetail(null); setTab("body"); setMessage(""); setDetailLoading(true); setPreviewMode("rendered"); setRenderedPreviewState(null); setGoogleTrendsBased(false);
    document.body.classList.add("sheet-open");
    try {
      const response = await fetch(`/api/research/manuscripts/${encodeURIComponent(value(row, "evaluation_id"))}/${encodeURIComponent(value(row, "content_version_id"))}`, { cache: "no-store" });
      if (!response.ok) throw new Error("원고 상세 정보를 불러오지 못했습니다.");
      const result = await response.json() as Row;
      if (detailSequence.current === requestId) {
        setDetail(result);
        const localeLabel = ({ ko: "이슈", en: "Issues", ja: "話題", "zh-CN": "热点" } as Record<string, string>)[value(result, "language_code")];
        const existingLabels = ((result.editorial_versions as Row[] | undefined)?.[0]?.blogger_labels as string[] | undefined) ?? [];
        setGoogleTrendsBased(Boolean(result.google_trends_based) || Boolean(localeLabel && existingLabels.includes(localeLabel)));
      }
      requestAnimationFrame(() => { if (detailSequence.current === requestId) dialog.current?.focus(); });
    } catch { setMessage("선택한 원고 상세 정보를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요."); }
    finally { setDetailLoading(false); }
  }, []);
  const closeDetail = useCallback(() => {
    detailSequence.current += 1;
    setSelected(null); setDetail(null); document.body.classList.remove("sheet-open");
    requestAnimationFrame(() => previousFocus.current?.focus());
  }, []);
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
      target_blog_id: null, publication_mode: "manual", planned_publish_at: null,
    });
  };

  const reviews = (detail?.review_history as Row[] | undefined) ?? [];
  const revisions = (detail?.editorial_versions as Row[] | undefined) ?? [];
  const approvals = (detail?.publication_approval_events as Row[] | undefined) ?? [];
  const latestRevision = revisions[0];
  const machinePassed = Boolean(latestRevision ? latestRevision.machine_passed : detail?.machine_passed);
  const latestReview = reviews[0];
  const body = value(detail, "saved_body") || value(detail, "body");
  const htmlBody = value(latestRevision ?? {}, "html_body") || (value(detail, "body_format") === "html" ? value(detail, "safe_body_html") : markdownHtml(body));
  const latestApproval = approvals[0];
  const publicationApproved = value(latestApproval ?? {}, "action") === "approved";
  const previewKey = JSON.stringify([
    value(selected, "content_version_id"), value(latestRevision ?? {}, "id"), googleTrendsBased,
  ]);
  const renderedPreview = renderedPreviewState?.key === previewKey ? renderedPreviewState.result : null;
  const previewError = previewErrorState?.key === previewKey ? previewErrorState.message : "";
  const previewLoading = Boolean(detail && tab === "body" && !renderedPreview && !previewError);

  useEffect(() => {
    if (!detail || tab !== "body") return;
    const controller = new AbortController();
    const revision = ((detail.editorial_versions as Row[] | undefined) ?? [])[0];
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
  }, [detail, tab, googleTrendsBased, previewKey]);

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
                <div className={styles.controls} role="group" aria-label="미리보기 보기 선택"><button type="button" aria-pressed={previewMode === "rendered"} onClick={() => setPreviewMode("rendered")}>화면 미리보기</button><button type="button" aria-pressed={previewMode === "source"} onClick={() => setPreviewMode("source")}>게시용 HTML</button></div>
                {previewLoading && <p role="status">게시용 HTML을 준비하고 있습니다…</p>}{previewError && <p className="quality-held" role="alert">{previewError}</p>}
                {renderedPreview && <><div className={styles.labels}><strong>게시 라벨</strong>{renderedPreview.labels.length ? renderedPreview.labels.map(label => <span key={label}>{label}</span>) : <small>지정된 라벨 없음</small>}</div>
                  {previewMode === "rendered" ? <HtmlPreview html={renderedPreview.post_html} lang={renderedPreview.language_code} title={renderedPreview.title} /> : <pre className={styles.htmlSource}>{renderedPreview.post_html}</pre>}
                  <p className={styles.limitation}>미리보기는 저장소의 공통 칼럼 CSS를 적용한 근사 화면입니다. Blogger 테마의 전역 CSS, 위젯, 글꼴과 폭은 실제 게시 화면과 다를 수 있습니다.</p></>}
                <details className={styles.metadata}><summary>원고와 출처 보기</summary><h4>원고 원문</h4><pre>{body}</pre><h4>연결된 출처</h4>{((detail.sources as Row[] | undefined) ?? []).length ? <ul>{(detail.sources as Row[]).map(source => <li key={value(source, "id")}><a href={value(source, "url")} target="_blank" rel="noreferrer">{value(source, "source_name") || value(source, "url")}</a></li>)}</ul> : <p>연결된 출처가 없습니다.</p>}</details>
              </section>
              {detail.review_actions_allowed ? <details className="edit-article"><summary>새 원고 버전 편집</summary><form onSubmit={event => void submitRevision(event)}>
                <label>작성자<input name="reviewer" required minLength={2} maxLength={80} /></label><label>변경 사유<input name="reason" required minLength={10} maxLength={2000} /></label><label>제목<input name="title" required maxLength={500} defaultValue={value(latestRevision ?? {}, "title") || value(detail, "title")} /></label><label>요약 및 SEO 설명<textarea name="summary" required minLength={1} maxLength={500} defaultValue={value(latestRevision ?? {}, "seo_description") || value(detail, "summary")} /></label><label>검색 키워드 (| 구분)<input name="keywords" required defaultValue={((detail.keywords as string[] | undefined) ?? []).join(" | ")} /></label><label>Blogger 라벨 (, 구분)<input name="labels" defaultValue={((latestRevision?.blogger_labels as string[] | undefined) ?? []).join(", ")} /></label><label>원고 HTML<textarea name="html_body" rows={14} required maxLength={100000} defaultValue={value(latestRevision ?? {}, "html_body") || htmlBody} /></label><p>저장 시 서버 허용 목록으로 HTML을 정화하고 새 버전에서 품질 검사를 다시 실행합니다.</p><button disabled={saving}>새 버전 저장</button></form></details> : <p className="notice">이 원고는 읽기 전용입니다. 현재 편집·검토 권한 정책에서 이 원고의 버전은 승인 대상에 포함되지 않습니다.</p>}
            </div>}
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

function QualityChecks({ value }: { value: unknown }) {
  const object = (value && typeof value === "object" ? value : {}) as Row;
  const checks = object.checks && typeof object.checks === "object" ? object.checks as Row : object;
  const entries = Object.entries(checks).filter(([, result]) => typeof result === "boolean");
  return entries.length ? <ul className="check-list">{entries.map(([name, passed]) => <li key={name}><span>{name.replaceAll("_", " ")}</span><strong>{passed ? "확인" : "보류"}</strong></li>)}</ul> : <p>세부 기계 검사 결과가 없습니다.</p>;
}
