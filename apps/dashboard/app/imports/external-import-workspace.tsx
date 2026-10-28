"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import Link from "next/link";

type Row = Record<string, unknown>;
type Details = {
  item: Row; latest_version: Row | null; versions: Row[]; assessments: Row[]; reviews: Row[];
  editorial_review_status: string; localization_requests: Row[]; mock_publications: Row[];
  publish_ready: false; generation_ready: false;
};
type DetailTab = "editor" | "evidence" | "quality" | "preview" | "distribution" | "history";
const languages = ["ko", "en", "ja", "zh-CN"] as const;
const languageNames: Record<string, string> = { ko: "한국어", en: "영어", ja: "일본어", "zh-CN": "중국어 간체" };
const statusNames: Record<string, string> = {
  awaiting_human_review: "사람 검토 대기", review_started: "검토 중", changes_requested: "수정 필요",
  editorial_review_passed: "편집 검토 통과", requested: "외부 원고 대기", cancelled: "요청 취소",
  unknown: "미확인", unverified: "사실 검증 미완료", verified: "검증 완료", source_span_verified: "출처 문구 연결 확인",
  proposed: "제안", planned: "예정", approved: "승인", enacted: "시행", paid: "지급 완료",
  public_domain: "공공 영역", licensed: "이용 허가 확인", permission_required: "이용 허가 확인 필요", unknown_rights: "이용 권리 미확인",
  ready: "준비됨", review: "검토 필요", not_measured: "측정 안 됨", failed: "실패",
};
const displayState = (value: unknown) => statusNames[String(value ?? "")] ?? "기록된 상태";
const fmt = (value: unknown) => {
  const date = new Date(String(value ?? ""));
  return Number.isNaN(date.valueOf()) ? "—" : new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Seoul" }).format(date);
};
const escapeHtml = (value: unknown) => String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#39;");
const localStyle = `<style>body{margin:0;color:#202a34;font:17px/1.8 system-ui,sans-serif}article{max-width:740px;margin:auto;padding:24px}p{margin:0 0 1.25em;overflow-wrap:anywhere}h2{margin:2em 0 .7em;font-size:1.45em;line-height:1.4}h3{margin:1.7em 0 .6em;font-size:1.2em}a{color:#1857a4;overflow-wrap:anywhere}blockquote{border-left:3px solid #7d9bc4;margin:1.5em 0;padding:.5em 1em;color:#46576b}.wb-table-wrap{max-width:100%;overflow-x:auto}table{border-collapse:collapse;max-width:100%}th,td{border:1px solid #d6dce4;padding:.55em;text-align:left;overflow-wrap:anywhere}@media(max-width:430px){body{font-size:16px}article{padding:16px}}</style>`;

export function ExternalImportQueue() {
  const [items, setItems] = useState<Row[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    void fetch("/api/research/content-imports", { cache: "no-store" }).then(async response => {
      const data = await response.json();
      if (!response.ok) throw new Error("외부 원고 목록을 불러오지 못했습니다.");
      if (active) setItems((data.items ?? []) as Row[]);
    }).catch(reason => { if (active) setError(reason instanceof Error ? reason.message : "목록을 불러오지 못했습니다."); });
    return () => { active = false; };
  }, []);
  return <section className="workspace-panel" aria-labelledby="external-imports-title">
    <div className="section-heading"><div><h2 id="external-imports-title">외부 원고 검토 대기</h2><p>전체 {items.length}건 · 원고 제목을 누르면 해당 원고를 바로 엽니다.</p></div></div>
    {error ? <p role="alert" className="quality-held">{error}</p> : items.length ? <div className="publication-table-scroll"><table><thead><tr><th>제목</th><th>분야</th><th>언어</th><th>자료 지역</th><th>상태</th></tr></thead><tbody>{items.map(item => <tr key={String(item.id)} data-testid="external-import-row" data-content-id={String(item.external_content_id)}><td><Link href={`/imports?open_import_id=${encodeURIComponent(String(item.id))}`}>{String(item.title)}</Link></td><td>{categoryNames[String(item.category)] ?? String(item.category)}</td><td>{languageNames[String(item.language_code)] ?? String(item.language_code)}</td><td>{String(item.source_region)}</td><td>사람 검토 대기</td></tr>)}</tbody></table></div> : <p className="empty-state">검토 대기 중인 외부 원고가 없습니다.</p>}
  </section>;
}

