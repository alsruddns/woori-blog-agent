"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

type Job = {
  blog_id?: string; job_id: string | null; import_id?: string | null; content_version_id?: string;
  title: string; blog_name: string; publication_lane: string; generation_method?: string;
  state: string; registered_at?: string; started_at?: string; updated_at?: string;
  progress_at?: string; progress_event?: string; live_stage?: string; retry_count: number;
  available_at?: string; lease_overdue?: boolean; failure_stage?: string; failure_reason?: string; retry_possible?: boolean; remote_url?: string;
};
type Monitor = {
  period_label: string; as_of: string; counts: Record<string,number>; items: Job[];
  worker_state: string; worker: {process_id:number; last_seen_at:string; execution_mode?:string} | null;
  last_job: {title:string; status:string; publication_state:string} | null;
  page: number; page_count:number; total:number;
};
const labels: Record<string,string> = {all:"전체",queued:"Job 대기",running:"처리 중",published:"Blogger 공개 완료",failed:"실패·보류 Job",pre_job_failure:"Job 생성 전 자동발행실패"};
const stages: Record<string,string> = {draft_needed:"초안 생성 단계",draft_created:"공개 전 확인·발행 간격 대기",published:"공개 확인 완료",eligibility:"발행 자격 평가",duplicate_check:"중복 확인",publication_worker:"Worker 처리",create_draft:"Blogger 초안 생성",publish_draft:"Blogger 공개 요청"};
const reasons: Record<string,string> = {claim_source_verification_unavailable:"주장 출처 수집·확인 필요",claim_span_not_found_in_live_source_evidence:"원문 근거 구간 불일치",no_supported_body_after_sanitization:"게시 가능한 근거 본문 부족",publication_policy_missing:"대상 발행 정책 없음",remote_duplicate_found:"기존 게시물 확인됨",remote_duplicate_check_unknown:"원격 중복 확인 필요",not_found:"대상 리소스 없음",unauthorized:"OAuth 인증 확인 필요",permission_denied:"Blogger 권한 확인 필요",uncertain_write:"원격 게시 결과 확인 필요"};
const intervalReasons:Record<string,string> = {account_minimum_interval_not_elapsed:"OAuth \uC5F0\uACB0 \uACF5\uC720 \uACC4\uC815 2\uBD84 \uAC04\uACA9 \uB300\uAE30",blog_minimum_interval_not_elapsed:"Blogger 5\uBD84 \uAC04\uACA9 \uB300\uAE30"};
const time = (value?:string) => value ? new Intl.DateTimeFormat("ko-KR",{timeZone:"Asia/Seoul",dateStyle:"short",timeStyle:"medium"}).format(new Date(value))+" KST" : "기록 없음";

