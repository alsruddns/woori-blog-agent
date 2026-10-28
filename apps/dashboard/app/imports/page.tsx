"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";

type ImportRow = {
  id: string; external_content_id: string; event_group_id: string; language_code: string;
  source_region: string; category: string; title: string; content_sha256: string;
  state: string; received_at: string; generation_method: string; model_name: string | null;
};
type Detail = { item: Record<string, unknown>; events: Array<Record<string, unknown>>; publish_ready: false };

const example = {
  schema_version: "1.0", content_id: "external-article-2026-001", event_group_id: "event-group-2026-001",
  research_package_id: null, parent_content_id: null, relation: "original", source_region: "US", language_code: "en",
  target_audiences: [{ language_code: "en", target_region: "US", reader_relevance_reason: "The policy directly changes reporting requirements for US readers." }],
  title: "A reviewed, evidence-linked article title", body_markdown: "## Main point\n\nReplace this example with the complete article body and source-linked discussion. Explain the verified facts, why they matter, and the implications for the selected readers without adding unsupported claims.",
  category: "policy", google_trends_based: false, source_ids: ["source-1"],
  sources: [{ source_id: "source-1", title: "Official source document", organization: "Example agency", url: "https://example.gov/report", published_at: "2026-10-20T00:00:00Z", observed_at: "2026-10-28T00:00:00Z", language_code: "en", source_type: "government", rights_status: "quotation_review_required", rights_note: "Review quotation and reuse conditions before publication." }],
  claims: [{ claim_id: "claim-1", claim: "A specific claim stated in the source", source_ids: ["source-1"], evidence_excerpt: "Exact short passage supporting this claim.", verification_status: "unverified", factual_state: "unverified" }],
  fact_checked_at: "2026-10-28T00:00:00Z", seo: { search_intent: "Understand the policy change", primary_terms: ["policy change"], related_terms: [], seo_title: "What the policy change means", search_description: "An evidence-linked explanation of the policy change, its scope, and what remains unconfirmed.", core_question: "What changed?", core_answer: "The imported article explains the documented change and its verified scope." },
  blogger_labels: [], generation_method: "manual_codex_import", model_name: null, generated_at: "2026-10-28T00:00:00Z", created_by: "Editorial Desk",
};

