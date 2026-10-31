"use client";

import { useEffect, useState } from "react";

type ReviewItem = { id: string; issue_type: string; severity: string; description: string; resolved: boolean };
type Review = {
  id: string; publication_mode?: "draft" | "publish"; review_status: "pending" | "in_progress" | "completed"; review_notes: string;
  remote_url: string | null; remote_post_id: string; published_at: string; content_version_id: string;
  title: string; language_code: string; blog_url: string; open_item_count: number;
  high_count: number; review_items: ReviewItem[];
  claim_verification?: { verification_status: string }[];
  blog_name?: string; keyword?: string; codex_job_id?: string; import_id?: string;
  remote_status?: string; saved_at?: string; remote_published_at?: string; remote_updated_at?: string;
  remote_checked_at?: string; remote_check_error?: string;
};

const issueTypes = ["source", "number", "date", "exchange_rate", "translation", "copyright", "other"] as const;
const issueLabels: Record<string, string> = {
  source: "출처", number: "수치", date: "날짜", exchange_rate: "환율", translation: "번역", copyright: "권리", other: "기타",
};

export default function PostPublicationReviewPanel() {
  const [status, setStatus] = useState("pending");
  const [items, setItems] = useState<Review[]>([]);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [draft, setDraft] = useState<Record<string, string>>({});
  async function load() {
    setBusy(true); setError("");
    try {
      const response = await fetch(`/api/publications/post-publication-reviews?status=${status}`, { cache: "no-store" });
      const body = await response.json();
      if (!response.ok) throw new Error(String(body.detail ?? "게시 후 보완 목록을 불러오지 못했습니다."));
      setItems(body.items as Review[]);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "요청에 실패했습니다."); }
    finally { setBusy(false); }
  }
  useEffect(() => {
    let cancelled = false;
    void fetch(`/api/publications/post-publication-reviews?status=${status}`, { cache: "no-store" })
      .then(async (response) => {
        const body = await response.json();
        if (!response.ok) throw new Error(String(body.detail ?? "게시 후 보완 목록을 불러오지 못했습니다."));
        if (!cancelled) setItems(body.items as Review[]);
      })
      .catch((cause: unknown) => { if (!cancelled) setError(cause instanceof Error ? cause.message : "요청에 실패했습니다."); })
      .finally(() => { if (!cancelled) setBusy(false); });
    return () => { cancelled = true; };
  }, [status]);
  async function update(review: Review, patch: Record<string, unknown>) {
    setBusy(true); setError("");
    try {
      const response = await fetch(review.publication_mode === "draft" ? `/api/publications/jobs/${review.id}/draft-review` : `/api/publications/post-publication-reviews/${review.id}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(String(body.detail ?? "보완 상태를 저장하지 못했습니다."));
      await load();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "저장에 실패했습니다."); }
    finally { setBusy(false); }
  }
  async function addItem(review: Review, description: string, issueType: string, severity: string) {
    const value = description.trim();
    if (!value) return;
    setBusy(true); setError("");
    try {
      const response = await fetch(`/api/publications/post-publication-reviews/${review.id}/items`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ issue_type: issueType, severity, description: value, idempotency_key: `postreview-${crypto.randomUUID()}` }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(String(body.detail ?? "보완 항목을 저장하지 못했습니다."));
      setDraft((current) => ({ ...current, [`${review.id}:description`]: "" })); await load();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "저장에 실패했습니다."); }
    finally { setBusy(false); }
  }
  async function resolve(review: Review, item: ReviewItem) {
    setBusy(true); setError("");
    try {
      const response = await fetch(`/api/publications/post-publication-reviews/${review.id}/items/${item.id}/resolve`, { method: "POST" });
      const body = await response.json();
      if (!response.ok) throw new Error(String(body.detail ?? "보완 완료를 저장하지 못했습니다."));
      await load();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "저장에 실패했습니다."); }
    finally { setBusy(false); }
  }
  return <section className="workspace-panel publication-section post-review-panel" aria-labelledby="post-review-title">
    <div className="section-heading"><div><p className="eyebrow">원격 확인된 Blogger 초안 및 공개 게시물</p><h2 id="post-review-title">게시 후 보완 관리</h2><p>검토 상태와 편집 메모를 저장 이력에 연결합니다. 비공개 초안과 실제 공개 상태를 구분하며, 검토 완료 표시는 사용자의 확인 기록입니다.</p></div></div>
    <div className="post-review-toolbar" role="group" aria-label="보완 상태 필터">
      {[ ["pending", "보완 필요"], ["completed", "보완 완료"], ["all", "전체"] ].map(([key, label]) =>
        <button key={key} type="button" className={status === key ? "is-active" : "secondary-button"} aria-pressed={status === key} onClick={() => { setBusy(true); setError(""); setStatus(key); }}>{label}</button>)}
    </div>
    {error && <p className="quality-held" role="alert">{error}</p>}
    {busy && items.length === 0 ? <p className="empty-state">불러오는 중…</p> : items.length === 0 ? <p className="empty-state">원격 확인된 초안·게시물 중 이 필터에 해당하는 항목이 없습니다.</p> : <div className="post-review-list">
      {items.map((review) => <article className="post-review-card" key={review.id}>
        <p>{review.publication_mode === "draft" ? review.remote_status === "LIVE" ? "Draft → 사용자 직접 LIVE 공개 확인" : review.remote_status === "DRAFT" ? "Draft 모드 · 비공개 초안 저장 이력" : "원격 조회 확인 필요 · 기존 초안 저장 이력 보존" : "Blogger LIVE 공개 게시물"}</p>
        {review.blog_name && <p>{review.blog_name} · {review.keyword} · Codex Job {review.codex_job_id} · Import {review.import_id}</p>}
        {review.publication_mode === "draft" && <p>초안 저장: {review.saved_at} · 공개 시각: {review.remote_published_at??"공개 확인 없음"} · 원격 수정: {review.remote_updated_at??"정보 없음"} · 상태 조회: {review.remote_checked_at??"저장 시 확인"}{review.remote_check_error&&` · 조회 오류 ${review.remote_check_error} (삭제로 단정하지 않음)`}</p>}
        {review.publication_mode === "draft" && <button type="button" className="secondary-button" disabled={busy} onClick={() => {
          setBusy(true);
          void fetch(`/api/publications/jobs/${review.id}/sync-draft`, { method: "POST" }).then(async response => {
            if (!response.ok) throw new Error(`원격 상태 조회 실패 (HTTP ${response.status})`);
            await load();
          }).catch(cause => setError(String(cause))).finally(() => setBusy(false));
        }}>Blogger Draft/LIVE 상태 재조회</button>}
        <header><div><span className={review.high_count ? "post-review-risk" : "post-review-status"}>{review.high_count ? `높은 중요도 ${review.high_count}` : review.review_status === "completed" ? "보완 완료" : `열린 항목 ${review.open_item_count}`}</span><h3>{review.title}</h3><p>{review.language_code} · {review.blog_url} · postId {review.remote_post_id}</p></div>{review.remote_url && <a href={review.remote_url} target="_blank" rel="noreferrer">Blogger 글 열기</a>}</header>
        <p>검토 상태: {review.review_status === "completed" ? "사용자 검토 완료" : review.review_status === "in_progress" ? "수정 필요" : "검토 전"} · {review.publication_mode === "draft" ? "초안 저장 시각" : "발행 시각"}: {new Intl.DateTimeFormat("ko-KR", { dateStyle: "short", timeStyle: "short", timeZone: "Asia/Seoul" }).format(new Date(review.published_at))}</p>
        <p>Claim {review.claim_verification?.length ?? 0}개 · 미검증 {review.claim_verification?.filter(claim => claim.verification_status === "unverified").length ?? 0}개. 검토 완료 표시는 사용자의 확인 기록이며 Blogger 수정 여부를 자동 확인한 결과는 아닙니다.</p>
        {review.review_notes && <p>{review.review_notes}</p>}
        <ul>{review.review_items.map((item) => <li key={item.id} className={item.resolved ? "is-resolved" : ""}><span>{issueLabels[item.issue_type] ?? item.issue_type} · {item.severity}</span><p>{item.description}</p>{!item.resolved && <button type="button" className="secondary-button" disabled={busy} onClick={() => void resolve(review, item)}>보완 완료</button>}</li>)}</ul>
        <div className="post-review-actions"><label>보완 메모<textarea maxLength={4000} value={draft[review.id] ?? review.review_notes} onChange={(event) => setDraft((current) => ({ ...current, [review.id]: event.target.value }))} /></label>
          <div><button type="button" className="secondary-button" disabled={busy} onClick={() => void update(review, { review_status: "in_progress", review_notes: draft[review.id] ?? review.review_notes })}>수정 필요</button><button type="button" disabled={busy} onClick={() => void update(review, { review_status: "completed", review_notes: draft[review.id] ?? review.review_notes })}>사용자 검토 완료</button></div>
          <div className="post-review-add"><label htmlFor={`review-item-${review.id}`}>추가 메모 항목</label><select aria-label="항목 유형" value={draft[`${review.id}:type`] ?? "source"} onChange={(event) => setDraft((current) => ({ ...current, [`${review.id}:type`]: event.target.value }))}>{issueTypes.map((type) => <option key={type} value={type}>{issueLabels[type]}</option>)}</select><select aria-label="중요도" value={draft[`${review.id}:severity`] ?? "low"} onChange={(event) => setDraft((current) => ({ ...current, [`${review.id}:severity`]: event.target.value }))}><option value="low">낮음</option><option value="medium">보통</option><option value="high">높음</option></select><input id={`review-item-${review.id}`} value={draft[`${review.id}:description`] ?? ""} onChange={(event) => setDraft((current) => ({ ...current, [`${review.id}:description`]: event.target.value }))} placeholder="추가로 확인하거나 보완할 내용"/><button type="button" className="secondary-button" disabled={busy || review.publication_mode === "draft" || !draft[`${review.id}:description`]?.trim()} onClick={() => void addItem(review, draft[`${review.id}:description`] ?? "", draft[`${review.id}:type`] ?? "source", draft[`${review.id}:severity`] ?? "low")}>항목 추가</button></div>
        </div>
      </article>)}
    </div>}
  </section>;
}
