"use client";

import { useEffect, useRef, useState } from "react";
import ExternalImportWorkspace from "../imports/external-import-workspace";
import PostPublicationReviewPanel from "./post-publication-review-panel";
import PublicationWorkerPanel from "./publication-worker-panel";
import { publicationReasonText, publicationReasonsText, publicationApiErrorText } from "./publication-messages";

type Item = {
  id: string; content_version_id: string; group_id?: string; title: string; language_code: string;
  blog_id: string; blog_name?: string; url: string; topic?: string | null; source_names?: string | null;
  status: string; quality_status?: string | null; eligibility_reasons?: string[];
  has_publishing_job?: boolean; publishing_job_id?: string | null;
  next_publish_at?: string | null; created_at?: string | null; remote_url?: string | null;
  remote_post_id?: string | null; remote_status?: string | null; remote_verified_at?: string | null;
  simulation_only?: boolean; adapter_type?: string; evaluation_id?: string | null;
  import_id?: string | null; generation_method?: string | null; google_trends_based?: boolean;
  trends_search_query?: string | null; trends_search_country?: string | null;
  trends_search_volume_raw?: string | null; trends_search_volume_kind?: string | null;
  auto_publication_failure?: boolean; failure_stage?: string | null; failure_reason_code?: string | null;
  manual_publication_available?: boolean; retry_count?: number;
  published_title?: string; published_content_version_id?: string;
  origin_kind?: "google_trends" | "scheduled" | "manual" | "unknown";
  origin_reason?: string; automation_id?: string; scheduled_slot?: string; occurrence_id?: string;
  authoring_job_id?: string; trend_request_id?: string;
  previous_view?: string; discard_reason?: string; discard_actor?: string; discarded_at?: string;
};
type ManualPreview = { eligible?: boolean; request_available?: boolean; blockers?: string[]; title?: string; body?: string; title_sha256?: string; body_sha256?: string; html_sha256?: string; content_version_id?: string; generation_method?: string; publish_ready?: boolean; followups?: Array<{issue_type?:string;severity?:string;description?:string}>; seo?: {search_description?:string|null;search_description_stored?:boolean;blogger_api_supported?:boolean;manual_entry_required?:boolean;blogger_delivery_status?:string;html_meta_description_verified?:boolean;robots_indexing_status?:string;canonical_status?:string} };
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
  operational_limits?: {timezone:string;global_daily:number;language_daily:Record<string,number|null>;language_hourly:Record<string,number>;english_daily_policy:string;global_publish_min_interval_minutes:number|null};
};
const tabs = [["queue", "발행 대기"], ["review", "검토 필요"], ["published", "게시 완료"], ["held", "실패·보류"], ["auto_failure", "자동발행실패"], ["discarded", "폐기 보관함"]] as const;
const originLabels = { google_trends: "Google Trends", scheduled: "Codex 예약", manual: "수동 작성", unknown: "출처 미확인" } as const;
const languageLabel = (code: string) => ({ko:"한국어",en:"영어",ja:"일본어","zh-CN":"중국어 간체",de:"독일어","pt-BR":"브라질 포르투갈어",vi:"베트남어"}[code] ?? code);
const statusLabel = (status: string) => ({review_needed:"검토 필요",queueable:"발행 자격 충족 · Job 없음",queued:"Worker 처리 대기",auto_paused:"자동 발행 중지로 보류",manual_action_required:"수동 요청 확인 필요 · 실행 차단",draft_saved:"Blogger 비공개 초안 저장 완료",publishing:"게시 중",published:"게시 완료",quality_held:"품질 보류",publication_blocked:"게시 차단",failed:"실패",uncertain:"결과 확인 필요",auto_publication_failed:"자동발행실패"}[status] ?? status);
const kst = (value?: string | null) => value ? new Intl.DateTimeFormat("ko-KR", { timeZone:"Asia/Seoul", dateStyle:"medium", timeStyle:"short" }).format(new Date(value)) + " KST" : "기록 없음";

