"use client";

import { useEffect, useState } from "react";

type Policy = {
  id: string;
  enabled: boolean;
  publication_mode: "draft" | "publish";
  allowed_geos: string[];
  daily_limit: number | null;
  created_at: string;
};
type Blog = {
  id: string;
  display_name: string;
  blog_id: string | null;
  url: string;
  language_code: string;
  active: boolean;
  oauth_status?: string;
  last_completed_at?: string | null;
  public_approval_present?: boolean;
  authoring?: { job_id: string | null; request_state: string; state: string | null; error_code: string | null; keyword: string; import_id: string | null } | null;
  delivery?: { id: string; publication_state: string; status: string; last_error_category: string | null; available_at: string; remote_post_id: string | null } | null;
  activation_blockers?: string[];
  draft_activation_blockers?: string[];
  mapped_geos: string[];
  policy: Policy | null;
};
type Backoff={active:boolean;error_code:string;not_before:string;basis:string};
type State = { policies: Blog[]; supported_geographies: string[]; emergency_stopped?: boolean; codex_backoff?: Backoff|null; blogger_backoff?: Backoff|null };
type Draft = { enabled: boolean; publication_mode: "draft" | "publish"; geos: string[]; reason: string; confirmation: string };
const blockerNames: Record<string, string> = {
  country_mapping_required: "수집 국가 매핑 필요",
  blogger_write_oauth_required: "Blogger OAuth 쓰기 권한 확인 필요",
  actual_write_verification_required: "실제 쓰기 성공 이력 확인 필요",
  fresh_blog_identity_verification_required: "현재 블로그 연결 확인 필요",
  authenticated_public_publish_approval_required: "관리자 자동 공개 승인 필요",
};