const categoryNames: Record<string, string> = { economy: "경제", finance: "금융", stocks: "주식", crypto: "암호화폐", technology: "IT", semiconductors: "반도체", ai: "인공지능", policy: "정치·정책" };

export default function ExternalImportWorkspace() {
  const [items, setItems] = useState<Row[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [detail, setDetail] = useState<Details | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [submitter, setSubmitter] = useState("편집 담당자");
  const [json, setJson] = useState("");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [seo, setSeo] = useState<Row>({});
  const [labels, setLabels] = useState("");
  const [reason, setReason] = useState("사람 검토 후 내용을 명확히 수정");
  const [reviewer, setReviewer] = useState("편집 담당자");
  const [attest, setAttest] = useState({ sources: false, claims: false, rights: false });
  const [targetLanguage, setTargetLanguage] = useState<(typeof languages)[number]>("ko");
  const [detailTab, setDetailTab] = useState<DetailTab>("editor");
  const [preview, setPreview] = useState<Row | null>(null);
  const autoOpened = useRef("");
  const detailDialog = useRef<HTMLElement | null>(null);
  const returnFocus = useRef<HTMLElement | null>(null);

  const openDetail = useCallback(async (id: string) => {
    setError("");
    if (!detailDialog.current && document.activeElement instanceof HTMLElement) returnFocus.current = document.activeElement;
    const response = await fetch(`/api/research/content-imports/${id}`, { cache: "no-store" });
    const data = await response.json();
    if (!response.ok) throw new Error("원고 상세를 불러오지 못했습니다.");
    setSelectedId(id); setDetail(data as Details); setPreview(null); setDetailTab("editor");
    const current = data.latest_version ?? data.item;
    setTitle(String(current.title ?? "")); setBody(String(current.body_markdown ?? ""));
    setSeo(current.seo_metadata ?? data.item.seo_metadata ?? {});
    setLabels(Array.isArray(current.blogger_labels ?? data.item.blogger_labels) ? (current.blogger_labels ?? data.item.blogger_labels).join(", ") : "");
    const url = new URL(window.location.href);
    if (url.searchParams.get("open_import_id") !== id) {
      url.searchParams.set("open_import_id", id);
      window.history.pushState({ importDetail: id }, "", `${url.pathname}${url.search}${url.hash}`);
    }
  }, []);

  useEffect(() => {
    let active = true;
    void fetch("/api/research/content-imports", { cache: "no-store" }).then(async response => {
      const data = await response.json();
      if (!response.ok) throw new Error("외부 원고 목록을 불러오지 못했습니다.");
      if (active) setItems((data.items ?? []) as Row[]);
    }).catch(reason => { if (active) setError(reason instanceof Error ? reason.message : "목록을 불러오지 못했습니다."); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    const requestedId = new URLSearchParams(window.location.search).get("open_import_id") ?? "";
    if (!requestedId || autoOpened.current === requestedId || !items.some(item => String(item.id) === requestedId)) return;
    autoOpened.current = requestedId;
    void openDetail(requestedId);
  }, [items, openDetail]);

  const closeDetail = useCallback(() => {
    if (window.history.state?.importDetail) {
      window.history.back();
      return;
    }
    setDetail(null); setSelectedId("");
    const url = new URL(window.location.href);
    url.searchParams.delete("open_import_id");
    window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
  }, []);

  useEffect(() => {
    if (!detail) return;
    document.body.classList.add("sheet-open");
    detailDialog.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeDetail();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.classList.remove("sheet-open");
      window.removeEventListener("keydown", onKey);
      returnFocus.current?.focus();
    };
  }, [detail, closeDetail]);

  useEffect(() => {
    const onPopState = () => {
      const requestedId = new URLSearchParams(window.location.search).get("open_import_id");
      if (requestedId) void openDetail(requestedId);
      else { setDetail(null); setSelectedId(""); }
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [openDetail]);

  const latestVersion = detail?.latest_version;
  const latestAssessment = detail?.assessments?.[0];
  const reviewState = detail?.editorial_review_status ?? "awaiting_human_review";
  const publicationAllowed = Boolean(latestAssessment?.machine_passed && reviewState === "editorial_review_passed");
  const previewDocument = useMemo(() => preview?.safe_html ? `<!doctype html><html lang="${escapeHtml(detail?.item.language_code ?? "en")}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">${localStyle}</head><body><article><h1>${escapeHtml(preview.title)}</h1>${String(preview.safe_html)}</article></body></html>` : "", [preview, detail]);

  const api = async (path: string, method = "POST", payload?: unknown) => {
    const response = await fetch(`/api/research/content-imports/${selectedId}/${path}`, {
      method, headers: { "Content-Type": "application/json" }, body: payload === undefined ? undefined : JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "요청을 처리하지 못했습니다.");
    return data;
  };
  const run = async (action: () => Promise<unknown>, success: string) => {
    setBusy(true); setError(""); setNotice("");
    try { const result = await action(); setNotice(success); if (selectedId) await openDetail(selectedId); await refreshListOnly(); return result; }
    catch (reason) { setError(reason instanceof Error ? reason.message : "작업이 실패했습니다."); return null; }
    finally { setBusy(false); }
  };
  const refreshListOnly = async () => {
    const response = await fetch("/api/research/content-imports", { cache: "no-store" });
    if (response.ok) { const data = await response.json(); setItems((data.items ?? []) as Row[]); }
  };
  const submitImport = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy(true); setError(""); setNotice("");
    try {
      const parsed: unknown = JSON.parse(json);
      const envelope = typeof parsed === "object" && parsed !== null && "item" in parsed
        ? { ...(parsed as Record<string, unknown>), submitted_by: submitter }
        : { submitted_by: submitter, item: parsed };
      const response = await fetch("/api/research/content-imports", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(envelope) });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "원고 형식 검증에 실패했습니다.");
      if (data.duplicate) setNotice("같은 원고가 이미 등록되어 있습니다. 중복 버전이나 검토 기록은 추가하지 않았습니다.");
      else { setNotice("원고를 검토 대기열에 저장했습니다. 사실 검증과 사람 검토가 필요합니다."); await openDetail(data.import_id); }
      await refreshListOnly();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "원고 가져오기에 실패했습니다."); }
    finally { setBusy(false); }
  };
  const assess = async () => {
    const result = await run(() => api("assessment", "POST", { version_id: latestVersion?.id }), "결정론적 품질·SEO 검사를 기록했습니다. 사실 검증 및 발행은 별도입니다.");
    if (result) setPreview(result as Row);
  };
  const saveVersion = async () => {
    await run(() => api("versions", "POST", { base_version_id: latestVersion?.id, title, body_markdown: body,
      seo_metadata: seo, blogger_labels: labels.split(",").map(value => value.trim()).filter(Boolean),
      author_label: reviewer, reason }), "새 불변 원고 버전을 저장했습니다.");
  };
  const recordReview = (disposition: string) => run(() => api("reviews", "POST", {
    version_id: latestVersion?.id, disposition, reviewer_label: reviewer, reason,
    sources_examined: attest.sources, claims_checked: attest.claims, rights_reviewed: attest.rights,
  }), disposition === "editorial_review_passed" ? "편집 검토 이벤트를 기록했습니다. 이 기록은 Blogger 게시 승인과 다릅니다." : "검토 이력을 추가했습니다.");
  return <main className="workspace-main import-workspace" data-testid="import-workspace">
    <div className="page-heading"><div><p className="eyebrow">원고 관리 · 외부 원고</p><h1>원고 가져오기</h1><p><code>woori-content-import/1.0</code> 형식의 원고를 추가합니다. 가져온 원고는 별도 사람 검토 전까지 발행할 수 없습니다.</p></div><Link className="secondary-button" href="/manuscripts?view=external">원고 목록으로</Link></div>
    <div className="quality-held"><strong>발행 차단 유지</strong><p>원고 가져오기와 기계 검사만으로 generation_ready 또는 publish_ready를 변경하지 않습니다. Blogger API 요청·자동 발행·AI Provider 호출은 수행되지 않습니다.</p></div>
    <section className="workspace-panel import-panel"><h2>구조화 원고 가져오기</h2><p>JSON Schema: <code>docs/schemas/woori-content-import-1.0.schema.json</code></p>
      <form onSubmit={submitImport} className="import-form"><label>제출자 표시 이름<input required minLength={2} maxLength={100} value={submitter} onChange={event => setSubmitter(event.target.value)} /></label>
        <label htmlFor="import-json-file">JSON 파일 가져오기<input id="import-json-file" aria-label="JSON 파일 가져오기" type="file" accept=".json,application/json" onChange={async event => { const file = event.currentTarget.files?.[0]; if (!file) return; if (file.size > 150000) { setError("Import JSON 파일은 150KB 이하여야 합니다."); return; } setError(""); setJson(await file.text()); setNotice("JSON 파일을 불러왔습니다. 제출 전에 내용을 확인하세요."); }} /></label>
        <label>원고 JSON<textarea data-testid="import-json" required maxLength={150000} spellCheck={false} value={json} onChange={event => setJson(event.target.value)} placeholder="버전 1.0 형식의 원고 JSON을 붙여 넣으세요." /></label>
        <button disabled={busy || json.length === 0 || submitter.trim().length < 2}>{busy ? "처리 중…" : "검토 대기열에 가져오기"}</button></form>
    </section>
    {notice && <p role="status" className="quality-ok">{notice}</p>}{error && <p role="alert" className="quality-held">{error}</p>}
    <details className="workspace-panel import-recent"><summary>최근 가져온 원고 · {items.length}건</summary><div className="section-heading"><p>원고 제목을 누르면 해당 원고 상세가 바로 열립니다.</p><button type="button" className="secondary-button" onClick={() => void refreshListOnly()}>새로고침</button></div>
      {items.length ? <div className="publication-table-scroll"><table><thead><tr><th>제목</th><th>분야</th><th>언어</th><th>자료 지역</th><th>상태</th><th>접수 시각</th></tr></thead><tbody>{items.map(item => <tr key={String(item.id)} data-testid="import-row" data-content-id={String(item.external_content_id)}><td><button className="import-title" onClick={() => void openDetail(String(item.id))}>{String(item.title)}</button></td><td>{categoryNames[String(item.category)] ?? String(item.category)}</td><td>{languageNames[String(item.language_code)] ?? String(item.language_code)}</td><td>{String(item.source_region)}</td><td>사람 검토 대기</td><td>{fmt(item.received_at)}</td></tr>)}</tbody></table></div> : <p className="empty-state">가져온 원고가 없습니다.</p>}
    </details>
    {detail && latestVersion && <div className="sheet-backdrop import-sheet-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) closeDetail(); }}><section ref={detailDialog} tabIndex={-1} className="detail-sheet import-detail" role="dialog" aria-modal="true" aria-labelledby="import-detail-title" data-testid="import-detail" data-content-id={String(detail.item.external_content_id)}>
      <div className="section-heading import-detail-heading"><div><p className="eyebrow">{languageNames[String(detail.item.language_code)] ?? String(detail.item.language_code)} · {String(detail.item.source_region)} · {categoryNames[String(detail.item.category)] ?? String(detail.item.category)}</p><h2 id="import-detail-title">{String(latestVersion.title)}</h2><p>버전 {String(latestVersion.version_number)} · 수정 {fmt(latestVersion.created_at)} · 상태: {statusNames[reviewState] ?? "사람 검토 대기"}</p></div><button type="button" className="secondary-button" onClick={closeDetail}>닫기</button></div>
      <p className="quality-held"><strong>근거 상태: 외부 제출 · 독립 검증 미완료</strong> — 제출된 인용문과 검증 상태는 원문을 실제로 확인하기 전까지 주장의 증거로 승인되지 않습니다.</p>
      <nav className="import-detail-tabs" role="tablist" aria-label="원고 상세 탭">
        {([["editor", "원고 편집"], ["evidence", "출처·근거"], ["quality", "품질·SEO"], ["preview", "HTML 미리보기"], ["distribution", "다국어·발행"], ["history", "변경 이력"]] as const).map(([id, label]) =>
          <button key={id} type="button" role="tab" disabled={busy} aria-selected={detailTab === id} onClick={() => setDetailTab(id)}>{label}</button>)}
      </nav>
      <div role="tabpanel" aria-label="원고 상세 내용" className="import-detail-content">
        {detailTab === "editor" && <>
          <section className="workspace-panel" id="import-editor"><h3>원고 편집</h3><label>제목<input data-testid="import-title-input" value={title} onChange={event => setTitle(event.target.value)} /></label><label>본문 Markdown<textarea data-testid="import-body-input" value={body} onChange={event => setBody(event.target.value)} /></label><label>SEO 제목<input value={String(seo.seo_title ?? "")} onChange={event => setSeo({ ...seo, seo_title: event.target.value })} /></label><label>검색 설명<textarea value={String(seo.search_description ?? "")} onChange={event => setSeo({ ...seo, search_description: event.target.value })} /></label><label>Blogger 라벨<input value={labels} onChange={event => setLabels(event.target.value)} /></label><label>수정 사유<input value={reason} onChange={event => setReason(event.target.value)} /></label><label>작성자 표시<input value={reviewer} onChange={event => setReviewer(event.target.value)} /></label><button type="button" data-testid="save-import-version" disabled={busy} onClick={() => void saveVersion()}>새 버전 저장</button>
            <div className="import-actions"><button type="button" disabled={busy || body.trim().length < 100} onClick={() => void assess()}>{busy ? "검사 중…" : "품질·SEO·HTML 검사"}</button><button type="button" className="secondary-button" disabled={!latestAssessment} onClick={() => { if (latestAssessment) { setPreview({ title: title || String(latestVersion.title ?? detail.item.title ?? ""), safe_html: latestAssessment.safe_html, seo_checks: latestAssessment.seo_checks, html_sha256: latestAssessment.html_sha256 }); setDetailTab("preview"); } }}>게시용 미리보기</button></div>
          </section>
        </>}
        {detailTab === "evidence" && <section className="workspace-panel" id="import-evidence"><h3>출처와 주장</h3>{(Array.isArray(detail.item.sources) ? detail.item.sources as Row[] : []).map(source => <article className="history-card" key={String(source.source_id)}><a href={String(source.url)} target="_blank" rel="noreferrer">{String(source.title)}</a><p>{String(source.organization)} · 이용권한: {displayState(source.rights_status)} · 독립 검증 전</p></article>)}{(Array.isArray(detail.item.claims) ? detail.item.claims as Row[] : []).map(claim => <article className="history-card" key={String(claim.claim_id)}><strong>{String(claim.claim)}</strong><p>연결된 외부 출처: {Array.isArray(claim.source_ids) ? claim.source_ids.map(sourceId => (Array.isArray(detail.item.sources) ? detail.item.sources as Row[] : []).find(source => source.source_id === sourceId)?.title ?? "출처명 미확인").join(" · ") : "—"} · 제출 상태: {displayState(claim.verification_status)} · 사실 상태 주장: {displayState(claim.factual_state)}</p><details><summary>제출된 발췌문 보기</summary><blockquote>{String(claim.evidence_excerpt)}</blockquote></details></article>)}</section>}
        {detailTab === "quality" && <section className="workspace-panel" id="import-quality"><h3>품질·SEO 검사</h3>{latestAssessment ? <><p className={latestAssessment.machine_passed ? "quality-ok" : "quality-held"}>{latestAssessment.machine_passed ? "결정론적 규칙 통과" : "기계 검사 보류"}. 이 결과는 사실의 의미적 정확성·권리·자연스러움을 보증하지 않습니다.</p><ul>{((latestAssessment.seo_checks ?? []) as Row[]).map(check => <li key={String(check.key)}>{displayState(check.status)} · {String(check.message)}</li>)}</ul><details><summary>세부 검사 결과</summary><pre>{JSON.stringify(latestAssessment.machine_checks, null, 2)}</pre></details></> : <p className="empty-state">아직 품질·SEO 검사를 실행하지 않았습니다.</p>}</section>}
        {detailTab === "preview" && <section className="workspace-panel" id="import-preview">{previewDocument ? <><div className="section-heading"><div><h3>게시용 HTML 미리보기</h3><p>디자인 렌더러 결과 · {String(preview?.html_sha256 ?? latestAssessment?.html_sha256 ?? "")} · 실제 Blogger 테마 적용 결과와 다를 수 있습니다.</p></div></div><iframe data-testid="import-html-preview" title="게시용 원고 미리보기" sandbox="" srcDoc={previewDocument} /></> : <p className="empty-state">먼저 원고 편집 탭에서 품질·HTML 검사를 실행하고 게시용 미리보기를 엽니다.</p>}</section>}
        {detailTab === "distribution" && <>
          <section className="workspace-panel" id="import-localization"><h3>다국어 확장</h3><p>생성 Provider가 연결되지 않아 요청은 대기하며 원고를 생성한 것으로 표시하지 않습니다.</p><label>대상 언어<select value={targetLanguage} onChange={event => setTargetLanguage(event.target.value as typeof targetLanguage)}>{languages.filter(language => language !== detail.item.language_code).map(language => <option key={language} value={language}>{languageNames[language]}</option>)}</select></label><button type="button" className="secondary-button" disabled={busy} onClick={() => void run(() => api("localizations", "POST", { target_language: targetLanguage, requester_label: reviewer, reason: "요청한 언어로 외부 원고를 준비하고 사람 검토 대기" }), "다국어 원고 요청을 외부 공급자 대기로 저장했습니다.")}>현지화 원고 요청</button>{detail.localization_requests.map(request => <article className="history-card" key={String(request.target_language)}><p>{languageNames[String(request.target_language)]} · {statusNames[String(request.event_type)] ?? String(request.event_type)} · {fmt(request.created_at)}</p>{request.event_type === "requested" && <button type="button" className="secondary-button" disabled={busy} onClick={() => void run(() => api(`localizations/${encodeURIComponent(String(request.target_language))}/cancel`, "POST", { requester_label: reviewer, reason: "사용자가 다국어 확장 요청을 취소" }), "현지화 요청을 취소 기록으로 저장했습니다.")}>요청 취소</button>}</article>)}</section>
          <section className="workspace-panel" id="import-review"><h3>사람 편집 검토</h3><label>검토자 표시 이름<input value={reviewer} onChange={event => setReviewer(event.target.value)} /></label><label>검토 메모<input value={reason} onChange={event => setReason(event.target.value)} /></label><div className="review-attestations"><label><input type="checkbox" checked={attest.sources} onChange={event => setAttest({ ...attest, sources: event.target.checked })} />원문 문서를 직접 확인했습니다</label><label><input type="checkbox" checked={attest.claims} onChange={event => setAttest({ ...attest, claims: event.target.checked })} />주장과 근거를 대조했습니다</label><label><input type="checkbox" checked={attest.rights} onChange={event => setAttest({ ...attest, rights: event.target.checked })} />저작권·인용 권리를 검토했습니다</label></div><div className="import-actions"><button type="button" className="secondary-button" disabled={busy} onClick={() => void recordReview("review_started")}>검토 시작</button><button type="button" className="secondary-button" disabled={busy} onClick={() => void recordReview("changes_requested")}>수정 요청</button><button type="button" disabled={busy || !latestAssessment?.machine_passed || !attest.sources || !attest.claims || !attest.rights} onClick={() => void recordReview("editorial_review_passed")}>편집 검토 통과 기록</button></div><p>편집 검토는 Blogger 발행 승인과 별개이며 이 화면에서 실제 게시하지 않습니다.</p></section>
          <section className="workspace-panel" id="import-publication"><h3>모의 게시</h3><p>실제 Blogger 요청이 아닌 테스트 시뮬레이션입니다. publish_ready=false는 유지됩니다.</p><button type="button" className="secondary-button" data-testid="mock-publish" disabled={busy || !publicationAllowed} onClick={() => void run(() => api("mock-publications", "POST", { version_id: latestVersion.id, idempotency_key: `import-${selectedId}-${String(latestVersion.content_sha256).slice(0,64)}`, scenario: "success", requested_by: reviewer }), "테스트 어댑터 결과를 기록했습니다. 실제 Blogger에는 변경이 없습니다.")}>모의 게시 시뮬레이션</button>{!publicationAllowed && <p role="status">현재 버전에 통과한 검사와 명시적 편집 검토 기록이 모두 있어야 모의 게시를 실행할 수 있습니다.</p>}{detail.mock_publications.map(attempt => <p key={String(attempt.id)}>모의 결과: {String(attempt.outcome)} · 모의 전용 · 외부 요청 0건</p>)}</section>
        </>}
        {detailTab === "history" && <section className="workspace-panel" id="import-history"><h3>버전 및 변경 이력</h3>{detail.versions.map(version => <article className="history-card" key={String(version.id)}><strong>v{String(version.version_number)} · {String(version.title)}</strong><p>{fmt(version.created_at)} · {String(version.author_label)} · {String(version.change_reason)}</p>{version.id !== latestVersion.id && <button type="button" className="secondary-button" onClick={() => void openDetail(selectedId)}>최신 버전 새로고침</button>}</article>)}{detail.reviews.map(event => <article className="history-card" key={String(event.version_id) + String(event.created_at)}><strong>{statusNames[String(event.event_type)] ?? String(event.event_type)}</strong><p>{String(event.reviewer_label)} · {fmt(event.created_at)} · {String(event.reason)}</p></article>)}</section>}
      </div>
      <p className="quality-held">이 가져오기 흐름은 품질·편집 검토·모의 게시까지 제공합니다. 실제 게시 준비에는 별도 승인 경로와 운영 DB 스키마 갱신이 필요합니다.</p>
    </section></div>}
  </main>;
}
