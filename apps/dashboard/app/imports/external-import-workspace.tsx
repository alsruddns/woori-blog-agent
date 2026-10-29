"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import Link from "next/link";

type Row = Record<string, unknown>;
type Details = {
  item: Row; latest_version: Row | null; versions: Row[]; lineage_history?: Row[]; assessments: Row[]; reviews: Row[];
  source_verifications?: Row[]; editorial_review_status: string; localization_requests: Row[]; mock_publications: Row[];
  publication?: Row; publish_ready: false; generation_ready: false;
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
const importReviewLabel = (item: Row) => {
  const review = String(item.editorial_review_status ?? "");
  if (review === "editorial_review_passed") return "편집 검토 완료";
  if (review === "review_started") return "편집 검토 중";
  if (review === "changes_requested") return "수정 요청";
  if (item.machine_passed !== true) return "기계 검사 필요";
  return "편집 검토 대기";
};
const publicationBlockerNames: Record<string, string> = {
  not_a_codex_scheduled_export: "Codex 예약 Export 원고가 아닙니다.",
  scheduled_version_not_promoted: "최신 예약 원고 버전이 운영 콘텐츠 버전과 연결되지 않았습니다.",
  latest_version_machine_assessment_not_passed: "최신 버전의 기계 검사가 통과하지 않았습니다.",
  editorial_review_not_passed: "이 정확한 원고 버전의 편집 검토 통과 및 출처·주장·권리 확인이 필요합니다.",
  scheduled_evidence_assessment_not_passed: "출처·주장 증거 평가가 통과하지 않았습니다.",
  scheduled_auto_policy_inactive: "예약 원고 Auto 정책이 활성화되지 않았습니다.",
  publication_emergency_stop_active: "긴급 발행 정지가 활성 상태입니다.",
  blog_not_in_active_scheduled_scope: "대상 블로그가 활성 예약 Auto 범위에 없습니다.",
  blogger_write_oauth_not_verified: "대상 블로그의 Blogger 쓰기 연결이 확인되지 않았습니다.",
  scheduled_live_write_policy_not_available: "예약 Blogger 쓰기 정책이 허용되지 않습니다.",
  first_publication_already_approved: "현재 버전·블로그의 첫 공개 승인이 이미 기록됐습니다.",
  remote_publication_already_recorded: "이 콘텐츠 버전의 원격 게시 기록이 있어 중복 발행을 차단했습니다.",
};
const fmt = (value: unknown) => {
  const date = new Date(String(value ?? ""));
  return Number.isNaN(date.valueOf()) ? "—" : new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Seoul" }).format(date);
};
const escapeHtml = (value: unknown) => String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#39;");
const localStyle = `<style>body{margin:0;color:#202a34;font:17px/1.8 system-ui,sans-serif}article{max-width:740px;margin:auto;padding:24px}p{margin:0 0 1.25em;overflow-wrap:anywhere}h2{margin:2em 0 .7em;font-size:1.45em;line-height:1.4}h3{margin:1.7em 0 .6em;font-size:1.2em}a{color:#1857a4;overflow-wrap:anywhere}blockquote{border-left:3px solid #7d9bc4;margin:1.5em 0;padding:.5em 1em;color:#46576b}.wb-table-wrap{max-width:100%;overflow-x:auto}table{border-collapse:collapse;max-width:100%}th,td{border:1px solid #d6dce4;padding:.55em;text-align:left;overflow-wrap:anywhere}@media(max-width:430px){body{font-size:16px}article{padding:16px}}</style>`;

export function ExternalImportQueue() {
  const [items, setItems] = useState<Row[]>([]);
  const [error, setError] = useState("");
  const [origin, setOrigin] = useState("all");
  useEffect(() => {
    let active = true;
    void fetch("/api/research/content-imports", { cache: "no-store" }).then(async response => {
      const data = await response.json();
      if (!response.ok) throw new Error("외부 원고 목록을 불러오지 못했습니다.");
      if (active) setItems((data.items ?? []) as Row[]);
    }).catch(reason => { if (active) setError(reason instanceof Error ? reason.message : "목록을 불러오지 못했습니다."); });
    return () => { active = false; };
  }, []);
  const visibleItems = items.filter(item => origin === "all"
    || (origin === "trends" ? item.google_trends_based === true
      : item.generation_method === origin && item.google_trends_based !== true));
  return <section className="workspace-panel" aria-labelledby="external-imports-title">
    <div className="section-heading"><div><h2 id="external-imports-title">가져온 원고 · 출처·근거 검토</h2><p>Codex 예약·수동 Import 등 가져온 원고를 보여줍니다. 같은 원고 계열은 최신 대표 버전만 표시하고 이전 버전은 상세의 변경 이력에서 확인합니다.</p></div></div>
    <label>생성 경로<select value={origin} onChange={event => setOrigin(event.target.value)}><option value="all">전체</option><option value="chatgpt_scheduled_export">Codex 예약</option><option value="manual_codex_import">수동 작성·Import</option><option value="trends">Google Trends</option><option value="other_external_export">기타 외부 Import</option></select></label>
    {error ? <p role="alert" className="quality-held">{error}</p> : visibleItems.length ? <div className="publication-table-scroll import-list-scroll"><table><thead><tr><th>제목</th><th>생성 경로</th><th>분야</th><th>언어</th><th>자료 지역</th><th>상태</th></tr></thead><tbody>{visibleItems.map(item => <tr key={String(item.id)} data-testid="external-import-row" data-content-id={String(item.external_content_id)}><td><Link href={`/imports?open_import_id=${encodeURIComponent(String(item.id))}`}>{String(item.title)}</Link></td><td>{item.google_trends_based === true ? "Google Trends" : item.generation_method === "chatgpt_scheduled_export" ? "Codex 예약" : item.generation_method === "manual_codex_import" ? "수동 작성·Import" : "기타 외부 Import"}</td><td>{categoryNames[String(item.category)] ?? String(item.category)}</td><td>{languageNames[String(item.language_code)] ?? String(item.language_code)}</td><td>{String(item.source_region)}</td><td><span className="status-text">{importReviewLabel(item)}</span></td></tr>)}</tbody></table></div> : <p className="empty-state">선택한 경로에 원고가 없습니다.</p>}
  </section>;
}

const categoryNames: Record<string, string> = { economy: "경제", finance: "금융", stocks: "주식", crypto: "암호화폐", technology: "IT", semiconductors: "반도체", ai: "인공지능", policy: "정치·정책" };

export default function ExternalImportWorkspace() {
  const [items, setItems] = useState<Row[]>([]);
  const [originFilter, setOriginFilter] = useState("all");
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
  const [publicationTargetId, setPublicationTargetId] = useState("");
  const [approvalActor, setApprovalActor] = useState("");
  const [approvalReason, setApprovalReason] = useState("");
  const [targetLanguage, setTargetLanguage] = useState<(typeof languages)[number]>("ko");
  const [detailTab, setDetailTab] = useState<DetailTab>("editor");
  const [preview, setPreview] = useState<Row | null>(null);
  const autoOpened = useRef("");
  const detailDialog = useRef<HTMLElement | null>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const firstApprovalIdempotencyKey = useRef("");

  const openDetail = useCallback(async (id: string) => {
    setError("");
    autoOpened.current = id;
    if (!detailDialog.current && document.activeElement instanceof HTMLElement) returnFocus.current = document.activeElement;
    const [response, publicationResponse] = await Promise.all([
      fetch(`/api/research/content-imports/${id}`, { cache: "no-store" }),
      fetch(`/api/publications/scheduled-auto-first-post?import_id=${encodeURIComponent(id)}`, { cache: "no-store" }),
    ]);
    const data = await response.json();
    if (!response.ok) throw new Error("원고 상세를 불러오지 못했습니다.");
    const publication = publicationResponse.ok
      ? await publicationResponse.json() as Row
      : { status_error: publicationResponse.status === 404 ? "예약 발행 상태 조회 API를 찾을 수 없습니다." : "예약 발행 상태를 조회하지 못했습니다." };
    const nextDetail = { ...data, publication } as Details;
    setSelectedId(id); setDetail(nextDetail); setPreview(null); setDetailTab("editor");
    const publicationTargets = (publication.targets as Row[] | undefined) ?? [];
    const defaultTarget = publicationTargets.find(target => target.in_scheduled_scope === true)
      ?? publicationTargets[0];
    setPublicationTargetId(String(defaultTarget?.id ?? ""));
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
    const url = new URL(window.location.href);
    const returnTo = url.searchParams.get("return_to");
    if (returnTo && returnTo.startsWith("/") && !returnTo.startsWith("//") && !returnTo.includes("\\")) {
      window.location.assign(returnTo);
      return;
    }
    if (window.history.state?.importDetail) {
      window.history.back();
      return;
    }
    setDetail(null); setSelectedId("");
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
  const refreshScheduledPublication = async (id = selectedId) => {
    const response = await fetch(`/api/publications/scheduled-auto-first-post?import_id=${encodeURIComponent(id)}`, { cache: "no-store" });
    const publication = response.ok ? await response.json() as Row
      : { status_error: response.status === 404 ? "예약 발행 상태 조회 API를 찾을 수 없습니다." : "예약 발행 상태를 조회하지 못했습니다." };
    setDetail(current => current && String(current.item.id) === id ? { ...current, publication } : current);
    return publication;
  };
  const approveFirstPublication = async () => {
    if (!detail) return;
    const publication = detail.publication ?? {};
    const targets = (publication.targets as Row[] | undefined) ?? [];
    const target = targets.find(item => String(item.id ?? "") === publicationTargetId);
    const blockers = (target?.approval_blockers as string[] | undefined) ?? [];
    if (!target || target.can_record_first_approval !== true || blockers.length > 0) return;
    const bodySha = String(publication.body_sha256 ?? "");
    const titleText = String(publication.title ?? detail.latest_version?.title ?? "원고 제목 미확인");
    const confirmed = window.confirm(
      `이 원고의 첫 Blogger 공개 발행을 승인합니다.\n\n제목: ${titleText}\n원고 버전: ${String(publication.version_number ?? "미확인")}\n본문 SHA-256: ${bodySha}\n대상: ${String(target.display_name ?? "Blogger")} · ${String(target.url ?? "")}\nBlogger ID: ${String(target.blog_id ?? "미확인")}\n\n이 동작은 정확한 원고·버전·해시·블로그에 승인 이력을 기록합니다. 승인 후 Publication Worker가 모든 게이트를 다시 검사하며, 이 화면은 Blogger 쓰기 요청을 직접 보내지 않습니다.`
    );
    if (!confirmed) return;
    setBusy(true); setError(""); setNotice("");
    if (!firstApprovalIdempotencyKey.current) firstApprovalIdempotencyKey.current = `scheduled-first-${crypto.randomUUID()}`;
    try {
      const response = await fetch("/api/publications/scheduled-auto-first-post", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          blog_id: target.id, import_id: publication.import_id,
          import_version_id: publication.import_version_id,
          content_version_id: publication.content_version_id,
          body_sha256: bodySha, actor_label: approvalActor.trim(), reason: approvalReason.trim(),
          idempotency_key: firstApprovalIdempotencyKey.current,
          confirmation: "APPROVE THIS SCHEDULED MANUSCRIPT FOR FIRST PUBLICATION",
        }),
      });
      const result = await response.json() as Row;
      if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "첫 공개 승인을 기록하지 못했습니다.");
      firstApprovalIdempotencyKey.current = "";
      setNotice("정확한 원고 버전의 첫 공개 승인 이력을 기록했습니다. 실제 게시 요청은 기존 Publication Worker가 안전 게이트를 다시 확인한 뒤 처리합니다.");
      await refreshScheduledPublication();
      await refreshListOnly();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "첫 공개 승인 요청 실패");
    } finally { setBusy(false); }
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
  const visibleImports = items.filter(item => originFilter === "all"
    || (originFilter === "trends" ? item.google_trends_based === true
      : item.google_trends_based !== true && item.generation_method === originFilter));
  const submitManualPublication = async () => {
    if (!detail || !latestVersion?.content_version_id || !publicationTargetId) return;
    const target = ((detail.publication?.targets as Row[] | undefined) ?? []).find(item => String(item.id) === publicationTargetId);
    const digest = String((target?.manual_publication as Row | undefined)?.body_sha256 ?? "");
    const titleText = String(latestVersion.title ?? detail.item.title ?? "제목 없음");
    if (!target || !window.confirm(`이 수동 원고의 Blogger 공개 발행을 요청합니다.\n\n제목: ${titleText}\nContent Version: ${String(latestVersion.content_version_id)}\n본문 SHA-256: ${digest || "확인 불가"}\n대상: ${String(target.display_name)} · ${String(target.url)}\n\n서버의 승인·품질·권리·중복·실제 쓰기 게이트가 하나라도 미충족이면 작업은 차단됩니다.`)) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const response = await fetch("/api/publications/live-requests", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content_version_id: latestVersion.content_version_id, blog_id: publicationTargetId,
          idempotency_key: `manual-live-${String(latestVersion.content_version_id)}-${publicationTargetId}` }) });
      const result = await response.json() as Row;
      if (!response.ok) throw new Error(String(result.detail ?? "공개 발행 요청을 처리하지 못했습니다."));
      if (result.recorded === false) throw new Error(`발행이 차단되었습니다: ${Array.isArray(result.reasons) ? result.reasons.join(", ") : "필수 조건 미충족"}`);
      setNotice(`공개 발행 Job ${String(result.id ?? "")}을 등록했습니다. 실제 Blogger 게시 결과는 Worker 처리 후 표시됩니다.`);
      await openDetail(selectedId); await refreshListOnly();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "공개 발행 요청 실패"); }
    finally { setBusy(false); }
  };
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
    <details className="workspace-panel import-recent"><summary>최근 가져온 원고 · {visibleImports.length}건</summary><div className="section-heading"><p>원고 제목을 누르면 해당 원고 상세가 바로 열립니다.</p><button type="button" className="secondary-button" onClick={() => void refreshListOnly()}>새로고침</button></div>
      <label>생성 경로<select aria-label="가져온 원고 생성 경로" value={originFilter} onChange={event => setOriginFilter(event.target.value)}><option value="all">전체 원고</option><option value="chatgpt_scheduled_export">Codex 예약</option><option value="manual_codex_import">수동 작성·Import</option><option value="trends">Google Trends</option><option value="other_external_export">기타 외부 원고</option></select></label>
      {visibleImports.length ? <div className="publication-table-scroll import-list-scroll"><table><thead><tr><th>제목</th><th>생성 경로</th><th>분야</th><th>언어</th><th>자료 지역</th><th>상태</th><th>접수 시각</th></tr></thead><tbody>{visibleImports.map(item => <tr key={String(item.id)} data-testid="import-row" data-content-id={String(item.external_content_id)}><td><button className="import-title" title={String(item.title)} onClick={() => void openDetail(String(item.id))}>{String(item.title)}</button></td><td>{item.google_trends_based === true ? "Google Trends" : item.generation_method === "chatgpt_scheduled_export" ? "Codex 예약" : item.generation_method === "manual_codex_import" ? "수동 작성·Import" : "기타 외부 원고"}</td><td>{categoryNames[String(item.category)] ?? String(item.category)}</td><td>{languageNames[String(item.language_code)] ?? String(item.language_code)}</td><td>{String(item.source_region)}</td><td><span className="status-text">{importReviewLabel(item)}</span></td><td>{fmt(item.received_at)}</td></tr>)}</tbody></table></div> : <p className="empty-state">선택한 생성 경로의 원고가 없습니다.</p>}
    </details>
    {detail && latestVersion && <div className="sheet-backdrop import-sheet-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) closeDetail(); }}><section ref={detailDialog} tabIndex={-1} className="detail-sheet import-detail" role="dialog" aria-modal="true" aria-labelledby="import-detail-title" data-testid="import-detail" data-content-id={String(detail.item.external_content_id)}>
      <div className="section-heading import-detail-heading"><div><p className="eyebrow">{languageNames[String(detail.item.language_code)] ?? String(detail.item.language_code)} · {String(detail.item.source_region)} · {categoryNames[String(detail.item.category)] ?? String(detail.item.category)}</p><h2 id="import-detail-title">{String(latestVersion.title)}</h2><p>버전 {String(latestVersion.version_number)} · 수정 {fmt(latestVersion.created_at)} · 상태: {statusNames[reviewState] ?? "사람 검토 대기"}</p></div><button type="button" className="secondary-button" onClick={closeDetail}>닫기</button></div>
      <p className="quality-held import-evidence-status" role="status"><strong>근거 검토 대기</strong> · 공식 원문·주장 연결·독립 근거·이용 권리를 확인하기 전까지 발행 근거로 승인되지 않습니다. 자세한 확인 결과는 출처·근거 탭에 있습니다.</p>
      <nav className="import-detail-tabs" role="tablist" aria-label="원고 상세 탭" onKeyDown={event => {
        const ids: DetailTab[] = ["editor", "evidence", "quality", "preview", "distribution", "history"];
        const current = ids.indexOf(detailTab);
        const next = event.key === "ArrowRight" ? (current + 1) % ids.length
          : event.key === "ArrowLeft" ? (current + ids.length - 1) % ids.length
            : event.key === "Home" ? 0 : event.key === "End" ? ids.length - 1 : -1;
        if (next >= 0) {
          event.preventDefault();
          const target = ids[next];
          setDetailTab(target);
          requestAnimationFrame(() => document.getElementById(`import-tab-${target}`)?.focus());
        }
      }}>
        {([['editor', '원고 편집'], ['evidence', '출처·근거'], ['quality', '품질·SEO'], ['preview', 'HTML 미리보기'], ['distribution', '다국어·발행'], ['history', '변경 이력']] as const).map(([id, label]) =>
          <button key={id} id={`import-tab-${id}`} type="button" role="tab" disabled={busy} aria-controls={`import-panel-${id}`} aria-selected={detailTab === id} tabIndex={detailTab === id ? 0 : -1} onClick={event => { setDetailTab(id); event.currentTarget.scrollIntoView({ block: "nearest", inline: "nearest" }); }}>{label}</button>)}
      </nav>
      <div role="tabpanel" aria-label="원고 상세 내용" className="import-detail-content">
        {detailTab === "editor" && <>
          <section className="workspace-panel" id="import-editor"><h3>원고 편집</h3><label>제목<input data-testid="import-title-input" value={title} onChange={event => setTitle(event.target.value)} /></label><label>본문 Markdown<textarea data-testid="import-body-input" value={body} onChange={event => setBody(event.target.value)} /></label><label>SEO 제목<input value={String(seo.seo_title ?? "")} onChange={event => setSeo({ ...seo, seo_title: event.target.value })} /></label><label>검색 설명<textarea value={String(seo.search_description ?? "")} onChange={event => setSeo({ ...seo, search_description: event.target.value })} /></label><label>Blogger 라벨<input value={labels} onChange={event => setLabels(event.target.value)} /></label><label>수정 사유<input value={reason} onChange={event => setReason(event.target.value)} /></label><label>작성자 표시<input value={reviewer} onChange={event => setReviewer(event.target.value)} /></label><button type="button" data-testid="save-import-version" disabled={busy} onClick={() => void saveVersion()}>새 버전 저장</button>
            <div className="import-actions"><button type="button" disabled={busy || body.trim().length < 100} onClick={() => void assess()}>{busy ? "검사 중…" : "품질·SEO·HTML 검사"}</button><button type="button" className="secondary-button" disabled={!latestAssessment} onClick={() => { if (latestAssessment) { setPreview({ title: title || String(latestVersion.title ?? detail.item.title ?? ""), safe_html: latestAssessment.safe_html, seo_checks: latestAssessment.seo_checks, html_sha256: latestAssessment.html_sha256 }); setDetailTab("preview"); } }}>게시용 미리보기</button></div>
          </section>
        </>}
        {detailTab === "evidence" && <section className="workspace-panel" id="import-evidence"><h3>출처와 주장</h3>
          {(detail.source_verifications ?? []).map(record => {
            const check = record.payload && typeof record.payload === "object" ? record.payload as Row : {};
            return <article className="source-live-verification" key={`${String(check.source_id)}-${String(record.created_at)}`}>
              <strong>공식 원문 HTTP {String(check.http_status ?? "미확인")} · {String(check.document_title ?? "문서 제목 미확인")}</strong>
              <p>확인 시각 {fmt(check.checked_at ?? check.verified_at ?? record.created_at)} · 발표 {fmt(check.published_at)} · 출처 호스트 {String(check.source_host ?? "미확인")}</p>
              {Boolean(check.url) && <a href={String(check.url)} target="_blank" rel="noopener noreferrer">Federal Reserve 원문 열기</a>}
              <p>독립 출처 {String(check.independent_source_count ?? 0)}건 · 권리 {String(check.rights_status ?? "미확인")} · 사람의 의미·권리 검토 미완료</p>
              <p>원문에서 확인한 근거 구간</p>
              {Array.isArray(check.verified_claim_evidence) && <ul>{(check.verified_claim_evidence as unknown[]).map((excerpt, index) => <li key={index}>{String(excerpt)}</li>)}</ul>}
              <p>사람의 의미·권리 검토: {String(check.human_semantic_review ?? "대기")} · 권리 승인: {check.rights_approved === true ? "승인 기록 있음" : "미승인"}</p>
            </article>;
          })}
          {!detail.source_verifications?.length && <p className="quality-held">현재 확인 기록 없음 · 수집 시 출처 상태와 실제 원문 확인은 별도입니다.</p>}
          {(Array.isArray(detail.item.sources) ? detail.item.sources as Row[] : []).map(source => <article className="history-card" key={String(source.source_id)}><a href={String(source.url)} target="_blank" rel="noopener noreferrer">{String(source.title)}</a><p>{String(source.organization)} · 발표 {fmt(source.published_at)} · 이용권한: {displayState(source.rights_status)} · 독립 검증 전</p></article>)}
          {(Array.isArray(detail.item.claims) ? detail.item.claims as Row[] : []).map(claim => <article className="history-card" key={String(claim.claim_id)}><strong>{String(claim.claim)}</strong><p>연결된 외부 출처: {Array.isArray(claim.source_ids) ? claim.source_ids.map(sourceId => (Array.isArray(detail.item.sources) ? detail.item.sources as Row[] : []).find(source => source.source_id === sourceId)?.title ?? "출처명 미확인").join(" · ") : "—"} · 제출 상태: {displayState(claim.verification_status)} · 사실 상태 주장: {displayState(claim.factual_state)}</p><details><summary>제출된 발췌문 보기</summary><blockquote>{String(claim.evidence_excerpt)}</blockquote></details></article>)}
        </section>}
        {detailTab === "quality" && <section className="workspace-panel" id="import-quality"><h3>품질·SEO 검사</h3>{latestAssessment ? <QualityAssessmentPanel assessment={latestAssessment} /> : <p className="empty-state">아직 품질·SEO 검사를 실행하지 않았습니다.</p>}</section>}
        {detailTab === "preview" && <section className="workspace-panel" id="import-preview">{previewDocument ? <><div className="section-heading"><div><h3>게시용 HTML 미리보기</h3><p>디자인 렌더러 결과 · {String(preview?.html_sha256 ?? latestAssessment?.html_sha256 ?? "")} · 실제 Blogger 테마 적용 결과와 다를 수 있습니다.</p></div></div><iframe data-testid="import-html-preview" title="게시용 원고 미리보기" sandbox="" srcDoc={previewDocument} /></> : <p className="empty-state">먼저 원고 편집 탭에서 품질·HTML 검사를 실행하고 게시용 미리보기를 엽니다.</p>}</section>}
        {detailTab === "distribution" && <>
          <section className="workspace-panel" id="import-localization"><h3>다국어 확장</h3><p>생성 Provider가 연결되지 않아 요청은 대기하며 원고를 생성한 것으로 표시하지 않습니다.</p><label>대상 언어<select value={targetLanguage} onChange={event => setTargetLanguage(event.target.value as typeof targetLanguage)}>{languages.filter(language => language !== detail.item.language_code).map(language => <option key={language} value={language}>{languageNames[language]}</option>)}</select></label><button type="button" className="secondary-button" disabled={busy} onClick={() => void run(() => api("localizations", "POST", { target_language: targetLanguage, requester_label: reviewer, reason: "요청한 언어로 외부 원고를 준비하고 사람 검토 대기" }), "다국어 원고 요청을 외부 공급자 대기로 저장했습니다.")}>현지화 원고 요청</button>{detail.localization_requests.map(request => <article className="history-card" key={String(request.target_language)}><p>{languageNames[String(request.target_language)]} · {statusNames[String(request.event_type)] ?? String(request.event_type)} · {fmt(request.created_at)}</p>{request.event_type === "requested" && <button type="button" className="secondary-button" disabled={busy} onClick={() => void run(() => api(`localizations/${encodeURIComponent(String(request.target_language))}/cancel`, "POST", { requester_label: reviewer, reason: "사용자가 다국어 확장 요청을 취소" }), "현지화 요청을 취소 기록으로 저장했습니다.")}>요청 취소</button>}</article>)}</section>
          <section className="workspace-panel" id="import-review"><h3>사람 편집 검토</h3><label>검토자 표시 이름<input value={reviewer} onChange={event => setReviewer(event.target.value)} /></label><label>검토 메모<input value={reason} onChange={event => setReason(event.target.value)} /></label><div className="review-attestations"><label><input type="checkbox" checked={attest.sources} onChange={event => setAttest({ ...attest, sources: event.target.checked })} />원문 문서를 직접 확인했습니다</label><label><input type="checkbox" checked={attest.claims} onChange={event => setAttest({ ...attest, claims: event.target.checked })} />주장과 근거를 대조했습니다</label><label><input type="checkbox" checked={attest.rights} onChange={event => setAttest({ ...attest, rights: event.target.checked })} />저작권·인용 권리를 검토했습니다</label></div><div className="import-actions"><button type="button" className="secondary-button" disabled={busy} onClick={() => void recordReview("review_started")}>검토 시작</button><button type="button" className="secondary-button" disabled={busy} onClick={() => void recordReview("changes_requested")}>수정 요청</button><button type="button" disabled={busy || !latestAssessment?.machine_passed || !attest.sources || !attest.claims || !attest.rights} onClick={() => void recordReview("editorial_review_passed")}>편집 검토 통과 기록</button></div><p>편집 검토 기록은 유지됩니다. Blogger 첫 공개 승인은 아래의 별도 승인 영역에서 정확한 원고 버전에 대해 처리합니다.</p></section>
          <ScheduledBloggerPublication detail={detail} selectedTargetId={publicationTargetId} setSelectedTargetId={setPublicationTargetId}
            actor={approvalActor} setActor={setApprovalActor} reason={approvalReason} setReason={setApprovalReason}
            busy={busy} onApprove={() => void approveFirstPublication()} onRefresh={() => void refreshScheduledPublication()} />
          {detail.item.generation_method === "manual_codex_import" && <section className="workspace-panel" id="manual-blogger-publication"><h3>수동 원고 Blogger 발행</h3>
            <p>예약 Auto와 분리된 수동 경로입니다. 요청은 현재 불변 버전과 대상 블로그에 고정되며, 서버의 사람 검토·게시 승인·권리·중복·운영 쓰기 게이트를 모두 통과해야 큐에 등록됩니다.</p>
            <p>Content Version: {String(latestVersion.content_version_id ?? "연결 없음")} · 원고 버전 {String(latestVersion.version_number ?? "—")} · 본문 SHA-256 {String((((detail.publication?.targets as Row[] | undefined) ?? []).find(target => String(target.id) === publicationTargetId)?.manual_publication as Row | undefined)?.body_sha256 ?? "계산·확인 불가")}</p>
            <label>수동 발행 대상 Blogger<select aria-label="수동 발행 대상 Blogger" value={publicationTargetId} onChange={event => setPublicationTargetId(event.target.value)}>
              <option value="">대상 선택</option>{((detail.publication?.targets as Row[] | undefined) ?? []).filter(target => target.active === true).map(target => <option key={String(target.id)} value={String(target.id)}>{String(target.display_name)} · {String(target.url)}</option>)}
            </select></label>
            {(() => { const selected = ((detail.publication?.targets as Row[] | undefined) ?? []).find(target => String(target.id) === publicationTargetId); const manual = selected?.manual_publication as Row | undefined; const blockers = (manual?.blockers as string[] | undefined) ?? []; return manual?.eligible === true ? <p className="quality-ok" role="status">현재 버전의 일반 수동 발행 게이트가 통과했습니다. 요청 전 대상과 해시를 다시 확인하세요.</p> : <div className="quality-held" role="status"><strong>현재 게시 불가 · 남은 조건</strong><ul>{blockers.length ? blockers.map(reason => <li key={reason}>{reason}</li>) : <li>수동 발행 상태를 확인할 수 없습니다.</li>}</ul></div>; })()}
            <button type="button" disabled={busy || !latestVersion.content_version_id || !publicationTargetId || (((detail.publication?.targets as Row[] | undefined) ?? []).find(target => String(target.id) === publicationTargetId)?.manual_publication as Row | undefined)?.eligible !== true} onClick={() => void submitManualPublication()}>현재 버전 공개 발행 요청</button>
          </section>}
          <section className="workspace-panel" id="import-publication"><h3>모의 게시</h3><p>실제 Blogger 요청이 아닌 테스트 시뮬레이션입니다. publish_ready=false는 유지됩니다.</p><button type="button" className="secondary-button" data-testid="mock-publish" disabled={busy || !publicationAllowed} onClick={() => void run(() => api("mock-publications", "POST", { version_id: latestVersion.id, idempotency_key: `import-${selectedId}-${String(latestVersion.content_sha256).slice(0,64)}`, scenario: "success", requested_by: reviewer }), "테스트 어댑터 결과를 기록했습니다. 실제 Blogger에는 변경이 없습니다.")}>모의 게시 시뮬레이션</button>{!publicationAllowed && <p role="status">현재 버전에 통과한 검사와 명시적 편집 검토 기록이 모두 있어야 모의 게시를 실행할 수 있습니다.</p>}{detail.mock_publications.map(attempt => <p key={String(attempt.id)}>모의 결과: {String(attempt.outcome)} · 모의 전용 · 외부 요청 0건</p>)}</section>
        </>}
        {detailTab === "history" && <section className="workspace-panel" id="import-history"><h3>버전 및 변경 이력</h3>{(detail.lineage_history ?? []).filter(version => String(version.import_id) !== String(detail.item.id)).map(version => <article className="history-card" key={String(version.import_version_id)}><strong>원고 계열 이전 버전 · v{String(version.version_number)} · {String(version.title)}</strong><p>{fmt(version.created_at)} · {String(version.author_label)} · {String(version.change_reason)}</p><details><summary>이전 원고 내용 보기</summary><pre>{String(version.body_markdown ?? "")}</pre></details></article>)}{detail.versions.map(version => <article className="history-card" key={String(version.id)}><strong>v{String(version.version_number)} · {String(version.title)}</strong><p>{fmt(version.created_at)} · {String(version.author_label)} · {String(version.change_reason)}</p>{version.id !== latestVersion.id && <button type="button" className="secondary-button" onClick={() => void openDetail(selectedId)}>최신 버전 새로고침</button>}</article>)}{detail.reviews.map(event => <article className="history-card" key={String(event.version_id) + String(event.created_at)}><strong>{statusNames[String(event.event_type)] ?? String(event.event_type)}</strong><p>{String(event.reviewer_label)} · {fmt(event.created_at)} · {String(event.reason)}</p></article>)}</section>}
      </div>
    </section></div>}
  </main>;
}