export default function PublicationManager({ initial,initialFilters={} }: { initial: PublicationData;initialFilters?:Record<string,string> }) {
  const [data, setData] = useState(initial);
  const [topTab,setTopTab]=useState<"publication"|"jobs">(initialFilters.section==="jobs"?"jobs":"publication");
  const initialGlobalMode=initial.mode_policy.settings.find(item=>item.scope_type==="global"&&!item.scope_key);
  const [view, setView] = useState<(typeof tabs)[number][0]>((initial.view as (typeof tabs)[number][0]) || "review");
  const [query, setQuery] = useState(initialFilters.q??""); const [language, setLanguage] = useState(initialFilters.language_code??""); const [blog, setBlog] = useState(initialFilters.blog_id??""); const [origin,setOrigin]=useState(initialFilters.origin??"");
  const [page, setPage] = useState(initial.page??1); const [loading, setLoading] = useState(false); const [error, setError] = useState("");
  const [activeTab, setActiveTab] = useState<string>(view);
  const [emergencyBusy, setEmergencyBusy] = useState(false);
  const [notice,setNotice]=useState("");
  const [monitorRefresh,setMonitorRefresh]=useState(0);
  const [selection,setSelection]=useState<string[]>([]);
  const [discardTargets,setDiscardTargets]=useState<Item[]>([]);
  const [discardReason,setDiscardReason]=useState("폐기처리 하기로 결정함");
  const [discardActor,setDiscardActor]=useState("관리자");
  const [discardBusy,setDiscardBusy]=useState(false);
  const [quickPublishLoading,setQuickPublishLoading]=useState(false);
  const [quickPublishBusy,setQuickPublishBusy]=useState(false);
  const [pendingManualJobId,setPendingManualJobId]=useState<string|null>(null);
  const searchTimer=useRef<ReturnType<typeof setTimeout>|null>(null);
  const refreshRequest=useRef(0);
  useEffect(()=>{
    if(!pendingManualJobId)return;
    let disposed=false,attempts=0,timer:ReturnType<typeof setTimeout>|undefined;
    const check=async()=>{
      if(disposed)return;
      if(document.visibilityState==="hidden"){timer=setTimeout(check,15000);return;}
      attempts+=1;
      try{
        const response=await fetch("/api/publications/worker-jobs?view=all&page=1&page_size=100",{cache:"no-store"});
        if(response.ok){
          const monitor=await response.json() as {items?:Array<{job_id?:string|null;state?:string;remote_status?:string|null;remote_post_id?:string|null;remote_url?:string|null;failure_reason?:string|null}>};
          const job=monitor.items?.find(item=>item.job_id===pendingManualJobId);
          if(job){
            if(job.state==="published"&&job.remote_status==="LIVE"&&job.remote_post_id&&job.remote_url){setNotice(`Blogger에 공개 게시가 완료되었습니다. postId ${job.remote_post_id} · ${job.remote_url}`);setPendingManualJobId(null);setMonitorRefresh(value=>value+1);return;}
            if(job.state==="draft_saved"&&job.remote_status==="DRAFT"&&job.remote_post_id){setNotice(`Blogger 비공개 초안으로 저장되었습니다. postId ${job.remote_post_id}`);setPendingManualJobId(null);setMonitorRefresh(value=>value+1);return;}
            if(["failed","auto_paused","manual_action_required","uncertain"].includes(job.state??"")){
              const why=job.failure_reason?publicationReasonText(job.failure_reason):"Job 관리에서 상세 상태를 확인하세요.";
              setNotice(`${job.state==="failed"?"Blogger 게시에 실패했습니다.":"발행 요청이 보류되었습니다."} ${why} (Job ${pendingManualJobId})`);setPendingManualJobId(null);setMonitorRefresh(value=>value+1);return;
            }
          }
        }
      }catch{/* Keep the queued Job visible; the next bounded poll can recover. */}
      if(attempts>=120){setNotice(`발행 요청이 아직 처리 중입니다. Job ${pendingManualJobId}의 최종 결과를 Job 관리에서 확인하세요.`);setPendingManualJobId(null);return;}
      timer=setTimeout(check,15000);
    };
    void check();
    return()=>{disposed=true;if(timer)clearTimeout(timer);};
  },[pendingManualJobId]);
  const [detailRequest,setDetailRequest]=useState<{id:string;version:string;target:string;publish:boolean;nonce:number}>();
  const openManuscript=(item:Item,publish=false)=>{if(item.import_id)setDetailRequest(previous=>({id:item.import_id!,version:item.content_version_id,target:item.blog_id,publish,nonce:(previous?.nonce??0)+1}));};
  const [scheduledBlogs,setScheduledBlogs]=useState<string[]>([]);
  const [scheduledActor,setScheduledActor]=useState("운영자");
  const [scheduledBusy,setScheduledBusy]=useState(false);
  const [scheduledConnectionBusy,setScheduledConnectionBusy]=useState(false);
  const [scopeType,setScopeType]=useState<"global"|"language"|"blog">("global");
  const [scopeKey,setScopeKey]=useState("");
  const [selectedMode,setSelectedMode]=useState<"manual"|"auto">((initialGlobalMode?.configured_mode as "manual"|"auto")??"manual");
  const [dailyLimit,setDailyLimit]=useState(initialGlobalMode?.daily_auto_limit??100); const [minimumInterval,setMinimumInterval]=useState(initialGlobalMode?.minimum_interval_minutes??15);
  const [startHour,setStartHour]=useState(initialGlobalMode?.allowed_start_hour??9); const [endHour,setEndHour]=useState(initialGlobalMode?.allowed_end_hour??17);
  const [maxAge,setMaxAge]=useState(initialGlobalMode?.max_source_age_hours??24); const [retryLimit,setRetryLimit]=useState(initialGlobalMode?.retry_limit??0);
  const [categories,setCategories]=useState(initialGlobalMode?.allowed_categories?.join(", ")??""); const [excludedTopics,setExcludedTopics]=useState(initialGlobalMode?.excluded_topics?.join(", ")??"");
  async function refresh(nextPage = page, nextView = view, searchQuery = query, filterChange: Record<string,string> = {}) {
    const requestId=++refreshRequest.current;
    setLoading(true); setError("");
    const params = new URLSearchParams({ view: nextView, q: searchQuery, language_code: language, blog_id: blog, origin, page: String(nextPage), page_size: "25", compact: "true" });
    Object.entries(filterChange).forEach(([key,value])=>params.set(key,value));
    try {
      const response = await fetch(`/api/publications?${params}`, { cache:"no-store" });
      if (!response.ok) throw new Error("발행 현황을 불러오지 못했습니다.");
      let next = await response.json() as PublicationData;
      if (nextPage > Math.max(next.page_count ?? 1, 1)) {
        nextPage = Math.max(next.page_count ?? 1, 1); params.set("page", String(nextPage));
        const corrected = await fetch(`/api/publications?${params}`, {cache:"no-store"});
        if (!corrected.ok) throw new Error("발행 현황을 갱신하지 못했습니다.");
        next = await corrected.json() as PublicationData;
      }
      if(requestId!==refreshRequest.current)return;
      setData(next); setPage(nextPage); setView(nextView); setActiveTab(nextView);setSelection([]);
      const url=new URL(window.location.href);params.forEach((value,key)=>url.searchParams.set(key,value));window.history.replaceState(null,"",url.pathname+url.search);
    } catch (cause) { if(requestId===refreshRequest.current)setError(cause instanceof Error ? cause.message : "연결 오류"); }
    finally { if(requestId===refreshRequest.current)setLoading(false); }
  }
  useEffect(()=>{const onPop=()=>setTopTab(new URL(window.location.href).searchParams.get("section")==="jobs"?"jobs":"publication");window.addEventListener("popstate",onPop);return()=>window.removeEventListener("popstate",onPop);},[]);
  useEffect(()=>()=>{if(searchTimer.current)clearTimeout(searchTimer.current);},[]);
  function chooseTop(next:"publication"|"jobs"){
    setTopTab(next);const url=new URL(window.location.href);
    if(next==="jobs")url.searchParams.set("section","jobs");else url.searchParams.delete("section");
    window.history.pushState({section:next},"",url.pathname+url.search);window.scrollTo({top:0,behavior:"auto"});
  }
  const itemKey=(item:Item)=>`${item.content_version_id}:${item.blog_id}`;
  function openDiscard(targets:Item[]){setDiscardTargets(targets);setDiscardReason("폐기처리 하기로 결정함");setError("");}
  async function openQuickPublish(item:Item){
    if(quickPublishLoading||quickPublishBusy)return;
    setQuickPublishLoading(true);setQuickPublishBusy(true);setError("");
    setNotice("수동 발행 요청을 처리하고 있습니다. 최신 원고와 발행 조건을 확인합니다.");
    try{
      if(!item.import_id)throw new Error("Research Import 연결이 없어 수동 발행 요청을 확인할 수 없습니다.");
      const previewUrl=`/api/publications/scheduled-auto-first-post?import_id=${encodeURIComponent(item.import_id)}`;
      const previewResponse=await fetch(previewUrl,{cache:"no-store"});
      const preview=await previewResponse.json().catch(()=>({})) as {targets?:Array<{id?:string;manual_publication?:ManualPreview}>;detail?:string;error?:string;code?:string};
      if(!previewResponse.ok)throw new Error(preview.detail?publicationApiErrorText(preview.detail):preview.error??`최신 발행 조건을 확인하지 못했습니다 (HTTP ${previewResponse.status}${preview.code?`, ${preview.code}`:""}).`);
      const target=preview.targets?.find(candidate=>candidate.id===item.blog_id);
      const manual=target?.manual_publication;
      if(!target)throw new Error("해당 언어의 활성 Blogger 목록에서 대상 블로그를 찾지 못했습니다. Blogger 언어 매핑을 확인하세요.");
      if(!manual)throw new Error("서버가 대상 Blogger의 수동 발행 상태를 반환하지 않았습니다. API와 Blogger 연결 상태를 확인하세요.");
      if(manual.content_version_id!==item.content_version_id)throw new Error("목록의 원고 버전이 최신 버전과 다릅니다. 목록을 새로고침한 뒤 다시 요청하세요.");
      if(manual.eligible!==true){
        const reasons=manual.blockers??[];
        throw new Error(`\ud604\uc7ac \ubc1c\ud589\ud560 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4. ${publicationReasonsText(reasons)||"\ubc1c\ud589 \uac00\ub2a5 \uc0c1\ud0dc\ub97c \ud655\uc778\ud558\uc9c0 \ubabb\ud588\uc2b5\ub2c8\ub2e4. \uc6d0\uace0\ub97c \uc0c8\ub85c\uace0\uce68\ud574 \ub2e4\uc2dc \ud655\uc778\ud558\uc138\uc694."}`);
      }
      if(!manual.title_sha256||!manual.body_sha256||!manual.html_sha256)throw new Error("최신 원고 해시가 없어 정확한 버전을 발행 요청에 연결할 수 없습니다.");
      const versionKey=item.content_version_id.replaceAll("-","");
      const response=await fetch("/api/publications/manual-live-requests",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({
        content_version_id:item.content_version_id,blog_id:item.blog_id,
        expected_title_sha256:manual.title_sha256,expected_body_sha256:manual.body_sha256,expected_html_sha256:manual.html_sha256,
        actor_label:"Dashboard admin action",reason:"발행 관리에서 사용자가 선택한 정확한 원고 버전의 LIVE 발행 요청",
        publication_mode:"publish",confirmation:"PUBLISH THIS EXACT MANUSCRIPT PUBLICLY",
        idempotency_key:`manual-publish-${versionKey}-${manual.body_sha256.slice(0,24)}`,
      })});
      const result=await response.json().catch(()=>({})) as {id?:string;recorded?:boolean;duplicate?:boolean;state?:string;reasons?:string[];detail?:string;code?:string;request_id?:string;followup_count?:number};
      if(!response.ok)throw new Error(result.detail?publicationApiErrorText(result.detail):`발행 요청에 실패했습니다 (HTTP ${response.status}${result.code?`, ${result.code}`:""}${result.request_id?`, 요청 ID ${result.request_id}`:""}).`);
      if(result.recorded===false)throw new Error(`\ubc1c\ud589\uc774 \ucc28\ub2e8\ub410\uc2b5\ub2c8\ub2e4. ${publicationReasonsText(result.reasons??[])||"\ud544\uc218 \uc870\uac74\uc744 \ucda9\uc871\ud558\uc9c0 \ubabb\ud588\uc2b5\ub2c8\ub2e4."}`);
      setNotice(result.duplicate?`기존 발행 요청을 확인했습니다. Job ${result.id??""} · 중복 게시 요청은 생성하지 않았습니다.`:`발행 큐에 등록했습니다. Job ${result.id??""} · 보완사항 ${result.followup_count??0}건 · 실제 Blogger 게시 결과는 Job 관리에서 확인하세요.`);
      if(result.id)setPendingManualJobId(result.id);
      setSelection([]);setMonitorRefresh(value=>value+1);await refresh(1,view);
    }catch(cause){
      const message=cause instanceof Error?cause.message:"수동 발행 요청을 처리하지 못했습니다.";
      setError(message);setNotice("발행 요청은 등록되지 않았으며 Blogger 쓰기도 시작되지 않았습니다.");
    }finally{setQuickPublishLoading(false);setQuickPublishBusy(false);}
  }
  async function submitDiscard(){
    if(discardActor.trim().length<2||discardReason.trim().length<10){setError("작업자 2자 이상과 사유 10자 이상을 입력하세요.");return;}
    const restoring=view==="discarded";
    setDiscardBusy(true);setError("");
    try{
      const response=await fetch(`/api/publications/discards${restoring?"/restore":""}`,{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({actor:discardActor.trim(),reason:discardReason.trim(),targets:discardTargets.map(item=>({content_version_id:item.content_version_id,blog_id:item.blog_id,previous_view:restoring?(item.previous_view??"review"):view}))}),
      });
      const result=await response.json() as {success_count?:number;failure_count?:number;failures?:{reason:string}[];detail?:string};
      if(!response.ok)throw new Error(result.detail?publicationApiErrorText(result.detail):`요청 실패 (HTTP ${response.status})`);
      const succeeded=result.success_count??0;const failed=result.failure_count??0;
      setNotice(`${restoring?"복원":"폐기"} ${succeeded}건 완료${failed?` · ${failed}건 실패 (${(result.failures??[]).map(item=>item.reason).join(", ")})`:""}`);
      setDiscardTargets([]);setSelection([]);setMonitorRefresh(value=>value+1);
      await refresh(1,view);
    }catch(cause){setError(cause instanceof Error?cause.message:"원고 상태 변경 실패");}
    finally{setDiscardBusy(false);}
  }
  useEffect(() => {
    let pending=false; const controller=new AbortController();
    const poll=async()=>{if(pending||topTab!=="publication"||document.visibilityState!=="visible")return;pending=true;
      const requestId=++refreshRequest.current;
      try {const params=new URLSearchParams({view,q:query,language_code:language,blog_id:blog,origin,page:String(page),page_size:"25",compact:"true"});
        const response=await fetch(`/api/publications?${params}`,{cache:"no-store",signal:controller.signal});
        if(!response.ok)throw new Error("발행 현황 자동 갱신에 실패했습니다.");
        const next=await response.json() as PublicationData;
        if(requestId===refreshRequest.current){if(page>Math.max(next.page_count??1,1))setPage(Math.max(next.page_count??1,1));else setData(next);}
      }catch(cause){if(!controller.signal.aborted)setError(cause instanceof Error?cause.message:"발행 현황 갱신 실패");}finally{pending=false;}};
    const timer=setInterval(()=>void poll(),30000);return()=>{clearInterval(timer);controller.abort();};
  },[view,query,language,blog,origin,page,topTab]);
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
      const response=await fetch("/api/publications/scheduled-auto-policy",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action,blog_ids:scope,daily_limit:100,actor_label:scheduledActor,reason:action==="enable"?"Authenticated operator explicitly enabled scheduled-export-only publication.":"Authenticated operator disabled scheduled-export-only publication.",idempotency_key:`scheduled-auto-${action}-${crypto.randomUUID()}`,confirmation})});
      const result=await response.json();if(!response.ok)throw new Error(String(result.detail?publicationApiErrorText(result.detail):"예약 원고 자동 발행 설정을 저장하지 못했습니다."));
      setNotice(action==="enable"?"예약 발행 범위와 일일 상한을 저장했습니다. 각 작업은 공통 Blogger 발행 정책과 중복 검사를 거칩니다.":"예약 원고 자동 발행을 중지했습니다.");
      await refresh();
    }catch(cause){setError(cause instanceof Error?cause.message:"예약 원고 정책 변경 실패");}
    finally{setScheduledBusy(false);}
  }
  async function verifyScheduledConnections(){
    if(scheduledBlogs.length===0){setError("먼저 확인할 Blogger 블로그를 선택하세요.");return;}
    setScheduledConnectionBusy(true);setError("");setNotice("");
    try{
      const response=await fetch("/api/publications/scheduled-auto/verify-connections",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({blog_ids:scheduledBlogs})});
      const result=await response.json();if(!response.ok)throw new Error(String(result.detail?publicationApiErrorText(result.detail):"Blogger 연결을 확인하지 못했습니다."));
      setNotice(result.all_verified?"선택한 블로그의 Blogger 읽기 연결과 ID를 확인했습니다. 이 확인은 글을 작성하거나 공개하지 않습니다.":"일부 Blogger 연결을 확인하지 못했습니다. 상세 상태를 점검한 뒤 다시 시도하세요.");
      await refresh();
    }catch(cause){setError(cause instanceof Error?cause.message:"Blogger 연결 확인 실패");}
    finally{setScheduledConnectionBusy(false);}
  }
  function chooseScope(type:"global"|"language"|"blog",key=""){
    setScopeType(type);setScopeKey(key);
    const saved=data.mode_policy.settings.find(item=>item.scope_type===type&&item.scope_key===key);
    setSelectedMode((saved?.configured_mode as "manual"|"auto")??"manual");setDailyLimit(saved?.daily_auto_limit??100);
    setMinimumInterval(saved?.minimum_interval_minutes??15);setStartHour(saved?.allowed_start_hour??9);setEndHour(saved?.allowed_end_hour??17);
    setMaxAge(saved?.max_source_age_hours??24);setRetryLimit(saved?.retry_limit??0);
    setCategories(saved?.allowed_categories?.join(", ")??"");setExcludedTopics(saved?.excluded_topics?.join(", ")??"");
  }
  async function saveMode(){
    if(selectedMode==="auto"&&!window.confirm("Auto 정책 설정을 저장합니다. 실제 공개 발행은 별도 운영 게이트가 열리기 전까지 차단됩니다. 저장할까요?"))return;
    setEmergencyBusy(true);setNotice("");setError("");
    try{const response=await fetch("/api/publications/mode-settings",{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({scope_type:scopeType,scope_key:scopeKey,configured_mode:"authoring_only",daily_auto_limit:dailyLimit,minimum_interval_minutes:minimumInterval,allowed_start_hour:startHour,allowed_end_hour:endHour,timezone:"Asia/Seoul",allowed_categories:categories.split(",").map(x=>x.trim()).filter(Boolean),excluded_topics:excludedTopics.split(",").map(x=>x.trim()).filter(Boolean),max_source_age_hours:maxAge,retry_limit:retryLimit})});
      const result=await response.json();if(!response.ok)throw new Error(String(result.detail?publicationApiErrorText(result.detail):"설정 저장에 실패했습니다."));
      setNotice("설정을 저장했습니다. Blogger 실제 쓰기 및 Auto 게시 활성화는 별도 게이트에 의해 계속 차단됩니다.");
      const params=new URLSearchParams({view,q:query,language_code:language,blog_id:blog,page:String(page),page_size:"25"});const refreshResponse=await fetch(`/api/publications?${params}`,{cache:"no-store"});if(refreshResponse.ok)setData(await refreshResponse.json() as PublicationData);
    }catch(cause){setError(cause instanceof Error?cause.message:"설정 저장 실패");}finally{setEmergencyBusy(false);}
  }
  const counts = data.summary ?? {};
  const items = data.items ?? [];
  const shownCount = data.total_count ?? items.length;
  const globalMode = data.mode_policy.settings.find(x => x.scope_type === "global" && !x.scope_key);
  return <div className="publication-manager">
    <nav className="workspace-tabs publication-top-tabs" role="tablist" aria-label="발행 운영 영역">
      <button type="button" role="tab" aria-selected={topTab==="publication"} onClick={()=>chooseTop("publication")}>발행 관리</button>
      <button type="button" role="tab" aria-selected={topTab==="jobs"} onClick={()=>chooseTop("jobs")}>Job 관리</button>
    </nav>
    {topTab==="jobs" ? <PublicationWorkerPanel refreshKey={monitorRefresh} onOpenImport={job=>{if(job.import_id){chooseTop("publication");setDetailRequest(previous=>({id:job.import_id!,version:job.content_version_id??"",target:job.blog_id??"",publish:false,nonce:(previous?.nonce??0)+1}));}}} onRequestPublication={job=>{if(job.import_id&&job.content_version_id&&job.blog_id){chooseTop("publication");setView("auto_failure");setActiveTab("auto_failure");void refresh(1,"auto_failure");setDetailRequest(previous=>({id:job.import_id!,version:job.content_version_id!,target:job.blog_id!,publish:true,nonce:(previous?.nonce??0)+1}));}}} /> : <>
    {notice&&<p role="status" className="publication-notice">{notice}</p>}
    <ExternalImportWorkspace embedded detailRequest={detailRequest} onPublicationRequested={jobId=>{setNotice(`발행 Job ${jobId} 등록 완료 · 실제 게시 결과는 Worker 모니터에서 확인하세요.`);setMonitorRefresh(x=>x+1);void refresh();}} />
    <section className="publishing-summary" aria-label="원고 목록 요약">
      <article><span>실제 공개 게시</span><strong>{data.actual_published_count ?? counts.published ?? 0}건</strong></article>
      <article><span>발행 대기 원고</span><strong>{counts.queue ?? 0}건</strong></article>
      <article><span>검토 필요 원고</span><strong>{counts.review ?? 0}건</strong></article>
      <article><span>실패·보류 항목</span><strong>{counts.held ?? 0}건</strong></article>
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
       <div className="section-heading"><div><p className="eyebrow">예약 원고만 적용 · 일반 Auto·Trends와 별도</p><h2 id="scheduled-auto-title">예약 원고 자동 게시 관리</h2><p>Codex 예약 원고만 대상으로 합니다. 활성 범위, 품질, 중복 및 Blogger 쓰기 정책을 충족해야 공개됩니다.</p></div>
        <strong className={data.mode_policy.scheduled_auto_policy?.enabled ? "status-positive" : "status-muted"} role="status">{data.mode_policy.scheduled_auto_policy?.enabled ? "예약 Auto 활성" : "예약 Auto 중지"}</strong></div>
      <div className="scheduled-auto-grid">
        <article><h3>1. 대상 블로그</h3><p>실제 Blogger 읽기 연결을 확인한 활성 블로그만 승인 범위에 포함됩니다.</p>
          <fieldset><legend>예약 원고 자동 게시 대상</legend>{data.mode_policy.blogs.filter(item=>item.active).map(item=><label key={item.id}><input type="checkbox" checked={scheduledBlogs.includes(item.id)} onChange={event=>setScheduledBlogs(current=>event.target.checked?[...new Set([...current,item.id])]:current.filter(id=>id!==item.id))}/>{item.display_name} · {item.url}</label>)}</fieldset>
          <label>승인 기록 표시 이름<input value={scheduledActor} onChange={event=>setScheduledActor(event.target.value)} maxLength={120}/></label>
          <button className="secondary-button" disabled={scheduledConnectionBusy||scheduledBusy||scheduledBlogs.length===0} onClick={()=>void verifyScheduledConnections()}>{scheduledConnectionBusy?"연결 확인 중…":"선택 블로그 읽기 연결 확인"}</button>
        </article>
        <article><h3>2. 예약 원고 Auto 정책</h3><p>승인된 예약 Blogger 범위에만 적용합니다. 모든 활성 블로그는 KST 기준 하루 100건의 공통 LIVE 상한과 15분 글로벌 간격을 공유합니다.</p>
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
        <label>운영 모드<select value="authoring_only" disabled><option value="authoring_only">원고 작성 전용</option></select></label>
        <label>운영 모드 일일 Auto 상한<input type="number" min={0} max={100} value={dailyLimit} onChange={event=>setDailyLimit(Number(event.target.value))}/></label>
        <label>운영 모드 최소 간격(분)<input type="number" min={15} max={10080} value={minimumInterval} onChange={event=>setMinimumInterval(Number(event.target.value))}/></label>
        <label>자료 최신성(시간)<input type="number" min={1} max={720} value={maxAge} onChange={event=>setMaxAge(Number(event.target.value))}/></label>
        <label>재시도 상한<input type="number" min={0} max={2} value={retryLimit} onChange={event=>setRetryLimit(Number(event.target.value))}/></label>
        <label>허용 분야(쉼표 구분)<input value={categories} onChange={event=>setCategories(event.target.value)}/></label>
        <label>제외 주제<input value={excludedTopics} onChange={event=>setExcludedTopics(event.target.value)}/></label>
        <label>허용 시작 시각 KST<input type="number" min={0} max={23} value={startHour} onChange={event=>setStartHour(Number(event.target.value))}/></label>
        <label>허용 종료 시각 KST<input type="number" min={0} max={23} value={endHour} onChange={event=>setEndHour(Number(event.target.value))}/></label>
        <button disabled={emergencyBusy||(scopeType!=="global"&&!scopeKey)} onClick={()=>void saveMode()}>{emergencyBusy?"저장 중…":"설정 저장"}</button>
      </div>
      <h3>코드상 발행 안전 상한</h3><p>KST · 전체 {data.operational_limits?.global_daily??"—"}건/일 · 영어는 잔여량 우선 · 활성 6개 블로그 공통 최소 간격 {data.operational_limits?.global_publish_min_interval_minutes??"—"}분</p>
      <ul>{Object.entries(data.operational_limits?.language_daily??{}).map(([code,limit])=><li key={code}>{languageLabel(code)} 일일 {limit??"전역 잔여량"}건 · 시간당 {data.operational_limits?.language_hourly[code]??"—"}건</li>)}</ul>
      <h3>저장된 범위별 설정</h3><ul>{data.mode_policy.settings.map(item=><li key={`${item.scope_type}-${item.scope_key}`}>{item.scope_type}:{item.scope_key||"global"} · {item.configured_mode} · {item.daily_auto_limit}건/일 · {item.minimum_interval_minutes}분</li>)}</ul>
      {notice&&<p role="status">{notice}</p>}
      <button className="secondary-button" disabled={emergencyBusy || data.mode_policy.emergency_stopped} onClick={() => void emergencyStop()}>{data.mode_policy.emergency_stopped ? "긴급 정지 활성" : "긴급 발행 정지"}</button>
      <p>발행 한도는 상한입니다. 이 화면은 Blogger 실제 게시를 수행하지 않습니다.</p>
    </section> : <section className="workspace-panel publication-section">
      <div className="section-heading"><div><h2>{tabs.find(x=>x[0]===view)?.[1]}</h2><p>{shownCount}건 · 최신 대표 버전 기준 · 이전 버전은 원고 상세의 변경 이력에서 확인합니다.</p></div></div>
       <form className="publication-filters" onSubmit={event => { event.preventDefault(); if(searchTimer.current)clearTimeout(searchTimer.current); void refresh(1,view); }}>
         <label>제목·주제 검색<input value={query} onChange={e=>{const next=e.target.value;setQuery(next);if(searchTimer.current)clearTimeout(searchTimer.current);searchTimer.current=setTimeout(()=>void refresh(1,view,next),320);}} placeholder="검색어" /></label>
         <label>언어<select value={language} onChange={event=>{setLanguage(event.target.value);void refresh(1,view,query,{language_code:event.target.value});}}><option value="">모든 언어</option>{data.mode_policy.languages.map(x=><option key={x.code} value={x.code}>{x.display_name || languageLabel(x.code)}</option>)}</select></label>
         <label>블로그<select value={blog} onChange={event=>{setBlog(event.target.value);void refresh(1,view,query,{blog_id:event.target.value});}}><option value="">모든 블로그</option>{data.mode_policy.blogs.map(x=><option key={x.id} value={x.id}>{x.display_name}</option>)}</select></label>
         <label>생성 출처<select value={origin} onChange={event=>{setOrigin(event.target.value);void refresh(1,view,query,{origin:event.target.value});}}><option value="">모든 출처</option>{Object.entries(originLabels).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label>
        <button type="submit" disabled={loading}>검색</button>
      </form>
       {(view!=="published")&&<div className="publication-selection-actions"><label><input type="checkbox" checked={items.length>0&&selection.length===items.length} onChange={event=>setSelection(event.target.checked?items.map(itemKey):[])}/> 현재 페이지 전체 선택</label><span>{selection.length}건 선택</span><button type="button" className="secondary-button" disabled={!selection.length} onClick={()=>openDiscard(items.filter(item=>selection.includes(itemKey(item))))}>{view==="discarded"?"선택 복원":"선택 폐기"}</button></div>}
       {loading ? <div className="publication-skeleton" role="status">목록을 불러오는 중…</div> : items.length ? <div className="publication-table-scroll"><table><thead><tr>{view!=="published"&&<th>선택</th>}<th>원고</th><th>Google Trends 검색량</th><th>생성 출처</th><th>언어</th><th>대상 블로그</th><th>주제·출처</th><th>상태</th><th>시각</th>{view==="published"&&<th>게시 URL</th>}<th>작업</th></tr></thead><tbody>
        {items.map(item=><tr key={`${item.id}-${item.blog_id}`}>
           {view!=="published"&&<td><input type="checkbox" aria-label={`${item.title} 선택`} checked={selection.includes(itemKey(item))} onChange={event=>setSelection(current=>event.target.checked?[...current,itemKey(item)]:current.filter(key=>key!==itemKey(item)))}/></td>}
          <td>{item.import_id
            ? <button type="button" className="import-title" onClick={()=>openManuscript(item)}>{item.title || "제목 없음"}</button>
            : item.evaluation_id
              ? <a href={`/manuscripts?open_evaluation_id=${encodeURIComponent(item.evaluation_id)}&open_content_version_id=${encodeURIComponent(item.content_version_id)}&return_to=${encodeURIComponent(`/publishing?view=${view}&page=${page}&q=${query}&language_code=${language}&blog_id=${blog}`)}`}>{item.title || "제목 없음"}</a>
              : <span>{item.title || "제목 없음"}</span>}
            <small>현재 버전 {item.content_version_id.slice(0,8)} <span className={`publication-mobile-origin publication-origin publication-origin-${item.origin_kind??"unknown"}`}>{originLabels[item.origin_kind??"unknown"]}</span></small>
            {item.automation_id&&<small>Automation {item.automation_id} · {item.scheduled_slot??item.occurrence_id??"예약 슬롯 미확인"}</small>}{item.trend_request_id&&<small>Trends 회차 {item.trend_request_id}</small>}
            {item.origin_kind==="google_trends"&&<small>Trends 검색어 {item.trends_search_query||"정보 없음"}{item.trends_search_country?` · ${item.trends_search_country}`:""}</small>}
            {view==="discarded"&&<small>폐기 전 {item.previous_view??"미확인"} · {item.discard_actor??"작업자 미확인"} · {item.discard_reason??"사유 미확인"}</small>}
            {item.published_title && <small>게시 당시 제목: {item.published_title} · 게시 버전 {item.published_content_version_id?.slice(0,8)} · 현재 Blogger 제목은 별도 원격 확인이 필요합니다.</small>}</td>
          <td className="publication-trends-volume" data-label="Google Trends 검색량">{item.origin_kind==="google_trends"?<><strong>{item.trends_search_volume_raw||"정보 없음"}</strong><small title={item.trends_search_volume_kind||"Google Trends 원본 구간 표기입니다."}>원본 구간 · 정확한 검색 횟수 아님</small></>:"—"}</td>
           <td className="publication-desktop-origin"><span className={`publication-origin publication-origin-${item.origin_kind??"unknown"}`}>{originLabels[item.origin_kind??"unknown"]}</span></td><td>{languageLabel(item.language_code)}</td><td>{item.blog_name || item.url}</td>
          <td>{item.topic || item.source_names || "주제·출처 정보 없음"}</td>
          <td>{statusLabel(item.status)}{item.failure_reason_code && <small>실패 단계 {item.failure_stage ?? "미확인"} · {publicationReasonText(item.failure_reason_code)}</small>}{item.retry_count !== undefined && <small>재시도 {item.retry_count}회</small>}{item.eligibility_reasons?.length ? <small>{publicationReasonsText(item.eligibility_reasons)}</small> : null}{item.simulation_only && <small>모의 작업</small>}</td>
          <td>{kst(item.next_publish_at || item.created_at)}</td>
          {view==="published"&&<td>{item.remote_url&&item.remote_status==="LIVE"&&item.remote_verified_at?<a href={item.remote_url} target="_blank" rel="noreferrer">게시물 열기</a>:"원격 게시 확인 없음"}{item.remote_post_id&&<small>postId {item.remote_post_id}</small>}</td>}
            <td>{view==="published"?"이력 보존":<div className="publication-row-actions">{view!=="discarded"&&item.import_id&&(item.manual_publication_available||view==="auto_failure"||view==="review"||view==="held")&&<button type="button" className="secondary-button" disabled={quickPublishLoading||quickPublishBusy} onClick={()=>void openQuickPublish(item)}>{quickPublishLoading?"발행 요청 중…":"수동 발행"}</button>}<button type="button" className="secondary-button" onClick={()=>openDiscard([item])}>{view==="discarded"?"복원":"폐기"}</button></div>}</td>
        </tr>)}
      </tbody></table></div> : <p className="empty-state">이 상태의 원고가 없습니다.</p>}
      <div className="publication-pagination"><button disabled={page<=1||loading} onClick={()=>void refresh(page-1,view)}>이전</button><span>{page} / {Math.max(data.page_count ?? 0,1)}</span><button disabled={page>=(data.page_count??0)||loading} onClick={()=>void refresh(page+1,view)}>다음</button></div>
     </section>}
     </>}
     {discardTargets.length>0&&<div className="publication-discard-backdrop" role="presentation"><section role="dialog" aria-modal="true" aria-label={view==="discarded"?"원고 복원 확인":"원고 폐기 확인"} className="workspace-panel publication-discard-dialog">
       <h2>{view==="discarded"?"선택 원고 복원":"선택 원고 폐기"}</h2><p>{discardTargets.length}건 · 기존 Version·Job·감사 기록은 보존됩니다. {view==="discarded"?"복원해도 Job은 다시 실행되지 않습니다.":"Blogger에 이미 시작된 쓰기는 취소를 보장할 수 없습니다."}</p>
       <ul>{discardTargets.map(item=><li key={itemKey(item)}>{item.title} · {item.blog_name||item.url} · {originLabels[item.origin_kind??"unknown"]} · {statusLabel(item.status)}</li>)}</ul>
       <label>작업자<input value={discardActor} onChange={event=>setDiscardActor(event.target.value)} /></label>
       <label>사유 (10자 이상)<textarea value={discardReason} onChange={event=>setDiscardReason(event.target.value)} rows={3} /></label>
       {error&&<p role="alert" className="quality-held">{error}</p>}
       <div className="publication-discard-actions"><button type="button" className="secondary-button" disabled={discardBusy} onClick={()=>setDiscardTargets([])}>취소</button><button type="button" disabled={discardBusy||discardActor.trim().length<2||discardReason.trim().length<10} onClick={()=>void submitDiscard()}>{discardBusy?"처리 중…":view==="discarded"?"선택 복원":"선택 폐기"}</button></div>
     </section></div>}
  </div>;
}
