"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

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

function HtmlPreview({ html, lang }: { html: string; lang: string }) {
  const source = `<!doctype html><html lang="${escapeHtml(lang)}"><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data: https:; style-src 'unsafe-inline';"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{font:16px/1.8 system-ui,sans-serif;max-width:760px;margin:20px auto;padding:0 20px;color:#202a31;overflow-wrap:anywhere}h2,h3{line-height:1.4;margin-top:2em}a{color:#176b56}blockquote{border-left:3px solid #9eb5ac;padding-left:1em;color:#53645d}</style></head><body>${html}</body></html>`;
  return <iframe className="article-preview" title="원고 본문 미리보기" sandbox="" srcDoc={source} />;
}

export default function ManuscriptWorkspace() {
  const [filters, setFilters] = useState({ q: "", language: "", category: "", status: "", sort: "newest", page: 1 });
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
  const dialog = useRef<HTMLElement>(null);
  const previousFocus = useRef<HTMLElement | null>(null);
  const requestSequence = useRef(0);
  const detailSequence = useRef(0);

  useEffect(() => { const timer = setTimeout(() => setFilters(current => ({ ...current, q: searchText, page: 1 })), 250); return () => clearTimeout(timer); }, [searchText]);
  useEffect(() => {
    const controller = new AbortController();
    const id = ++requestSequence.current;
    const params = new URLSearchParams({ page: String(filters.page), page_size: "25", sort: filters.sort });
    if (filters.q.trim()) params.set("q", filters.q.trim());
    if (filters.language) params.set("language", filters.language);
    if (filters.category) params.set("category", filters.category);
    if (filters.status) params.set("status", filters.status);
    fetch(`/api/research/manuscripts?${params}`, { cache: "no-store", signal: controller.signal })
      .then(async response => { if (!response.ok) throw new Error("원고 목록을 불러오지 못했습니다."); return await response.json() as ListResult; })
      .then(result => { if (requestSequence.current === id) setData(result); })
      .catch(reason => { if (!controller.signal.aborted && requestSequence.current === id) setError(reason instanceof Error ? reason.message : "조회 오류가 발생했습니다."); })
      .finally(() => { if (requestSequence.current === id) setLoading(false); });
    return () => controller.abort();
  }, [filters]);

  const openDetail = useCallback(async (row: Row, trigger: HTMLElement) => {
    const requestId = ++detailSequence.current;
    previousFocus.current = trigger;
    setSelected(row); setDetail(null); setTab("body"); setMessage(""); setDetailLoading(true);
    document.body.classList.add("sheet-open");
    try {
      const response = await fetch(`/api/research/manuscripts/${encodeURIComponent(value(row, "evaluation_id"))}/${encodeURIComponent(value(row, "content_version_id"))}`, { cache: "no-store" });
      if (!response.ok) throw new Error("원고 상세 정보를 불러오지 못했습니다.");
      const result = await response.json() as Row;
      if (detailSequence.current === requestId) setDetail(result);
      requestAnimationFrame(() => { if (detailSequence.current === requestId) dialog.current?.focus(); });
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : "상세 조회 오류"); }
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
    await submit("article-revisions", {
      evaluation_id: value(detail, "id"), content_version_id: value(detail, "content_version_id"),
      base_editorial_version_id: value((detail.editorial_versions as Row[] | undefined)?.[0], "id") || null,
      idempotency_key: crypto.randomUUID(), reviewer_name: String(form.get("reviewer") ?? ""), reason: String(form.get("reason") ?? ""),
      title: String(form.get("title") ?? ""), body: "", html_body: String(form.get("html_body") ?? ""),
      summary: String(form.get("summary") ?? ""), seo_description: String(form.get("summary") ?? ""),
      keywords: String(form.get("keywords") ?? "").split("|").map(item => item.trim()).filter(Boolean),
      blogger_labels: String(form.get("labels") ?? "").split(",").map(item => item.trim()).filter(Boolean),
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

  const pageCount = Math.max(1, Math.ceil((data?.total ?? 0) / 25));
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
            {tab === "body" && <div className="body-tab"><p className="article-summary">{value(latestRevision ?? {}, "seo_description") || value(detail, "summary")}</p><HtmlPreview html={htmlBody} lang={value(detail, "language_code")} />
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