function ScheduledBloggerPublication({ detail, selectedTargetId, setSelectedTargetId, actor, setActor, reason, setReason, busy, onApprove, onRefresh }: {
  detail: Details; selectedTargetId: string; setSelectedTargetId: (value: string) => void;
  actor: string; setActor: (value: string) => void; reason: string; setReason: (value: string) => void;
  busy: boolean; onApprove: () => void; onRefresh: () => void;
}) {
  const publication = detail.publication ?? {};
  const targets = (publication.targets as Row[] | undefined) ?? [];
  const target = targets.find(item => String(item.id ?? "") === selectedTargetId);
  const blockers = (target?.approval_blockers as string[] | undefined) ?? [];
  const assessment = publication.assessment as Row | undefined;
  const evidence = publication.evidence_assessment as Row | undefined;
  const review = publication.editorial_review as Row | undefined;
  const jobs = (target?.jobs as Row[] | undefined) ?? [];
  const recordedApproval = target?.first_approval as Row | undefined;
  const scheduled = publication.generation_method === "chatgpt_scheduled_export";
  const isPublished = jobs.some(job => job.remote_status === "LIVE" && job.remote_verified_at && job.remote_post_id && job.remote_url);
  return <section className="workspace-panel" id="scheduled-blogger-publication" aria-labelledby="scheduled-blogger-publication-title" data-testid="scheduled-blogger-publication">
    <div className="section-heading"><div><h3 id="scheduled-blogger-publication-title">Blogger 공개 발행</h3><p>예약 원고의 최초 공개 승인은 원고 버전·본문 해시·대상 블로그에 결속됩니다. 승인 기록 후에도 Publication Worker가 게시 게이트를 다시 확인합니다.</p></div><button type="button" className="secondary-button" disabled={busy} onClick={onRefresh}>상태 새로고침</button></div>
    {publication.status_error ? <p role="alert" className="quality-held">{String(publication.status_error)}</p> : <>
      <dl className="publication-detail-status">
        <dt>예약 원고 여부</dt><dd>{scheduled ? "Codex 예약 Export" : `범위 밖 · ${String(publication.generation_method ?? "생성 출처 미확인")}`}</dd>
        <dt>편집 검토</dt><dd>{displayState(review?.event_type ?? detail.editorial_review_status)}</dd>
        <dt>기계 평가</dt><dd>{assessment?.machine_passed === true ? "최신 버전 통과" : "최신 버전 미통과 또는 기록 없음"}</dd>
        <dt>근거 평가</dt><dd>{displayState(evidence?.status)}{Array.isArray(evidence?.reasons) && evidence.reasons.length ? ` · ${(evidence.reasons as unknown[]).join(", ")}` : ""}</dd>
        <dt>예약 Auto</dt><dd>{publication.scheduled_auto_enabled === true ? "활성" : "비활성"}{publication.emergency_stopped === true ? " · 긴급 정지" : ""}</dd>
        <dt>원고 버전 / SHA-256</dt><dd>v{String(publication.version_number ?? "—")} · {String(publication.body_sha256 ?? "—")}</dd>
      </dl>
      {!scheduled && publication.content_version_id != null && <p className="quality-held">이 원고는 수동 가져오기 경로입니다. 예약 Auto의 최초 승인 API는 사용할 수 없습니다. <Link href={`/manuscripts?open_content_version_id=${encodeURIComponent(String(publication.content_version_id))}`}>일반 원고 검토·발행 상태 열기</Link></p>}
      {targets.length > 0 && <label>대상 Blogger<select aria-label="첫 공개 승인 대상 Blogger" value={selectedTargetId} onChange={event => setSelectedTargetId(event.target.value)}>
        {targets.map(item => <option key={String(item.id)} value={String(item.id)}>{String(item.display_name)} · {String(item.url)} · Blogger ID {String(item.blog_id ?? "미확인")}{item.in_scheduled_scope ? " · 예약 Auto 범위" : " · 범위 밖"}</option>)}
      </select></label>}
      {target ? <>
        <p>대상 상태: {target.active ? "활성" : "비활성"} · OAuth {String(target.oauth_status ?? "미확인")} · 예약 범위 {target.in_scheduled_scope ? "포함" : "미포함"} · 실제 쓰기 정책 {target.remote_write_policy_available ? "허용 확인" : "차단 또는 미확인"}</p>
        {recordedApproval && <p className="quality-ok" role="status">최초 공개 승인 기록됨 · {String(recordedApproval.actor_label)} · {fmt(recordedApproval.created_at)} · 이 승인만으로 Blogger 요청이 전송되지는 않습니다.</p>}
        {!recordedApproval && blockers.length > 0 && <div className="quality-held" role="status"><strong>승인·발행 차단 사유</strong><ul>{blockers.map(blocker => <li key={blocker}>{publicationBlockerNames[blocker] ?? blocker}</li>)}</ul></div>}
        {jobs.length > 0 && <div><h4>발행 작업</h4>{jobs.map(job => <article className="history-card" key={String(job.id)}><p>Job {String(job.id)} · {String(job.publication_state)} · {String(job.status)} · {job.simulation_only ? "Mock" : "실제 발행 경로"}</p>{job.remote_post_id != null && <p>Blogger postId: {String(job.remote_post_id)}</p>}{Boolean(job.remote_status === "LIVE" && job.remote_verified_at && job.remote_url) && <p><a href={String(job.remote_url)} target="_blank" rel="noopener noreferrer">실제 Blogger 게시 URL 열기 ↗</a></p>}{Boolean(job.remote_verified_at) && <p>원격 재검증 {fmt(job.remote_verified_at)}</p>}{job.published_at != null && <p>게시 시각 {fmt(job.published_at)}</p>}</article>)}</div>}
        {isPublished && <p className="quality-ok">원격 공개 게시 기록이 확인됐습니다.</p>}
        {!recordedApproval && <>
          <label>승인자 표시 이름<input value={actor} onChange={event => setActor(event.target.value)} minLength={2} maxLength={120} /></label>
          <label>첫 공개 승인 사유<input value={reason} onChange={event => setReason(event.target.value)} minLength={10} maxLength={2000} /></label>
          <button type="button" data-testid="scheduled-first-publication-approve" disabled={busy || target.can_record_first_approval !== true || actor.trim().length < 2 || reason.trim().length < 10} onClick={onApprove}>Blogger 첫 공개 승인 기록</button>
        </>}
      </> : <p className="empty-state">현재 언어의 Blogger 대상이 없거나 예약 발행 상태를 확인할 수 없습니다.</p>}
      <p>승인 버튼은 정확한 버전의 append-only 승인을 기록합니다. Blogger 공개 POST는 이 버튼에서 직접 실행하지 않고, 승인된 기존 발행 큐와 Publication Worker가 처리합니다. 외부 게시 URL은 원격 공개 상태가 확인된 경우에만 표시됩니다.</p>
    </>}
  </section>;
}