export default function PublicationWorkerPanel({refreshKey=0,onOpenImport}:{refreshKey?:number;onOpenImport?:(job:Job)=>void}) {
  const [data,setData]=useState<Monitor|null>(null);
  const [view,setView]=useState("all"); const [page,setPage]=useState(1);
  const [refresh,setRefresh]=useState(0); const [busy,setBusy]=useState(false); const [error,setError]=useState("");
  useEffect(()=>{
    let disposed=false; let pending=false; let controller:AbortController|null=null;
    async function load() {
      if(disposed || pending || document.visibilityState!=="visible") return;
      pending=true; controller=new AbortController(); setBusy(true);
      try {
        const response=await fetch(`/api/publications/worker-jobs?view=${view}&page=${page}`,{cache:"no-store",signal:controller.signal});
        if(!response.ok) throw new Error(`Job 상태 조회 실패 (HTTP ${response.status})`);
        const result=await response.json() as Monitor;
        if(!disposed){setData(result);setError("");}
      }catch(cause){if(!disposed && !(cause instanceof DOMException && cause.name==="AbortError"))setError(cause instanceof Error?cause.message:"Job 조회 실패");}
      finally{pending=false;if(!disposed)setBusy(false);}
    }
    const visibility=()=>{if(document.visibilityState==="hidden")controller?.abort();else void load();};
    void load(); const interval=setInterval(()=>void load(),10000);
    document.addEventListener("visibilitychange",visibility);
    return ()=>{disposed=true;clearInterval(interval);controller?.abort();document.removeEventListener("visibilitychange",visibility);};
  },[view,page,refresh,refreshKey]);
  return <section className="workspace-panel publication-worker-monitor" aria-labelledby="worker-monitor-title">
    <div className="section-heading"><div><h2 id="worker-monitor-title">Publication Worker · 실제 발행 Job</h2><p>{data?.period_label??"실제 Job 조회 중"} · 화면 표시 중 10초마다 갱신</p></div><button type="button" className="secondary-button" disabled={busy} onClick={()=>setRefresh(x=>x+1)}>{busy?"조회 중…":"상태 새로고침"}</button></div>
    {error&&<p className="quality-held" role="alert">{error} · 마지막 정상 조회 결과를 표시합니다.</p>}
    {!data?<p className="loading-state" role="status">Worker와 Job 상태를 불러오는 중입니다.</p>:<>
      <div className="publishing-summary" aria-label="실제 Job 집계">{Object.keys(labels).filter(x=>x!=="all").map(key=><article key={key}><span>{labels[key]}</span><strong>{data.counts[key].toLocaleString()}건</strong></article>)}</div>
      <div className="worker-monitor-status"><p><strong>Worker {({running:"실행 중",stopped:"중지·실행 기록 없음",stale:"heartbeat 지연"} as Record<string,string>)[data.worker_state]}</strong> · 처리 중 Job {data.counts.running}건</p><p>PID {data.worker?.process_id??"기록 없음"} · 모드 {data.worker?.execution_mode?.replace(/^operations-/,"")??"기록 없음"}</p><p>마지막 heartbeat {time(data.worker?.last_seen_at)} · 조회 {time(data.as_of)}</p><p>마지막 Job 결과: {data.last_job?`${data.last_job.title} · ${labels[data.last_job.publication_state]??labels[data.last_job.status]??data.last_job.publication_state}`:"처리 기록 없음"}</p></div>
      <div className="worker-monitor-filters"><label>Job 상태 <select value={view} onChange={e=>{setView(e.target.value);setPage(1);}}>{Object.entries(labels).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label><span>{data.total.toLocaleString()}건 · {data.page}/{data.page_count}페이지</span></div>
      {!data.items.length?<p className="empty-state">이 상태에 해당하는 실제 Job 또는 생성 전 실패 기록이 없습니다.</p>:<div className="publication-table-scroll"><table><thead><tr><th>원고·Blogger</th><th>생성·발행 경로</th><th>Job·상태</th><th>시각·진행</th><th>재시도·실패 사유</th></tr></thead><tbody>{data.items.map((job,index)=><tr key={job.job_id??`${job.import_id}-${index}`}>
        <td>{job.import_id && onOpenImport ? <button type="button" className="import-title worker-monitor-title" title={job.title} onClick={()=>onOpenImport(job)}>{job.title}</button> : job.import_id?<Link className="worker-monitor-title" title={job.title} href={`/imports?open_import_id=${encodeURIComponent(job.import_id)}&open_content_version_id=${encodeURIComponent(job.content_version_id??"")}`}>{job.title}</Link>:<span className="worker-monitor-title" title={job.title}>{job.title}</span>}<small>{job.blog_name}</small>{job.remote_url&&<a href={job.remote_url} target="_blank" rel="noreferrer">공개 글 보기</a>}</td>
        <td>{job.generation_method==="chatgpt_scheduled_export"?"Codex 예약":job.generation_method==="manual_codex_import"?"수동 Import":"기타 원고"}<small>{job.publication_lane==="manual"?"사용자 수동 발행":"예약 Auto 발행"}</small></td>
        <td><span className={`status-badge ${job.state==="failed"||job.state==="pre_job_failure"?"status-warning":""}`}>{job.state==="queued" && job.failure_reason?.includes("minimum_interval") ? "\uBC1C\uD589 \uAC04\uACA9 \uB300\uAE30" : labels[job.state]}</span><small className="worker-monitor-id">{job.job_id??"Job 생성 전 차단"}</small>{job.live_stage&&<small>{stages[job.live_stage]??job.live_stage}</small>}{job.lease_overdue&&<small>처리 임대 시간 경과 · 진행 기록 확인 필요</small>}</td>
        <td><small>등록 {time(job.registered_at)}</small><small>처리 시작 {time(job.started_at)}</small><small>상태 변경 {time(job.updated_at)}</small>{job.state==="queued" && job.available_at && <small>{"\uB2E4\uC74C \uCC98\uB9AC \uAC00\uB2A5 "}{time(job.available_at)}</small>}{job.progress_at&&<small>마지막 진행 기록 {time(job.progress_at)}</small>}</td>
        <td>{job.retry_count}회{job.failure_reason&&<><small>{stages[job.failure_stage??""]??"실패 단계 확인 필요"} · {intervalReasons[job.failure_reason]??reasons[job.failure_reason]??"원고 상세에서 원인을 확인하세요."}</small><details><summary>기술 코드</summary><code className="worker-monitor-id">{job.failure_reason}</code></details></>}{job.state==="failed"&&<small>{job.retry_possible?"재시도 여지 있음 · 기존 정책에 따라 처리":"재시도 전 원격 결과·정책 확인 필요"}</small>}{job.state==="pre_job_failure"&&<small>Job 미등록 · 원고 상세에서 보완·수동 발행 검토</small>}</td>
      </tr>)}</tbody></table></div>}
      {data.page_count>1&&<div className="worker-monitor-filters"><button className="secondary-button" disabled={page<=1||busy} onClick={()=>setPage(x=>x-1)}>이전</button><button className="secondary-button" disabled={page>=data.page_count||busy} onClick={()=>setPage(x=>x+1)}>다음</button></div>}
    </>}
  </section>;
}
