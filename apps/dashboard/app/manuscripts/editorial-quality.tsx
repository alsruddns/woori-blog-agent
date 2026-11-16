"use client";
import { useCallback, useEffect, useState } from "react";
import styles from "./editorial-quality.module.css";

type Suggestion = {id:string;category:string;field:string;location:string;original:string;proposal:string|null;reason:string;expected_effect:string;automatic:boolean;fact_check_required:boolean};
type Report = {id:string;import_version_id:string;content_version_id:string;engine_version:string;stage:string;status:string;created_at:string;result:{scores?:Record<string,number|null>;overall_score?:number|null;measured_score?:number;measured_weight?:number;suggestions?:Suggestion[];evidence?:{verified_claims:number|null;unverified_claims:number;source_count:number;source_original_examined:boolean};checks?:Record<string,boolean>;error_code?:string;rationale?:string}};
type Version = {id:string;version_number:number;title:string};
type Data = {reports:Report[];current_engine_version?:string;link:{import_id:string;import_version_id:string}|null;events:{suggestion_id:string;action:string;report_id:string}[];versions:Version[];selection:{id:string;geo:string;score:number;engine_version:string}[];native_editorial_version:unknown};
const names:Record<string,string>={caution:"사실 표현",substance:"내용 충실도",analysis:"분석 깊이",seo:"SEO",readability:"가독성",localization:"현지화",structure:"기사 구조"};
const failures:Record<string,string>={codex_usage_limit:"Codex 사용량 제한으로 보류됐습니다. 실제 초기화 시각은 확인되지 않았습니다.",codex_timeout:"평가 제한 시간을 초과했습니다.",review_introduced_unverified_number_or_url:"수치·URL 대조 검사에서 보류됐습니다. 저장 응답을 다시 검사할 수 있습니다.",codex_deep_review_failed:"심층 평가를 완료하지 못했습니다."};
const base="/api/research/editorial-intelligence";
async function api(path:string,method="GET",body?:unknown){const r=await fetch(base+path,{method,headers:{"Content-Type":"application/json"},body:body===undefined?undefined:JSON.stringify(body),cache:"no-store"});const d=await r.json();if(!r.ok)throw new Error(d.detail??d.error??`HTTP ${r.status}`);return d;}