function QualityAssessmentPanel({ assessment }: { assessment: Row }) {
  const seoChecks = (Array.isArray(assessment.seo_checks) ? assessment.seo_checks : []) as Row[];
  const machine = assessment.machine_checks && typeof assessment.machine_checks === "object" ? assessment.machine_checks as Row : {};
  const gates = machine.checks && typeof machine.checks === "object" ? machine.checks as Row : {};
  const failedMachine = Object.entries(gates).filter(([, passed]) => passed === false).map(([key]) => key.replaceAll("_", " "));
  const groups = [
    ["통과", seoChecks.filter(check => check.status === "ready")],
    ["수정 필요", seoChecks.filter(check => check.status === "failed")],
    ["사람 검토 필요", seoChecks.filter(check => check.status === "review")],
    ["미측정", seoChecks.filter(check => check.status === "not_measured")],
  ] as const;
  return <>
    <p className={assessment.machine_passed ? "quality-ok" : "quality-held"}>{assessment.machine_passed ? "규칙 기계 검사 통과" : "기계 검사 보류"} · 이 결과는 사실의 의미적 정확성·권리·자연스러움을 보증하지 않습니다.</p>
    <p>기계 검사: {Object.values(gates).filter(value => value === true).length}/{Object.keys(gates).length} 통과</p>
    {failedMachine.length > 0 && <section><h4>수정 필요</h4><ul>{failedMachine.map(name => <li key={name}>{name}</li>)}</ul></section>}
    <div className="quality-check-groups">{groups.map(([label, checks]) => <section key={label}><h4>{label} <span>{checks.length}</span></h4>{checks.length ? <ul>{checks.map(check => <li key={String(check.key)}>{String(check.message)}</li>)}</ul> : <p>해당 상태 항목 없음</p>}</section>)}</div>
    <details><summary>개발자용 원시 검사 데이터</summary><pre>{JSON.stringify(assessment.machine_checks, null, 2)}</pre></details>
  </>;
}
