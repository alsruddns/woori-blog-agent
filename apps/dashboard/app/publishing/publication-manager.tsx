"use client";

import { useState } from "react";
import PostPublicationReviewPanel from "./post-publication-review-panel";

type Item = {
  id: string; content_version_id: string; group_id?: string; title: string; language_code: string;
  blog_id: string; blog_name?: string; url: string; topic?: string | null; source_names?: string | null;
  status: string; quality_status?: string | null; eligibility_reasons?: string[];
  has_publishing_job?: boolean; publishing_job_id?: string | null;
  next_publish_at?: string | null; created_at?: string | null; remote_url?: string | null;
  remote_post_id?: string | null; remote_status?: string | null; remote_verified_at?: string | null;
  simulation_only?: boolean; adapter_type?: string; evaluation_id?: string | null;
  import_id?: string | null; generation_method?: string | null; google_trends_based?: boolean;
  auto_publication_failure?: boolean; failure_stage?: string | null; failure_reason_code?: string | null;
  manual_publication_available?: boolean; retry_count?: number;
};
type ModeSetting = { scope_type: string; scope_key: string; configured_mode: string; daily_auto_limit: number; minimum_interval_minutes: number; allowed_start_hour?:number; allowed_end_hour?:number; timezone?:string; allowed_categories?:string[]; excluded_topics?:string[]; max_source_age_hours?:number; retry_limit?:number };
export type PublicationData = {
  candidates: Item[]; items?: Item[]; view?: string; summary?: Record<string, number>; total_count?: number;
  page?: number; page_size?: number; page_count?: number; jobs: Array<Record<string, unknown>>;
  worker: { process_id: number; status: string; last_seen_at: string } | null; queued_mock_jobs: number;
  queued_confirmed_private_drafts?: number; actual_published_count?: number; real_writes_enabled: boolean;
  publish_ready_enabled: false; adapter_available: string;
  mode_policy: { migration_required: boolean; default_mode: string; settings: ModeSetting[];
    languages: { code: string; display_name: string; active: boolean }[];
    blogs: { id: string; language_code: string; url: string; display_name: string; active: boolean }[];
    emergency_stopped: boolean; operations_auto_approved: false; live_auto_enabled: boolean; real_writes_enabled: boolean;
    scoped_write_capability?: { scheduled_auto?: boolean; manual_confirmed?: boolean; reason?: string | null };
    publication_worker?: { execution_mode?: string | null; status?: string; last_seen_at?: string } | null;
    scheduled_auto_policy?: { enabled: boolean;
      policy_event?: { id?: number; action?: string; approved_blog_ids?: string[]; daily_limit?: number; actor_label?: string; reason?: string; created_at?: string } | null;
      first_publication_approval_required?: false;
      policy_history?: Array<{ id: number; action: string; approved_blog_ids: string[]; daily_limit: number; actor_label: string; reason: string; created_at: string }>;
      latest_connection_check?: { created_at: string; payload?: { results?: Array<{ blog_record_id: string; verified: boolean; remote_blog_id?: string; reason?: string }> } } | null;
      trends_lane_affected: false } };
  auto_candidate_count: number; auto_runtime_status: string;
  operational_limits?: {timezone:string;global_daily:number;language_daily:Record<string,number|null>;language_hourly:Record<string,number>;english_daily_policy:string;blog_minimum_interval_minutes:number;account_minimum_interval_minutes:number};
};
const tabs = [["queue", "발행 대기"], ["review", "검토 필요"], ["published", "게시 완료"], ["held", "실패·보류"], ["auto_failure", "자동발행실패"]] as const;
const languageLabel = (code: string) => ({ko:"한국어",en:"영어",ja:"일본어","zh-CN":"중국어 간체"}[code] ?? code);
const statusLabel = (status: string) => ({review_needed:"검토 필요",queueable:"발행 자격 충족 · Job 없음",queued:"Worker 처리 대기",publishing:"게시 중",published:"게시 완료",quality_held:"품질 보류",publication_blocked:"게시 차단",failed:"실패",uncertain:"결과 확인 필요",auto_publication_failed:"자동발행실패"}[status] ?? status);
const reasonLabel = (reason: string) => ({
  quality_evaluation_missing:"품질 검사 기록 없음", quality_not_passed:"품질 검사 통과 필요",
  editorial_source_rights_and_publication_review_required:"근거·권리·승인 확인 필요",
  automatic_publication_policy_inactive:"자동 발행 정책 비활성",
  remote_duplicate_found:"같은 Blogger 게시물 확인됨", remote_duplicate_check_unknown:"중복 여부 확인 필요",
  not_a_scheduled_export:"예약 Export 원고가 아님", scheduled_sanitized_revision_required:"원고 본문 보정 필요",
  no_supported_body_after_sanitization:"검증된 본문을 구성할 수 없음", scheduled_origin_target_mismatch:"예약 작업의 대상 블로그와 다름",
  blog_or_oauth_not_verified:"Blogger 연결 또는 OAuth 확인 필요", scheduled_language_blog_mismatch:"원고 언어와 Blogger 언어가 다름",
  same_event_already_queued_or_published:"같은 사건이 이미 대기 또는 게시됨", scheduled_import_not_found:"예약 원고 Import 기록 없음",
  source_evidence_missing:"출처 근거 확인 필요", claim_evidence_mismatch:"주장과 근거 연결 확인 필요",
  scheduled_version_hash_invalid:"원고 버전 해시 확인 필요", claims_or_sources_missing:"주장 또는 출처 자료 부족",
  source_live_verification_missing:"출처 원문 확인 필요", source_live_verification_mismatch:"출처 원문과 등록 정보 불일치",
  source_evidence_spans_missing:"출처 근거 구간 부족", claim_schema_invalid:"주장 근거 형식 오류",
  claim_evidence_incomplete:"주장별 근거 연결 미완료", claim_span_not_found_in_live_source_evidence:"주장 근거가 확인된 원문에 없음",
  claim_contains_unsupported_number_or_unit:"검증되지 않은 수치 또는 단위 포함", independent_corroboration_missing:"독립 교차 확인 필요",
  semantic_claim_review_required:"핵심 주장 의미 확인 필요", source_rights_not_machine_verified:"출처 이용 권리 확인 필요",
  uncited_paragraph:"출처 연결이 없는 본문 문단", source_has_unverified_claim:"출처에서 확인되지 않은 주장 포함",
  source_excerpt_copy_removed:"원문과 유사한 문장을 제외하고 보정 필요", embedded_image_removed:"이미지 제외 후 확인 필요",
  direct_quote_removed:"직접 인용 제외 후 확인 필요",
  daily_publication_limit:"오늘 발행 한도 도달", publication_policy_missing:"발행 대상 정책 없음",
  scheduled_auto_policy_not_active_for_blog:"대상 블로그의 예약 Auto 범위 밖",
  blog_oauth_mapping_changed:"Blogger 연결이 변경됨",
  separate_public_publish_operations_approval_required:"실제 Blogger 쓰기 운영 승인 필요",
  global_emergency_stop_or_policy_missing:"긴급 정지 또는 운영 정책 확인 필요",
  published_readback_mismatch:"게시 후 Blogger 확인 불일치", published_record_conflict:"게시 기록 충돌",
  blogger_write_scope_required:"Blogger 쓰기 권한 없음", invalid_grant:"Google 인증 갱신 필요",
  transport_error:"Blogger 연결 오류", timeout:"Blogger 응답 시간 초과",
}[reason] ?? reason.replaceAll("_", " "));
const kst = (value?: string | null) => value ? new Intl.DateTimeFormat("ko-KR", { timeZone:"Asia/Seoul", dateStyle:"medium", timeStyle:"short" }).format(new Date(value)) + " KST" : "기록 없음";

