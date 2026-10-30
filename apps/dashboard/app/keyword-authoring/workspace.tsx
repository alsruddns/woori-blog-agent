"use client";
import {useEffect,useRef,useState,type FormEvent} from "react";
import ExternalImportWorkspace from "../imports/external-import-workspace";
import {DEFAULT_KEYWORD_AUTHORING_DIRECTION,KEYWORD_AUTHORING_PROMPT_VERSION} from "./default-prompt";

type Blog={id:string;display_name:string;language_code:string;target_country:string};
type Cap={engine:{available:boolean;model:string;error_code?:string;version?:string};blogs:Blog[];categories:{slug:string;name_ko:string}[]};
type Job={id:string;keyword:string;state:string;blog_id:string;language_code:string;model:string;execution_id?:string;error_code?:string;created_at:string;import_id?:string;content_version_id?:string};
const states:Record<string,string>={queued:"대기",researching:"Codex 조사 중",writing:"원고 작성 중",validating:"JSON 검증 중",import_pending:"Worker Import 대기",imported_review:"Import 완료 · 사용자 검토 대기",failed:"작성 실패",cancelled:"취소"};
const errors:Record<string,string>={codex_not_installed:"Codex CLI가 설치되지 않았습니다.",codex_chatgpt_login_required:"Codex에서 ChatGPT 로그인을 완료하세요.",codex_billable_credentials_present:"API 키·과금 자격 증명 때문에 실행을 차단했습니다.",codex_usage_limit:"Codex 사용 한도에 도달했습니다. 결제로 전환하지 않습니다.",codex_timeout:"실행 제한 시간을 초과했습니다.",source_not_opened_in_this_run:"출처의 실제 열기를 확인하지 못했습니다.",web_research_not_observed:"실제 웹 조사 기록을 확보하지 못했습니다.",json_schema_invalid:"원고 JSON 검증에 실패했습니다.",worker_interrupted:"Worker 종료로 실행이 중단됐습니다.",codex_execution_failed:"Codex 실행이 실패했습니다. 로그인과 사용 한도를 확인하세요.",codex_config_unsupported:"설치된 Codex가 안전 실행 설정을 지원하지 않습니다."};
export default function KeywordAuthoring(){
  const [cap,setCap]=useState<Cap|null>(null),[jobs,setJobs]=useState<Job[]>([]),[error,setError]=useState("");
  const [keyword,setKeyword]=useState(""),[direction,setDirection]=useState(DEFAULT_KEYWORD_AUTHORING_DIRECTION),[blog,setBlog]=useState(""),[category,setCategory]=useState("technology");
  const [articleType,setArticleType]=useState("news_analysis"),[length,setLength]=useState("default"),[range,setRange]=useState("latest"),[from,setFrom]=useState(""),[to,setTo]=useState("");
  const [busy,setBusy]=useState(false),[accepted,setAccepted]=useState(false),[selected,setSelected]=useState<{id:string;version:string;target:string;publish:boolean;nonce:number}>();
  const key=useRef("");const posting=useRef(false);
  async function load(){const r=await fetch("/api/keyword-authoring",{cache:"no-store"});if(!r.ok)throw new Error(`요청 목록 조회 실패 HTTP ${r.status}`);const d=await r.json();setJobs(d.items??[]);}
  useEffect(()=>{
    let active=true,pending=false;const controller=new AbortController();
    void fetch("/api/keyword-authoring/capabilities",{cache:"no-store",signal:controller.signal}).then(async r=>{if(!r.ok)throw new Error(`작성 기능 조회 실패 HTTP ${r.status}`);const d=await r.json() as Cap;if(active){setCap(d);setBlog(d.blogs[0]?.id??"");}}).catch(e=>{if(active)setError(String(e));});
    const poll=async()=>{if(pending||document.visibilityState!=="visible")return;pending=true;try{const r=await fetch("/api/keyword-authoring",{cache:"no-store",signal:controller.signal});if(!r.ok)throw new Error(`요청 목록 조회 실패 HTTP ${r.status}`);const d=await r.json();if(active)setJobs(d.items??[]);}catch(e){if(active)setError(String(e));}finally{pending=false;}};
    void poll();const timer=setInterval(()=>void poll(),5000);const visible=()=>void poll();document.addEventListener("visibilitychange",visible);
    return()=>{active=false;controller.abort();clearInterval(timer);document.removeEventListener("visibilitychange",visible);};
  },[]);
  const target=cap?.blogs.find(b=>b.id===blog);
  async function submit(event:FormEvent){event.preventDefault();if(posting.current||accepted)return;posting.current=true;setBusy(true);setError("");if(!key.current)key.current=crypto.randomUUID();try{
    const r=await fetch("/api/keyword-authoring",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({request_key:key.current,blog_id:blog,keyword,direction,direction_prompt_version:KEYWORD_AUTHORING_PROMPT_VERSION,category,article_type:articleType,length,research_range:range,date_from:range==="custom"?from:null,date_to:range==="custom"?to:null})});
    const d=await r.json();if(!r.ok)throw new Error(`HTTP ${r.status} · ${typeof d.detail==="string"?d.detail:d.error??"입력값 또는 로컬 API를 확인하세요."}`);setAccepted(true);await load();
  }catch(e){setError(String(e));}finally{posting.current=false;setBusy(false);}}
  async function action(job:Job,name:"cancel"|"retry") {if(posting.current)return;posting.current=true;setBusy(true);setError("");try{const r=await fetch(`/api/keyword-authoring/${job.id}/${name}`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({request_key:crypto.randomUUID()})});const d=await r.json();if(!r.ok)throw new Error(String(d.detail??d.error??`HTTP ${r.status}`));await load();}catch(e){setError(String(e));}finally{posting.current=false;setBusy(false);}}
  return <>
    {error&&<p className="quality-held" role="alert">{error}</p>}
    <section className="workspace-panel"><h2>작성 요청</h2><p>{cap?`${cap.engine.version??"Codex"} · ${cap.engine.model} · ${cap.engine.available?"ChatGPT 로그인 확인":"실행 불가: "+(errors[cap.engine.error_code??""]??cap.engine.error_code)}`:"실행 환경 확인 중…"}</p>
      <form className="keyword-authoring-form" onSubmit={submit}>
        <label>작성 키워드<input required minLength={2} maxLength={300} value={keyword} onChange={e=>setKeyword(e.target.value)} disabled={accepted}/></label>
        <label>추가 요청·작성 방향<textarea data-testid="keyword-authoring-direction" className="keyword-authoring-direction" maxLength={10000} value={direction} onChange={e=>setDirection(e.target.value)} disabled={accepted}/></label>
        <div className="import-actions"><small>기본 프롬프트 {KEYWORD_AUTHORING_PROMPT_VERSION} · {direction.length.toLocaleString("ko-KR")}자</small><button type="button" className="secondary-button" disabled={busy||accepted} onClick={()=>setDirection(DEFAULT_KEYWORD_AUTHORING_DIRECTION)}>기본 프롬프트 복원</button></div>
        <div className="keyword-authoring-grid"><label>대상 Blogger<select required value={blog} onChange={e=>setBlog(e.target.value)} disabled={accepted}>{cap?.blogs.map(b=><option key={b.id} value={b.id}>{b.display_name} · {b.language_code}/{b.target_country}</option>)}</select></label>
          <label>작성 언어<input readOnly value={target?.language_code??""}/></label>
          <label>원고 유형<select value={articleType} onChange={e=>setArticleType(e.target.value)} disabled={accepted}><option value="news_analysis">뉴스·해설</option><option value="deep_analysis">심층 분석</option><option value="guide">정보 가이드</option></select></label>
          <label>카테고리<select value={category} onChange={e=>setCategory(e.target.value)} disabled={accepted}>{cap?.categories.map(c=><option key={c.slug} value={c.slug}>{c.name_ko}</option>)}</select></label>
          <label>기사 분량<select value={length} onChange={e=>setLength(e.target.value)} disabled={accepted}><option value="default">기본</option><option value="detailed">상세</option></select></label>
          <label>자료 조사 범위<select value={range} onChange={e=>setRange(e.target.value)} disabled={accepted}><option value="latest">최신</option><option value="custom">사용자 지정 기간</option></select></label>
          {range==="custom"&&<><label>조사 시작일<input required type="date" value={from} onChange={e=>setFrom(e.target.value)} disabled={accepted}/></label><label>조사 종료일<input required type="date" min={from} value={to} onChange={e=>setTo(e.target.value)} disabled={accepted}/></label></>}
        </div><div className="import-actions"><button disabled={busy||accepted||!cap?.engine.available}>{busy?"요청 처리 중…":accepted?"요청 등록됨":"Codex 원고 작성 요청"}</button><button type="button" className="secondary-button" disabled={busy} onClick={()=>{key.current="";setAccepted(false);setError("");setDirection(DEFAULT_KEYWORD_AUTHORING_DIRECTION);}}>새 요청</button></div>
        <p>ChatGPT/Codex 사용 한도를 사용합니다. API 키·유료 대체 공급자·자동 공개 발행을 사용하지 않습니다. 사용 한도·근거 부족·검증 실패는 실패 사유로 보존됩니다.</p>
      </form>
    </section>
    <section className="workspace-panel"><div className="section-heading"><h2>최근 작성 요청</h2><button type="button" className="secondary-button" onClick={()=>void load().catch(e=>setError(String(e)))}>상태 새로고침</button></div><p>화면 표시 중 5초마다 실제 상태를 조회합니다. 원고는 Import 후 사용자 검토 대기 상태입니다.</p>
      {!jobs.length?<p className="empty-state">작성 요청이 없습니다.</p>:<div className="keyword-job-grid">{jobs.map(job=><article className="history-card" key={job.id}><h3>{job.keyword}</h3><p className="status-badge">{states[job.state]??job.state}</p><p>{job.language_code} · {job.model} · {new Intl.DateTimeFormat("ko-KR",{dateStyle:"short",timeStyle:"medium",timeZone:"Asia/Seoul"}).format(new Date(job.created_at))} KST</p><small className="worker-monitor-id">요청 {job.id}</small>{job.error_code&&<p className="quality-held">{errors[job.error_code]??job.error_code}</p>}
        <div className="import-actions">{job.import_id?<button type="button" onClick={()=>setSelected(previous=>({id:job.import_id!,version:job.content_version_id??"",target:job.blog_id,publish:false,nonce:(previous?.nonce??0)+1}))}>원고 검토·수정</button>:!['failed','cancelled'].includes(job.state)?<button type="button" className="secondary-button" disabled={busy} onClick={()=>void action(job,"cancel")}>작성 취소</button>:<button type="button" className="secondary-button" disabled={busy} onClick={()=>void action(job,"retry")}>다시 작성</button>}</div></article>)}</div>}
    </section>
    <ExternalImportWorkspace embedded detailRequest={selected}/>
  </>;
}
