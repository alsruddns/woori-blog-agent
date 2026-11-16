import Link from "next/link";
import type { ReactNode } from "react";

export type Snapshot = {
  trends?: { observations_last_24h?: number; last_collected_at?: string | null; regions?: Array<{ geo?: string; observations?: number; last_collected_at?: string }> };
  trend_pipeline?: { unique_issue_groups_24h?: number; article_candidates?: number; research_packages_24h?: number };
  scheduled_import?: { worker_status?: string; received_total?: number; imported_total?: number; rejected_total?: number; last_received_at?: string; verified_gpt_runs?: number; local_file_probe_runs?: number; scheduled_article_imports?: number };
  generation?: { provider_connected?: boolean; provider_status?: string; codex_scheduled_export_supported?: boolean; counts?: Record<string, number>; queue_waiting?: number };
  quality?: { machine_passed?: number; held?: number; failed?: number; human_review_required?: number };
  publishing?: { jobs?: Record<string, number>; recorded_posts?: number; last_recorded_at?: string; queued_mock_jobs?: number; live_queued_jobs?: number; recent_public_url?: string | null; latest_publication?: { title?:string; remote_url?:string; remote_post_id?:string; remote_verified_at?:string } | null; live_writes_enabled?: boolean; auto_enabled?: boolean; configured_global_mode?: string; emergency_stopped?: boolean; daily?: { published?: number; reserved?: number; global_limit?: number } };
  monitoring?: { workers?: Array<{service:string;status:string;last_seen_at?:string|null;last_error_category?:string|null}>; alerts?: Array<{severity:string;message:string}>; overall?:string };
  recent_activity?: Array<{event_type:string;created_at:string;stage?:string;target?:string|null;outcome?:string|null;error_category?:string|null}>;
  publication_policy?: { daily_limit?:number; hourly_limit?:Record<string,number>; emergency_stopped?:boolean };
};
const kst=(v?:string|null)=>v?new Intl.DateTimeFormat("ko-KR",{timeZone:"Asia/Seoul",dateStyle:"medium",timeStyle:"short"}).format(new Date(v))+" KST":"기록 없음";
const label=(s?:string)=>({running:"실행 중",stale:"heartbeat 지연",not_started:"미실행",inactive:"비활성",partial:"일부 확인",blocked:"차단",normal:"정상",warning:"주의"}[s??""]??s??"확인 필요");
function Stage({number,title,status,children}:{number:number;title:string;status:string;children:ReactNode}){return <article className="automation-stage"><div className="automation-stage-heading"><span>{number}</span><div><h2>{title}</h2><small>{status}</small></div></div>{children}</article>}
export default function AutomationDashboard({data}:{data:Snapshot|null}){
 if(!data)return <section className="workspace-panel"><p role="alert">운영 상태 API에서 정보를 가져오지 못했습니다.</p></section>;
 const research=data.trend_pipeline??{}; const imp=data.scheduled_import??{}; const pub=data.publishing??{};
 const worker=(name:string)=>data.monitoring?.workers?.find(x=>x.service===name);
 const recent=data.recent_activity??[];
 return <div className="automation-dashboard">
  <section className="automation-overview"><div><span>운영 모드</span><strong>{pub.configured_global_mode??"manual"} · Auto {pub.auto_enabled?"ON":"OFF"}</strong></div><div><span>오늘 실제 게시</span><strong>{pub.daily?.published??pub.recorded_posts??0} / {pub.daily?.global_limit??data.publication_policy?.daily_limit??50}</strong></div><div><span>수집 Worker</span><strong>{label(worker("research_worker")?.status)}</strong></div><div><span>발행 Worker</span><strong>{label(worker("publication_worker")?.status)}</strong></div></section>
  <section className="automation-stages" aria-label="자동화 처리 단계">
   <Stage number={1} title="자료 수집" status={label(worker("research_worker")?.status)}><p>최근 관측 {data.trends?.observations_last_24h??0}건 · 고유 이슈 {research.unique_issue_groups_24h??0}개</p><p>기사 후보 {research.article_candidates??0}개</p><p>마지막 수집 {kst(data.trends?.last_collected_at)}</p><p>Worker heartbeat {kst(worker("research_worker")?.last_seen_at)}</p><ul className="automation-regions">{(data.trends?.regions??[]).map(item=><li key={item.geo}>{item.geo}: {item.observations}건 · {kst(item.last_collected_at)}</li>)}</ul></Stage>
   <Stage number={2} title="공식 자료·원고" status={data.generation?.codex_scheduled_export_supported?"Codex 예약 파일 작성 허용 · 앱 Provider 미연결":data.generation?.provider_connected?"연결됨":"AI 원고 Provider 미연결"}><p>Research Package {research.research_packages_24h??0}건</p><p>예약 로컬 파일 probe {imp.local_file_probe_runs??0}회 · 예약 원고 Import {imp.scheduled_article_imports??0}건</p><p>파일 수신 {imp.received_total??0}건 · Import {imp.imported_total??0}건 · 거절 {imp.rejected_total??0}건</p><p>마지막 수신 {kst(imp.last_received_at)}</p><p>현재 in-process Provider: {data.generation?.provider_status??"미설정"}</p></Stage>
   <Stage number={3} title="품질 검증" status="기계 검사와 사람 검토 분리"><p>기계 검사 통과 {data.quality?.machine_passed??0}건</p><p>검토 필요 {data.quality?.human_review_required??0}건 · 보류 {data.quality?.held??0}건 · 실패 {data.quality?.failed??0}건</p><p>자동 적격은 검증 증거와 별도 운영 정책을 모두 확인합니다.</p><Link href="/publishing">발행 검토 목록</Link></Stage>
   <Stage number={4} title="Blogger 발행" status={pub.live_writes_enabled?"실제 쓰기 허용":"실제 쓰기 차단"}><p>실제 공개 게시 기록 {pub.recorded_posts??0}건</p><p>실제 발행 대기 {pub.live_queued_jobs??0}건 · 모의 작업 {pub.queued_mock_jobs??0}건</p><p>마지막 게시 {kst(pub.last_recorded_at)}</p>{pub.latest_publication?.remote_url&&<p><a href={pub.latest_publication.remote_url} target="_blank" rel="noreferrer">최근 게시: {pub.latest_publication.title||pub.latest_publication.remote_post_id}</a></p>}<p>긴급 정지 {pub.emergency_stopped?"활성":"해제"} · Auto {pub.auto_enabled?"ON":"OFF"}</p><Link href="/publishing">발행 관리</Link></Stage>
  </section>
  <section className="workspace-panel automation-recent"><div className="section-heading"><div><h2>최근 운영 실행</h2><p>감사 로그에서 단계·대상·결과를 안전한 필드만 골라 표시합니다.</p></div></div>{recent.length?<ul>{recent.map((item,index)=><li key={`${item.event_type}-${item.created_at}-${index}`}><div><strong>{item.stage||"운영 상태"}</strong><span>{item.target||item.event_type}{item.outcome?` · ${item.outcome}`:""}{item.error_category?` · 사유 ${item.error_category}`:""}</span></div><time>{kst(item.created_at)}</time></li>)}</ul>:<p className="empty-state">최근 실행 기록이 없습니다.</p>}</section>
  <footer className="automation-links"><Link href="/config">언어·블로그 설정</Link><Link href="/blogger">Blogger 연결</Link><Link href="/operations">운영 진단</Link></footer>
 </div>;
}