export default function EditorialQuality({contentVersionId,onChanged}:{contentVersionId:string;onChanged?:()=>void}){
  const [data,setData]=useState<Data|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState(""),[notice,setNotice]=useState(""),[revision,setRevision]=useState(0),[selected,setSelected]=useState<string[]>([]),[confirmed,setConfirmed]=useState(false),[before,setBefore]=useState(""),[after,setAfter]=useState(""),[diff,setDiff]=useState<Record<string,{diff:string[]}>|null>(null);
  useEffect(()=>{let active=true;api(`/versions/${contentVersionId}`).then((d:Data)=>{if(!active)return;setData(d);setSelected([]);setConfirmed(false);setDiff(null);setError("");setBefore(d.versions[1]?.id??d.versions[0]?.id??"");setAfter(d.versions[0]?.id??"");}).catch(e=>{if(active)setError(String(e));});return()=>{active=false;};},[contentVersionId,revision]);
  const run=useCallback(async(fn:()=>Promise<unknown>)=>{setBusy(true);setError("");setNotice("");try{await fn();setRevision(v=>v+1);}catch(e){setError(String(e));}finally{setBusy(false);}},[]);
  const currentReports=data?.reports.filter(r=>!data.current_engine_version||r.engine_version===data.current_engine_version);
  const report=currentReports?.find(r=>r.stage==="codex"&&r.status==="completed")??currentReports?.find(r=>r.stage==="static"&&r.status==="completed");
  const r=report?.result,importId=data?.link?.import_id;
  const latest=data?.versions[0]?.id===data?.link?.import_version_id;
  async function act(action:string,ids:string[]){if(!report)return;await api(`/reports/${report.id}/suggestions`,"POST",{suggestion_ids:ids,action,explicit_confirmation:confirmed,manual_review_confirmed:confirmed});if(action==="apply"){setNotice("선택한 제안을 새 Content Version에 저장했습니다. 최신 원고를 다시 열어 확인하세요.");onChanged?.();}}
  return <section className={styles.panel} aria-label="원고 품질 자동 평가" data-testid="editorial-quality"><h3>원고 품질 자동 평가</h3>
    <p>평가는 표시된 저장 버전에 연결됩니다. 점수는 편집 보조 지표이며 사실·권리 검증이나 게시 승인이 아닙니다.</p>
    {error&&<p role="alert">{error}</p>}{notice&&<p role="status">{notice}</p>}
    {!data&&!error&&<p role="status">품질 평가 조회 중…</p>}
    {data&&!importId&&<p>이 원고는 Codex Import 버전과 연결되지 않아 자동 평가 대상이 아닙니다. 기존 품질 기록을 확인하세요.</p>}
    {data?.native_editorial_version? <p>별도의 편집 버전이 있습니다. 아래 평가는 Import 원본 버전만 평가한 결과입니다. 편집본과 혼동하지 않도록 변경 이력도 확인하세요.</p>:null}
    {importId&&<><div className="toolbar"><button disabled={busy||!latest} onClick={()=>void run(()=>api(`/imports/${importId}/evaluate`,"POST",{}))}>정적 평가 실행</button><button disabled={busy||!latest} onClick={()=>void run(()=>api(`/imports/${importId}/deep-review`,"POST",{}))}>Codex 심층 평가 요청</button></div><p>심층 평가는 수동 요청으로만 실행하며, 동일 버전·엔진의 성공 결과를 재사용합니다. 작성 큐 우선·동시 실행 1개·시간당 3회 상한을 적용합니다.</p>
      {!latest&&<p>과거 버전입니다. 평가는 조회만 가능하며 새 제안 적용은 최신 원고에서 수행하세요.</p>}
      {data?.selection.map(s=><p key={s.id}>Trends 선정 연결: {s.geo} · {s.score}점 · {s.engine_version}</p>)}
      {!report&&<p>완료된 품질 평가가 없습니다. 정적 평가를 실행하세요.</p>}
      {data?.reports.filter(x=>x.status==="failed").map(x=><details key={x.id}><summary>이전 심층 평가 보류 기록{report?.stage==="codex"?" · 별도 완료 결과 있음":""}</summary><p role="status">{failures[x.result.error_code??""]??"평가를 완료하지 못했습니다. 원고와 이전 결과는 보존됩니다."}</p>{report?.stage!=="codex"&&<button disabled={busy} onClick={()=>void run(()=>api(`/reports/${x.id}/recheck`,"POST",{}))}>저장 응답 재검사 · Codex 호출 없음</button>}</details>)}
      {report&&r&&<><p><strong>{report.stage==="static"?"정적 평가만 완료 · 심층 항목 미평가":"Codex 심층 평가 완료 · 사람 검토 필요"}</strong><br/>{report.engine_version} · {new Date(report.created_at).toLocaleString("ko-KR")} · 평가 Version {data?.versions.find(v=>v.id===report.import_version_id)?.version_number??report.import_version_id}</p>
        <p>종합 점수: {r.overall_score??"미평가"}{r.measured_score!==undefined&&` · 정적 측정 항목 ${r.measured_score}점 (전체 가중치 중 ${r.measured_weight}% 범위)`}</p>
        <dl className={styles.scores}>{Object.entries(names).map(([k,n])=><div key={k}><dt>{n}</dt><dd>{r.scores?.[k]??"미평가"}</dd></div>)}</dl>
        {r.evidence&&<p>독립 검증 Claim {r.evidence.verified_claims??"미확인"} · 검증 전 Claim {r.evidence.unverified_claims} · 등록 출처 {r.evidence.source_count} · 평가 중 원문 확인 {r.evidence.source_original_examined?"예":"아니오"}</p>}
        {r.rationale&&<p>{r.rationale}</p>}
        {r.checks&&<details><summary>정적 검사 상세</summary><ul>{Object.entries(r.checks).map(([k,v])=><li key={k}>{k}: {v?"통과":"수정·검토 필요"}</li>)}</ul></details>}
        <h4>구체적인 수정 제안</h4>{Object.entries(names).map(([key,label])=>{const suggestions=r.suggestions?.filter(s=>s.category===key)??[];return suggestions.length?<section key={key}><h5>{label}</h5>{suggestions.map(s=>{const event=data?.events.filter(e=>e.report_id===report.id&&e.suggestion_id===s.id).at(-1);return <article key={s.id} className={styles.suggestion}><p>{s.location} · {s.automatic?"규칙으로 적용 가능":"사용자 의미·사실 검토 필요"}{event&&` · 기록: ${event.action}`}</p><strong>현재 문장</strong><blockquote>{s.original||"누락된 항목"}</blockquote><strong>개선 제안</strong><p>{s.field==="duplicate_sentence"?"첫 등장 문장은 유지하고 이후 동일 문장을 삭제합니다.":s.proposal??s.reason}</p><p>이유: {s.reason}</p><p>기대 효과: {s.expected_effect}</p>{s.fact_check_required&&<p>사실·의미 확인이 필요합니다.</p>}
          <div className="toolbar">{(s.automatic||s.proposal)&&<label><input type="checkbox" checked={selected.includes(s.id)} disabled={busy||!latest} onChange={e=>setSelected(ids=>e.target.checked?[...ids,s.id]:ids.filter(i=>i!==s.id))}/>적용할 제안 선택</label>}<button disabled={busy} onClick={()=>void run(()=>act("ignore",[s.id]))}>무시 기록</button><button disabled={busy} onClick={()=>void run(()=>act("review",[s.id]))}>검토 필요 기록</button></div></article>;})}</section>:null;})}
        {!r.suggestions?.length&&<p>기록된 수정 제안이 없습니다. 사람 검토는 별도로 필요합니다.</p>}
        <label><input type="checkbox" checked={confirmed} disabled={busy} onChange={e=>setConfirmed(e.target.checked)}/>선택한 수정안의 의미·사실과 정확한 버전을 직접 검토했습니다. 새 버전 저장에 동의합니다.</label><button disabled={busy||!latest||!confirmed||!selected.length} onClick={()=>void run(()=>act("apply",selected))}>선택 제안을 새 버전으로 적용</button>
      </>}
      <h4>Content Version 비교</h4><div className="toolbar"><label>변경 전<select value={before} onChange={e=>setBefore(e.target.value)}>{data?.versions.map(v=><option key={v.id} value={v.id}>v{v.version_number} · {v.title}</option>)}</select></label><label>변경 후<select value={after} onChange={e=>setAfter(e.target.value)}>{data?.versions.map(v=><option key={v.id} value={v.id}>v{v.version_number} · {v.title}</option>)}</select></label><button disabled={busy||!before||!after||before===after} onClick={async()=>{setError("");try{const d=await api(`/imports/${importId}/compare?before=${before}&after=${after}`);setDiff(d.fields);}catch(e){setError(String(e));}}}>버전 차이 보기</button></div>
      {diff&&Object.entries(diff).map(([field,d])=><section key={field}><h5>{{title:"제목",body_markdown:"Summary Deck · 본문",seo_metadata:"SEO 메타데이터",blogger_labels:"Blogger 라벨"}[field]}</h5>{d.diff.length?<pre className={styles.diff}>{d.diff.map((line,i)=><span key={i} data-kind={line.startsWith("+")?"added":line.startsWith("-")?"removed":"context"}>{line+"\n"}</span>)}</pre>:<p>변경 없음</p>}</section>)}
    </>}
  </section>;
}