export default function PublicationManager({ initial }: { initial: PublicationData }) {
  const [data, setData] = useState(initial);
  const initialGlobalMode=initial.mode_policy.settings.find(item=>item.scope_type==="global"&&!item.scope_key);
  const [view, setView] = useState<(typeof tabs)[number][0]>((initial.view as (typeof tabs)[number][0]) || "review");
  const [query, setQuery] = useState(""); const [language, setLanguage] = useState(""); const [blog, setBlog] = useState("");
  const [page, setPage] = useState(1); const [loading, setLoading] = useState(false); const [error, setError] = useState("");
  const [activeTab, setActiveTab] = useState<string>(view);
  const [emergencyBusy, setEmergencyBusy] = useState(false);
  const [notice,setNotice]=useState("");
  const [scheduledBlogs,setScheduledBlogs]=useState<string[]>([]);
  const [scheduledActor,setScheduledActor]=useState("운영자");
  const [scheduledBusy,setScheduledBusy]=useState(false);
  const [scheduledConnectionBusy,setScheduledConnectionBusy]=useState(false);
  const [scopeType,setScopeType]=useState<"global"|"language"|"blog">("global");
  const [scopeKey,setScopeKey]=useState("");
  const [selectedMode,setSelectedMode]=useState<"manual"|"auto">((initialGlobalMode?.configured_mode as "manual"|"auto")??"manual");
  const [dailyLimit,setDailyLimit]=useState(initialGlobalMode?.daily_auto_limit??1); const [minimumInterval,setMinimumInterval]=useState(initialGlobalMode?.minimum_interval_minutes??1440);
  const [startHour,setStartHour]=useState(initialGlobalMode?.allowed_start_hour??9); const [endHour,setEndHour]=useState(initialGlobalMode?.allowed_end_hour??17);
  const [maxAge,setMaxAge]=useState(initialGlobalMode?.max_source_age_hours??24); const [retryLimit,setRetryLimit]=useState(initialGlobalMode?.retry_limit??0);
  const [categories,setCategories]=useState(initialGlobalMode?.allowed_categories?.join(", ")??""); const [excludedTopics,setExcludedTopics]=useState(initialGlobalMode?.excluded_topics?.join(", ")??"");
  async function refresh(nextPage = page, nextView = view) {
    setLoading(true); setError("");
    const params = new URLSearchParams({ view: nextView, q: query, language_code: language, blog_id: blog, page: String(nextPage), page_size: "25" });
    try {
      const response = await fetch(`/api/publications?${params}`, { cache:"no-store" });
      if (!response.ok) throw new Error("발행 현황을 불러오지 못했습니다.");
      const next = await response.json() as PublicationData; setData(next); setPage(nextPage); setView(nextView); setActiveTab(nextView);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "연결 오류"); }
    finally { setLoading(false); }
  }
  async function emergencyStop() {
    setEmergencyBusy(true); setError("");
    try { const r = await fetch("/api/publications/emergency-stop", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({enabled:true}) });
      if (!r.ok) throw new Error("긴급 정지를 기록하지 못했습니다."); await refresh(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "정지 요청 실패"); }
    finally { setEmergencyBusy(false); }
  }
  async function setScheduledAuto(action:"enable"|"disable"){
    const confirmation=action==="enable"?"ENABLE SCHEDULED AUTO PUBLICATION":"STOP SCHEDULED AUTO PUBLICATION";
    const scope=action==="enable"?scheduledBlogs:(data.mode_policy.scheduled_auto_policy?.policy_event?.approved_blog_ids??[]);
    if(action==="enable"&&scope.length===0){setError("예약 원고 자동 발행 대상 블로그를 선택하세요.");return;}
    if(!window.confirm(`${action==="enable"?"선택한 블로그의 예약 원고 자동 공개 발행을 승인합니다.":"예약 원고 자동 발행을 중지합니다."}\n\n${confirmation}`))return;
    setScheduledBusy(true);setError("");setNotice("");
    try{
      const response=await fetch("/api/publications/scheduled-auto-policy",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action,blog_ids:scope,daily_limit:1,actor_label:scheduledActor,reason:action==="enable"?"Authenticated operator explicitly enabled scheduled-export-only publication.":"Authenticated operator disabled scheduled-export-only publication.",idempotency_key:`scheduled-auto-${action}-${crypto.randomUUID()}`,confirmation})});
      const result=await response.json();if(!response.ok)throw new Error(String(result.detail??"예약 원고 자동 발행 설정을 저장하지 못했습니다."));
      setNotice(action==="enable"?"정책 승인 기록을 저장했습니다. 실제 첫 공개 게시 전에는 원고·블로그별 최초 승인이 추가로 필요합니다.":"예약 원고 자동 발행을 중지했습니다.");
      await refresh();
    }catch(cause){setError(cause instanceof Error?cause.message:"예약 원고 정책 변경 실패");}
    finally{setScheduledBusy(false);}
  }
  async function verifyScheduledConnections(){
    if(scheduledBlogs.length===0){setError("먼저 확인할 Blogger 블로그를 선택하세요.");return;}
    setScheduledConnectionBusy(true);setError("");setNotice("");
    try{
      const response=await fetch("/api/publications/scheduled-auto/verify-connections",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({blog_ids:scheduledBlogs})});
      const result=await response.json();if(!response.ok)throw new Error(String(result.detail??"Blogger 연결을 확인하지 못했습니다."));
      setNotice(result.all_verified?"선택한 블로그의 Blogger 읽기 연결과 ID를 확인했습니다. 이 확인은 글을 작성하거나 공개하지 않습니다.":"일부 Blogger 연결을 확인하지 못했습니다. 상세 상태를 점검한 뒤 다시 시도하세요.");
      await refresh();
    }catch(cause){setError(cause instanceof Error?cause.message:"Blogger 연결 확인 실패");}
    finally{setScheduledConnectionBusy(false);}
  }
  function chooseScope(type:"global"|"language"|"blog",key=""){
    setScopeType(type);setScopeKey(key);
    const saved=data.mode_policy.settings.find(item=>item.scope_type===type&&item.scope_key===key);
    setSelectedMode((saved?.configured_mode as "manual"|"auto")??"manual");setDailyLimit(saved?.daily_auto_limit??1);
    setMinimumInterval(saved?.minimum_interval_minutes??1440);setStartHour(saved?.allowed_start_hour??9);setEndHour(saved?.allowed_end_hour??17);
    setMaxAge(saved?.max_source_age_hours??24);setRetryLimit(saved?.retry_limit??0);
    setCategories(saved?.allowed_categories?.join(", ")??"");setExcludedTopics(saved?.excluded_topics?.join(", ")??"");
  }
  async function saveMode(){
    if(selectedMode==="auto"&&!window.confirm("Auto 정책 설정을 저장합니다. 실제 공개 발행은 별도 운영 게이트가 열리기 전까지 차단됩니다. 저장할까요?"))return;
    setEmergencyBusy(true);setNotice("");setError("");
    try{const response=await fetch("/api/publications/mode-settings",{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({scope_type:scopeType,scope_key:scopeKey,configured_mode:selectedMode,daily_auto_limit:dailyLimit,minimum_interval_minutes:minimumInterval,allowed_start_hour:startHour,allowed_end_hour:endHour,timezone:"Asia/Seoul",allowed_categories:categories.split(",").map(x=>x.trim()).filter(Boolean),excluded_topics:excludedTopics.split(",").map(x=>x.trim()).filter(Boolean),max_source_age_hours:maxAge,retry_limit:retryLimit})});
      const result=await response.json();if(!response.ok)throw new Error(String(result.detail??"설정 저장에 실패했습니다."));
      setNotice("설정을 저장했습니다. Blogger 실제 쓰기 및 Auto 게시 활성화는 별도 게이트에 의해 계속 차단됩니다.");
      const params=new URLSearchParams({view,q:query,language_code:language,blog_id:blog,page:String(page),page_size:"25"});const refreshResponse=await fetch(`/api/publications?${params}`,{cache:"no-store"});if(refreshResponse.ok)setData(await refreshResponse.json() as PublicationData);
    }catch(cause){setError(cause instanceof Error?cause.message:"설정 저장 실패");}finally{setEmergencyBusy(false);}
  }
  const counts = data.summary ?? {};
  const items = data.items ?? [];
  const shownCount = data.total_count ?? items.length;
  const globalMode = data.mode_policy.settings.find(x => x.scope_type === "global" && !x.scope_key);
  return <div className="publication-manager">
    <section className="publishing-summary" aria-label="발행 요약">
      <article><span>실제 공개 게시</span><strong>{data.actual_published_count ?? counts.published ?? 0}건</strong></article>
      <article><span>발행 대기</span><strong>{counts.queue ?? 0}건</strong></article>
      <article><span>검토 필요</span><strong>{counts.review ?? 0}건</strong></article>
      <article><span>실패·보류</span><strong>{counts.held ?? 0}건</strong></article>
    </section>
    <p className="publication-list-note">임시 제목·Mock/Test 표식 {counts.excluded_non_operational??0}건은 후보 목록에서 제외했습니다. 원고·평가·감사 기록은 보존됩니다. 본문 완전 중복 억제 {counts.duplicate_suppressed??0}건.</p>
    <p className="publication-list-note">발행 대기는 실제 Job이 생성된 원고입니다. 수동 원고는 상세에서 공개 게시를 확인해야 Job이 생성되며, 예약 Auto 원고는 정책과 자격을 충족하면 자동 등록됩니다. 처리 중인 Job은 게시 중으로 표시합니다.</p>
    <nav className="workspace-tabs publication-tabs" role="tablist" aria-label="발행 상태">
      {tabs.map(([key,label]) => <button key={key} role="tab" aria-selected={activeTab===key} onClick={() => void refresh(1,key)}>{label}<span>{counts[key] ?? 0}</span></button>)}
      <button role="tab" aria-selected={activeTab==="settings"} onClick={() => setActiveTab("settings")}>운영 설정</button>
      <button role="tab" aria-selected={activeTab==="scheduled-auto"} onClick={() => setActiveTab("scheduled-auto")}>예약 Auto</button>
      <button role="tab" aria-selected={activeTab==="post-review"} onClick={() => setActiveTab("post-review")}>게시 후 보완</button>
    </nav>
    {error && <p className="quality-held" role="alert">{error}</p>}
    {activeTab === "post-review" ? <PostPublicationReviewPanel /> : activeTab === "scheduled-auto" ? <section className="workspace-panel publication-section scheduled-auto-section" aria-labelledby="scheduled-auto-title">
      <div className="section-heading"><div><p className="eyebrow">예약 원고만 적용 · 일반 Auto·Trends와 별도</p><h2 id="scheduled-auto-title">예약 원고 자동 게시 관리</h2><p>Codex 예약 원고만 대상으로 합니다. 기본은 중지이며, 첫 공개 게시에는 원고별 별도 확인이 필요합니다.</p></div>
        <strong className={data.mode_policy.scheduled_auto_policy?.enabled ? "status-positive" : "status-muted"} role="status">{data.mode_policy.scheduled_auto_policy?.enabled ? "예약 Auto 활성" : "예약 Auto 중지"}</strong></div>
      <div className="scheduled-auto-grid">
        <article><h3>1. 대상 블로그</h3><p>실제 Blogger 읽기 연결을 확인한 활성 블로그만 승인 범위에 포함됩니다.</p>
          <fieldset><legend>예약 원고 자동 게시 대상</legend>{data.mode_policy.blogs.filter(item=>item.active).map(item=><label key={item.id}><input type="checkbox" checked={scheduledBlogs.includes(item.id)} onChange={event=>setScheduledBlogs(current=>event.target.checked?[...new Set([...current,item.id])]:current.filter(id=>id!==item.id))}/>{item.display_name} · {item.url}</label>)}</fieldset>
          <label>승인 기록 표시 이름<input value={scheduledActor} onChange={event=>setScheduledActor(event.target.value)} maxLength={120}/></label>
          <button className="secondary-button" disabled={scheduledConnectionBusy||scheduledBusy||scheduledBlogs.length===0} onClick={()=>void verifyScheduledConnections()}>{scheduledConnectionBusy?"연결 확인 중…":"선택 블로그 읽기 연결 확인"}</button>
        </article>
        <article><h3>2. 예약 원고 Auto 정책</h3><p>초기 자체 상한은 하루 1건입니다. 품질·근거·권리·중복 검사를 통과하지 못한 원고는 자동 보류됩니다.</p>
          <p>승인 범위: {(data.mode_policy.scheduled_auto_policy?.policy_event?.approved_blog_ids ?? []).map(id=>data.mode_policy.blogs.find(item=>item.id===id)?.display_name ?? id).join(", ") || "없음"}</p>
          <div className="scheduled-policy-actions">
            <button className="secondary-button" disabled={scheduledBusy||!data.mode_policy.scheduled_auto_policy?.enabled} onClick={()=>void setScheduledAuto("disable")}>{scheduledBusy?"기록 중…":"예약 원고 자동 게시 중지"}</button>
            <button disabled={scheduledBusy||Boolean(data.mode_policy.scheduled_auto_policy?.enabled)||scheduledBlogs.length===0} onClick={()=>void setScheduledAuto("enable")}>{scheduledBusy?"기록 중…":"선택 블로그 예약 Auto 승인·활성화"}</button>
          </div>
          <p className="publication-list-note">현재 상태에 맞는 작업만 사용할 수 있습니다. 비활성 버튼은 상태 확인용이며 설정을 변경하지 않습니다.</p>
          <p>이 설정은 기존 일반 Auto·Trends 정책을 바꾸지 않으며, 버튼을 눌러도 게시 Job을 직접 실행하지 않습니다.</p>
        </article>
      </div>
      {data.mode_policy.scheduled_auto_policy?.latest_connection_check && <section aria-labelledby="scheduled-connection-result"><h3 id="scheduled-connection-result">최근 읽기 연결 확인</h3><p>{kst(data.mode_policy.scheduled_auto_policy.latest_connection_check.created_at)}</p><ul>{(data.mode_policy.scheduled_auto_policy.latest_connection_check.payload?.results ?? []).map(result=><li key={result.blog_record_id}>{data.mode_policy.blogs.find(item=>item.id===result.blog_record_id)?.display_name ?? result.blog_record_id} · {result.verified?`확인됨 (${result.remote_blog_id})`:`확인 실패 (${result.reason ?? "오류"})`}</li>)}</ul></section>}
      <p className="publication-list-note" role="status">예약 Auto는 활성화된 Blogger 범위와 운영 한도에 따라 처리됩니다. 별도 최초 게시 승인 이벤트는 요구하지 않으며, 과거 승인 이벤트는 감사 데이터로만 보존됩니다.</p>
      <section aria-labelledby="scheduled-policy-history"><h3 id="scheduled-policy-history">예약 Auto 승인 이력</h3>
        {(data.mode_policy.scheduled_auto_policy?.policy_history?.length ?? 0)===0 ? <p className="empty-state">승인·중지 이력이 없습니다.</p> : <div className="publication-table-scroll"><table><thead><tr><th>시각(KST)</th><th>상태</th><th>대상 블로그</th><th>상한</th><th>기록자·사유</th></tr></thead><tbody>{data.mode_policy.scheduled_auto_policy?.policy_history?.map(item=><tr key={item.id}><td>{kst(item.created_at)}</td><td>{item.action==="enabled"?"활성 승인":"중지"}</td><td>{item.approved_blog_ids.map(id=>data.mode_policy.blogs.find(blogItem=>blogItem.id===id)?.display_name??id).join(", ")||"없음"}</td><td>{item.daily_limit}건/일</td><td>{item.actor_label}<small>{item.reason}</small></td></tr>)}</tbody></table></div>}
      </section>
    </section> : activeTab === "settings" ? <section className="workspace-panel publication-section">
      <h2>현재 운영 설정</h2><dl className="publication-settings-list">
        <div><dt>운영 모드</dt><dd>{globalMode?.configured_mode === "auto" ? "Auto 정책 설정" : "수동"} · 실제 쓰기 {data.real_writes_enabled ? "허용" : "차단"}</dd></div>
        <div><dt>긴급 정지</dt><dd>{data.mode_policy.emergency_stopped ? "활성" : "해제"}</dd></div>
        <div><dt>Worker</dt><dd>{data.worker ? `${data.worker.status} · ${data.mode_policy.publication_worker?.execution_mode ?? "실행 모드 미기록"} · ${kst(data.worker.last_seen_at)}` : "실행 기록 없음"}</dd></div>
        <div><dt>모의 대기 작업</dt><dd>{data.queued_mock_jobs}건 (실제 게시와 별도)</dd></div>
        <div><dt>확인된 비공개 초안 요청</dt><dd>{data.queued_confirmed_private_drafts ?? 0}건</dd></div>
        <div><dt>자동 후보</dt><dd>{data.auto_candidate_count}건 · 자동 발행은 비활성</dd></div>
      </dl>
      <h3>운영 DB 설정 편집</h3><p>상단은 저장된 정책값입니다. Auto 설정을 저장해도 실제 쓰기 권한이나 자동 게시를 켜지 않습니다.</p>
      <div className="mode-settings-form">
        <label>적용 범위<select value={scopeType} onChange={event=>chooseScope(event.target.value as "global"|"language"|"blog","")}><option value="global">전체 기본값</option><option value="language">언어별</option><option value="blog">블로그별</option></select></label>
        {scopeType==="language"&&<label>언어<select value={scopeKey} onChange={event=>chooseScope("language",event.target.value)}><option value="">선택</option>{data.mode_policy.languages.map(item=><option key={item.code} value={item.code}>{item.display_name||languageLabel(item.code)}</option>)}</select></label>}
        {scopeType==="blog"&&<label>블로그<select value={scopeKey} onChange={event=>chooseScope("blog",event.target.value)}><option value="">선택</option>{data.mode_policy.blogs.map(item=><option key={item.id} value={item.id}>{item.display_name}</option>)}</select></label>}
        <label>운영 모드<select value={selectedMode} onChange={event=>setSelectedMode(event.target.value as "manual"|"auto")}><option value="manual">수동</option><option value="auto">Auto 정책 미리 설정</option></select></label>
        <label>운영 모드 일일 Auto 상한<input type="number" min={0} max={3} value={dailyLimit} onChange={event=>setDailyLimit(Number(event.target.value))}/></label>
        <label>운영 모드 최소 간격(분)<input type="number" min={60} max={10080} value={minimumInterval} onChange={event=>setMinimumInterval(Number(event.target.value))}/></label>
        <label>자료 최신성(시간)<input type="number" min={1} max={720} value={maxAge} onChange={event=>setMaxAge(Number(event.target.value))}/></label>
        <label>재시도 상한<input type="number" min={0} max={2} value={retryLimit} onChange={event=>setRetryLimit(Number(event.target.value))}/></label>
        <label>허용 분야(쉼표 구분)<input value={categories} onChange={event=>setCategories(event.target.value)}/></label>
        <label>제외 주제<input value={excludedTopics} onChange={event=>setExcludedTopics(event.target.value)}/></label>
        <label>허용 시작 시각 KST<input type="number" min={0} max={23} value={startHour} onChange={event=>setStartHour(Number(event.target.value))}/></label>
        <label>허용 종료 시각 KST<input type="number" min={0} max={23} value={endHour} onChange={event=>setEndHour(Number(event.target.value))}/></label>
        <button disabled={emergencyBusy||(scopeType!=="global"&&!scopeKey)} onClick={()=>void saveMode()}>{emergencyBusy?"저장 중…":"설정 저장"}</button>
      </div>
      <h3>코드상 발행 안전 상한</h3><p>KST · 전체 {data.operational_limits?.global_daily??"—"}건/일 · 영어는 잔여량 우선 · 블로그 간격 {data.operational_limits?.blog_minimum_interval_minutes??"—"}분 · Blogger 계정 간격 {data.operational_limits?.account_minimum_interval_minutes??"—"}분</p>
      <ul>{Object.entries(data.operational_limits?.language_daily??{}).map(([code,limit])=><li key={code}>{languageLabel(code)} 일일 {limit??"전역 잔여량"}건 · 시간당 {data.operational_limits?.language_hourly[code]??"—"}건</li>)}</ul>
      <h3>저장된 범위별 설정</h3><ul>{data.mode_policy.settings.map(item=><li key={`${item.scope_type}-${item.scope_key}`}>{item.scope_type}:{item.scope_key||"global"} · {item.configured_mode} · {item.daily_auto_limit}건/일 · {item.minimum_interval_minutes}분</li>)}</ul>
      {notice&&<p role="status">{notice}</p>}
      <button className="secondary-button" disabled={emergencyBusy || data.mode_policy.emergency_stopped} onClick={() => void emergencyStop()}>{data.mode_policy.emergency_stopped ? "긴급 정지 활성" : "긴급 발행 정지"}</button>
      <p>발행 한도는 상한입니다. 이 화면은 Blogger 실제 게시를 수행하지 않습니다.</p>
    </section> : <section className="workspace-panel publication-section">
      <div className="section-heading"><div><h2>{tabs.find(x=>x[0]===view)?.[1]}</h2><p>{shownCount}건 · 최신 대표 버전 기준 · 이전 버전은 원고 상세의 변경 이력에서 확인합니다.</p></div></div>
      <form className="publication-filters" onSubmit={event => { event.preventDefault(); void refresh(1,view); }}>
        <label>제목·주제 검색<input value={query} onChange={e=>setQuery(e.target.value)} placeholder="검색어" /></label>
        <label>언어<select value={language} onChange={e=>setLanguage(e.target.value)}><option value="">모든 언어</option>{data.mode_policy.languages.map(x=><option key={x.code} value={x.code}>{x.display_name || languageLabel(x.code)}</option>)}</select></label>
        <label>블로그<select value={blog} onChange={e=>setBlog(e.target.value)}><option value="">모든 블로그</option>{data.mode_policy.blogs.map(x=><option key={x.id} value={x.id}>{x.display_name}</option>)}</select></label>
        <button type="submit" disabled={loading}>검색</button>
      </form>
      {loading ? <p className="empty-state">불러오는 중…</p> : items.length ? <div className="publication-table-scroll"><table><thead><tr><th>원고</th><th>언어</th><th>대상 블로그</th><th>주제·출처</th><th>상태</th><th>시각</th>{view==="published"&&<th>게시 URL</th>}{view==="auto_failure"&&<th>복구</th>}</tr></thead><tbody>
        {items.map(item=><tr key={`${item.id}-${item.blog_id}`}>
          <td>{item.import_id
            ? <a href={`/imports?open_import_id=${encodeURIComponent(item.import_id)}&return_to=${encodeURIComponent(`/publishing?view=${view}&page=${page}&q=${query}&language_code=${language}&blog_id=${blog}`)}`}>{item.title || "제목 없음"}</a>
            : item.evaluation_id
              ? <a href={`/manuscripts?open_evaluation_id=${encodeURIComponent(item.evaluation_id)}&open_content_version_id=${encodeURIComponent(item.content_version_id)}&return_to=${encodeURIComponent(`/publishing?view=${view}&page=${page}&q=${query}&language_code=${language}&blog_id=${blog}`)}`}>{item.title || "제목 없음"}</a>
              : <span>{item.title || "제목 없음"}</span>}
            {item.auto_publication_failure && <strong className="status-badge status-warning">자동발행실패</strong>}<small>버전 {item.content_version_id.slice(0,8)} · {item.google_trends_based ? "Google Trends" : item.generation_method === "chatgpt_scheduled_export" ? "Codex 예약" : item.generation_method === "manual_codex_import" ? "수동 Import" : "내부 원고"}</small></td>
          <td>{languageLabel(item.language_code)}</td><td>{item.blog_name || item.url}</td>
          <td>{item.topic || item.source_names || "주제·출처 정보 없음"}</td>
          <td>{statusLabel(item.status)}{item.failure_reason_code && <small>실패 단계 {item.failure_stage ?? "미확인"} · {reasonLabel(item.failure_reason_code)}</small>}{item.retry_count !== undefined && <small>재시도 {item.retry_count}회</small>}{item.eligibility_reasons?.length ? <small>{item.eligibility_reasons.slice(0,2).map(reasonLabel).join(" · ")}</small> : null}{item.simulation_only && <small>모의 작업</small>}</td>
          <td>{kst(item.next_publish_at || item.created_at)}</td>
          {view==="published"&&<td>{item.remote_url&&item.remote_status==="LIVE"&&item.remote_verified_at?<a href={item.remote_url} target="_blank" rel="noreferrer">게시물 열기</a>:"원격 게시 확인 없음"}{item.remote_post_id&&<small>postId {item.remote_post_id}</small>}</td>}
          {view==="auto_failure"&&<td>{item.import_id ? <a href={`/imports?open_import_id=${encodeURIComponent(item.import_id)}&open_content_version_id=${encodeURIComponent(item.content_version_id)}&return_to=${encodeURIComponent(`/publishing?view=auto_failure&page=${page}&q=${query}&language_code=${language}&blog_id=${blog}`)}`}>Blogger에 수동 발행</a> : "상세 원고 연결 없음"}</td>}
        </tr>)}
      </tbody></table></div> : <p className="empty-state">이 상태의 원고가 없습니다.</p>}
      <div className="publication-pagination"><button disabled={page<=1||loading} onClick={()=>void refresh(page-1,view)}>이전</button><span>{page} / {Math.max(data.page_count ?? 0,1)}</span><button disabled={page>=(data.page_count??0)||loading} onClick={()=>void refresh(page+1,view)}>다음</button></div>
    </section>}
  </div>;
}