export default function ContentImportsPage() {
  const [items, setItems] = useState<ImportRow[]>([]);
  const [json, setJson] = useState("");
  const [submitter, setSubmitter] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [detail, setDetail] = useState<Detail | null>(null);
  const refresh = useCallback(async () => {
    try {
      const response = await fetch("/api/research/content-imports", { cache: "no-store" });
      const data = await response.json();
      if (!response.ok) throw new Error("가져온 원고 대기열을 불러오지 못했습니다. Migration 045 적용 여부를 확인하세요.");
      setItems(data.items as ImportRow[]);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "가져온 원고 목록을 불러오지 못했습니다."); }
  }, []);
  useEffect(() => { const timer = window.setTimeout(() => void refresh(), 0); return () => window.clearTimeout(timer); }, [refresh]);
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setBusy(true); setNotice(""); setError("");
    try {
      const item = JSON.parse(json) as unknown;
      const response = await fetch("/api/research/content-imports", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ submitted_by: submitter, item }) });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "규격 검증에 실패했습니다. 필수 필드와 출처 연결을 확인하세요.");
      setNotice(data.duplicate ? "같은 외부 원고를 이미 가져왔습니다. 기존 대기 기록을 재사용했습니다." : "원고를 검증 대기열에 저장했습니다. 사람의 근거·권리·문체 검토가 필요합니다.");
      await refresh();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "JSON을 읽거나 저장하지 못했습니다."); }
    finally { setBusy(false); }
  };
  const open = async (id: string) => {
    setError("");
    try { const response = await fetch(`/api/research/content-imports/${id}`, { cache: "no-store" }); const data = await response.json(); if (!response.ok) throw new Error("원고 상세를 불러오지 못했습니다."); setDetail(data as Detail); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "원고 상세를 불러오지 못했습니다."); }
  };
  return <main className="workspace-main import-workspace">
    <div className="page-heading"><div><p className="eyebrow">외부 작성 원고 · 수동 전달</p><h1>원고 가져오기</h1><p>GPT 예약 작업, Codex 등에서 내보낸 구조화 원고를 검증 대기열에 보관합니다. 가져오기는 발행 승인이나 원고 품질 통과를 의미하지 않습니다.</p></div></div>
    <div className="quality-held"><strong>현재 상태: 사람 검토 대기 전용</strong><p>AI 생성 Provider와 공식 자동 파일 전달 연결은 구성되어 있지 않습니다. 가져온 Markdown은 신뢰하지 않는 입력으로 저장하며 원문 자료를 자동으로 가져오지 않습니다. Blogger 쓰기, Auto 발행, publish_ready 전환은 수행하지 않습니다.</p></div>
    <section className="workspace-panel import-panel"><h2>구조화 원고 가져오기</h2><p>교환 형식: <code>woori-content-import/1.0</code>. 필수 필드와 모든 주장·출처 연결을 검증합니다.</p>
      <button type="button" className="secondary-button" onClick={() => setJson(JSON.stringify(example, null, 2))}>예시 형식 불러오기</button>
      <form onSubmit={submit} className="import-form"><label>제출자<input required minLength={2} maxLength={100} value={submitter} onChange={event => setSubmitter(event.target.value)} /></label><label className="import-json-label">원고 JSON<textarea required maxLength={150000} spellCheck={false} value={json} onChange={event => setJson(event.target.value)} placeholder="규격에 맞는 JSON을 붙여 넣으세요." /></label><button disabled={busy || json.length === 0 || submitter.trim().length < 2}>{busy ? "검증 및 저장 중…" : "검증 대기열에 가져오기"}</button></form>
      {notice && <p role="status" className="import-notice">{notice}</p>}{error && <p role="alert" className="quality-held">{error}</p>}
    </section>
    <section className="workspace-panel"><div className="section-heading"><div><h2>가져온 원고</h2><p>{items.length}건 · 본문 수정과 게시 전 사람 검토가 필요합니다.</p></div><button className="secondary-button" onClick={() => void refresh()}>새로고침</button></div>
      {items.length ? <div className="publication-table-scroll"><table><thead><tr><th>제목</th><th>분야</th><th>언어</th><th>수집 지역</th><th>상태</th><th>수신 시각</th></tr></thead><tbody>{items.map(item => <tr key={item.id}><td><button className="import-title" onClick={() => void open(item.id)}>{item.title}</button><small>{item.external_content_id}</small></td><td>{item.category}</td><td>{item.language_code}</td><td>{item.source_region}</td><td>사람 검토 대기</td><td>{new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Seoul" }).format(new Date(item.received_at))}</td></tr>)}</tbody></table></div> : <p className="empty-state">가져온 원고가 없습니다. 외부 작업에서 원고를 내보낸 뒤 JSON 형식으로 가져올 수 있습니다.</p>}
    </section>
    {detail && <section className="workspace-panel import-detail"><div className="section-heading"><h2>{String(detail.item.title ?? "가져온 원고")}</h2><button className="secondary-button" onClick={() => setDetail(null)}>닫기</button></div><dl className="data-list"><dt>상태</dt><dd>사람 검토 대기 · publish_ready=false</dd><dt>언어 / 분야</dt><dd>{String(detail.item.language_code)} / {String(detail.item.category)}</dd><dt>사건 그룹</dt><dd>{String(detail.item.event_group_id)}</dd><dt>출처</dt><dd>{Array.isArray(detail.item.sources) ? detail.item.sources.length : 0}건 · 원문 자동 조회 안 함</dd><dt>주장 연결</dt><dd>{Array.isArray(detail.item.claims) ? detail.item.claims.length : 0}건</dd></dl><h3>본문 Markdown</h3><pre>{String(detail.item.body_markdown ?? "")}</pre><h3>근거·권리 검토</h3><pre>{JSON.stringify({ sources: detail.item.sources, claims: detail.item.claims, seo_metadata: detail.item.seo_metadata }, null, 2)}</pre><p>이 대기열은 원고 계보와 검토 자료를 보존합니다. 승인 후 정식 원고 버전으로 승격하고 게시하려면 기존 근거·편집 검토·승인 절차에서 별도 구현/승인이 필요합니다.</p></section>}
  </main>;
}