export default function TrendsPublicationSettings() {
  const [state, setState] = useState<State | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [actor, setActor] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState("");

  async function load() {
    const response = await fetch("/api/publications/trends-auto-policy", { cache: "no-store" });
    if (!response.ok) throw new Error(`Trends 발행 정책 조회 실패 (HTTP ${response.status})`);
    const data = await response.json() as State;
    setState(data);
    setDrafts(Object.fromEntries(data.policies.map(blog => [blog.id, {
      enabled: blog.policy?.enabled ?? false,
      publication_mode: blog.policy?.publication_mode ?? "draft",
      geos: blog.policy?.allowed_geos ?? [],
      reason: "",
      confirmation: "",
    }])));
  }

  useEffect(() => {
    let disposed=false, pending=false;
    const controller=new AbortController();
    async function refresh() {
      if (pending || disposed || document.visibilityState!=="visible") return;
      pending=true;
      try {
        const response=await fetch("/api/publications/trends-auto-policy",{cache:"no-store",signal:controller.signal});
        if(!response.ok) throw new Error(`Trends 상태 조회 HTTP ${response.status}`);
        const data=await response.json() as State;
        if(!disposed){setState(data);setDrafts(current=>Object.keys(current).length ? current : Object.fromEntries(data.policies.map(blog=>[blog.id,{
          enabled:blog.policy?.enabled??false,publication_mode:blog.policy?.publication_mode??"draft",geos:blog.policy?.allowed_geos??[],reason:"",confirmation:"",
        }])));}
      }catch(error){if(!controller.signal.aborted)setMessage(String(error));}finally{pending=false;}
    }
    void refresh();const timer=setInterval(()=>void refresh(),10000);
    const visible=()=>void refresh();document.addEventListener("visibilitychange",visible);
    return()=>{disposed=true;controller.abort();clearInterval(timer);document.removeEventListener("visibilitychange",visible);};
  }, []);

  function patch(blogId: string, value: Partial<Draft>) {
    setDrafts(current => ({ ...current, [blogId]: { ...current[blogId], ...value } }));
  }

  async function verify(blog: Blog) {
    if (busy) return;
    setBusy(blog.id); setMessage("");
    try {
      const response = await fetch("/api/publications/trends-auto/verify-connections", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ blog_ids: [blog.id] }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail ?? `HTTP ${response.status}`);
      await load();
      setMessage(result.results?.[0]?.write_verified ? "기존 실제 LIVE 이력과 현재 연결을 확인했습니다." : "기존 LIVE 쓰기 검증 근거가 부족합니다. 정책은 활성화되지 않았습니다.");
    } catch (error) { setMessage(String(error)); }
    finally { setBusy(null); }
  }

  async function save(blog: Blog) {
    const draft = drafts[blog.id];
    if (!draft || busy) return;
    setBusy(blog.id);
    setMessage("");
    try {
      const confirmation = draft.enabled ? "ENABLE TRENDS AUTO PUBLICATION" : "STOP TRENDS AUTO PUBLICATION";
      if (draft.publication_mode === "publish" && draft.confirmation !== confirmation) throw new Error(`확인 문구를 정확히 입력하세요: ${confirmation}`);
      const response = await fetch("/api/publications/trends-auto-policy", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          blog_id: blog.id, enabled: draft.enabled, publication_mode: draft.publication_mode,
          allowed_geos: draft.geos, daily_limit: null,
          actor_label: actor, reason: draft.reason,
          confirmation: draft.publication_mode === "publish" ? confirmation : "", idempotency_key: crypto.randomUUID(),
        }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail ?? result.error ?? `HTTP ${response.status}`);
      await load();
      setMessage(`${blog.display_name}: 설정 변경 감사 기록을 추가했습니다.`);
    } catch (error) {
      setMessage(String(error));
    } finally {
      setBusy(null);
    }
  }

  return <section className="workspace-panel" aria-labelledby="trends-auto-policy-heading">
    <h2 id="trends-auto-policy-heading">Google Trends 과거 발행 정책 (자동 쓰기 중지)</h2>
    <p>아래 값은 감사용으로 보존된 이전 설정입니다. ON 또는 Draft 표시가 있어도 현재 자동 실행 권한은 없습니다.</p>
    <p>예약 Auto와 별도인 Trends 전용 정책입니다. 기본값은 비공개 초안 저장이며 공개 승인이 필요하지 않습니다. 즉시 공개는 관리자의 명시적 승인이 필요합니다. 미검증 상태는 보존하고 Blogger 매핑·중복·긴급 정지·Worker 상태를 확인합니다.</p>
    <label>설정 변경자<input value={actor} minLength={2} maxLength={120} onChange={event => setActor(event.target.value)} /></label>
    {!state && !message && <p role="status">정책을 불러오는 중입니다.</p>}
    {state?.policies.map(blog => {
      const draft = drafts[blog.id];
      if (!draft) return null;
      const confirmation = draft.enabled ? "ENABLE TRENDS AUTO PUBLICATION" : "STOP TRENDS AUTO PUBLICATION";
      return <fieldset className="trend-blog-geo" key={blog.id} disabled>
        <legend>{blog.display_name} · {blog.language_code}</legend>
        <div role="group" aria-label={`${blog.display_name} 발행 방식`}>
          <label><input type="radio" name={`mode-${blog.id}`} checked={draft.publication_mode === "draft"} onChange={() => patch(blog.id, { publication_mode: "draft", confirmation: "" })} />임시발행(비공개 초안 저장) · 기본</label>
          <label><input type="radio" name={`mode-${blog.id}`} checked={draft.publication_mode === "publish"} onChange={() => patch(blog.id, { publication_mode: "publish", confirmation: "" })} />즉시 공개 발행 · 관리자 승인</label>
        </div>
        <p>{draft.publication_mode === "draft" ? "공개 승인 없이 비공개 초안을 저장합니다. 이후 Blogger에서 직접 수정·공개할 수 있습니다." : "저장 시 이 블로그와 선택 국가의 이후 신규 원고 자동 공개를 명시적으로 승인합니다."}</p>
        <button type="button" className="button button-secondary" disabled={busy !== null || !blog.active || !blog.mapped_geos.length} onClick={() => void verify(blog)}>현재 연결·기존 LIVE 쓰기 이력 확인</button>
        <p>{blog.url} · Blogger ID: {blog.blog_id ?? "미확인"}</p>
        <p>이후 새 수집 회차에 적용되며 기존 Job의 발행 방식은 바뀌지 않습니다. 기본 안전·중복·쓰기 간격 검사를 유지하고 미검증 항목은 직접 검토합니다.</p>
        <p>{(draft.publication_mode === "draft" ? blog.draft_activation_blockers : blog.activation_blockers)?.length ? `활성화 준비: ${(draft.publication_mode === "draft" ? blog.draft_activation_blockers : blog.activation_blockers)!.map(code => blockerNames[code] ?? code).join(", ")}` : "활성화 조건 확인됨"}</p>
        <p>상태: {blog.policy?.enabled ? "활성" : "비활성"} · 연결된 수집 지역: {blog.mapped_geos.length ? blog.mapped_geos.join(", ") : "없음"}</p>
        <p>OAuth: {blog.oauth_status === "connected" ? "연결됨" : "연결 확인 필요"} · 공개 발행 승인: {blog.public_approval_present ? "기록 있음" : "미승인 (Draft에 불필요)"}</p>
        <p>긴급 중지: {state.emergency_stopped ? "ON · Blogger 쓰기 중지" : "OFF"} · <a href="/publishing">발행 관리에서 긴급 중지 관리</a></p>
        <p>마지막 정상 처리: {blog.last_completed_at ? new Intl.DateTimeFormat("ko-KR", { dateStyle: "short", timeStyle: "medium", timeZone: "Asia/Seoul" }).format(new Date(blog.last_completed_at)) : "처리 이력 없음"}</p>
        <p>원고 작성: {state.codex_backoff?.active ? `Codex 사용량·용량 대기 · ${state.codex_backoff.error_code} · 로컬 재확인 가능 ${state.codex_backoff.not_before} (한도 초기화 시각 아님)` : blog.authoring ? ({queued:"Codex 작성 대기",researching:"Codex 웹 조사 중",writing:"Codex 작성 중",validating:"JSON 검증 중",import_pending:"Import 대기",imported_review:"Import 완료",failed:"작성 실패",cancelled:"회차 만료·취소"} as Record<string,string>)[blog.authoring.state??""]??"작성 요청 대기" : "후보·작성 Job 없음"}</p>
        {blog.authoring && <p>{blog.authoring.keyword} · Codex Job {blog.authoring.job_id??"미생성"} · {blog.authoring.error_code??""}</p>}
        <p>최근 전달: {state.blogger_backoff?.active && blog.policy?.enabled ? `Google Blogger 외부 제한 대기 · ${state.blogger_backoff.error_code} · 로컬 재확인 가능 ${state.blogger_backoff.not_before} (제한 해제 시각 아님)` : blog.delivery ? `${({draft_saved:"Blogger 초안 저장 성공",publication_queued:"Draft/Publish Job 대기",publishing:"Blogger 처리 중",published:"원격 LIVE 확인",publication_failed:"발행 실패·보류"} as Record<string,string>)[blog.delivery.publication_state]??blog.delivery.publication_state} · ${blog.delivery.last_error_category??"오류 없음"} · Job ${blog.delivery.id}` : "Publishing Job 없음"}</p>
        <label><input type="checkbox" checked={draft.enabled} onChange={event => patch(blog.id, { enabled: event.target.checked, confirmation: "" })} /> Trends 자동 발행 허용</label>
        <div className="trend-geo-options">{blog.mapped_geos.map(geo => <label key={geo}>
          <input type="checkbox" checked={draft.geos.includes(geo)} onChange={event => patch(blog.id, {
            geos: event.target.checked ? [...draft.geos, geo] : draft.geos.filter(value => value !== geo), confirmation: "",
          })} />{geo}
        </label>)}</div>
        <p>발행량 상한: 무제한 (검증·중복 방지·최소 발행 간격은 계속 적용)</p>
        <label>변경 사유<input minLength={10} maxLength={2000} value={draft.reason} onChange={event => patch(blog.id, { reason: event.target.value, confirmation: "" })} /></label>
        {draft.publication_mode === "publish" && <label>공개 발행 명시적 확인 문구<input value={draft.confirmation} placeholder={confirmation} onChange={event => patch(blog.id, { confirmation: event.target.value })} /></label>}
        <button type="button" className="button button-secondary" disabled={busy !== null || !blog.active || actor.trim().length < 2 || draft.reason.trim().length < 10 || (draft.publication_mode === "publish" && draft.confirmation !== confirmation) || (draft.enabled && (!draft.geos.length || !blog.mapped_geos.length))} onClick={() => void save(blog)}>
          {busy === blog.id ? "저장 중…" : "정책 변경 기록"}
        </button>
        {blog.policy && <small>마지막 변경: {new Intl.DateTimeFormat("ko-KR", { dateStyle: "short", timeStyle: "short", timeZone: "Asia/Seoul" }).format(new Date(blog.policy.created_at))} · 발행량 상한 {blog.policy.daily_limit === null ? "무제한" : `${blog.policy.daily_limit}건`}</small>}
      </fieldset>;
    })}
    {message && <p role="status">{message}</p>}
  </section>;
}
