"use client";
import { useCallback, useEffect, useState } from "react";

type Row = Record<string, unknown>;
type Topic = { id: string; topic_id: string; query: string; geo: string; source_volume_label: string | null; score: number; decision: string; collection_slot: string; display_name: string; language_code: string; collected_at: string; result: { reasons: string[]; duplicate_matches: Row[]; components: Record<string, number> }; jobs: { job_id: string; state: string; import_id: string | null }[] | null };
const names: Record<string,string> = { selected:"선정", review_candidate:"추가 조사 후보", duplicate:"중복 제외", low_value:"가치 부족", insufficient_context:"맥락 부족", high_risk:"고위험 보류" };
const weightsNames: Record<string,string> = { news_value:"뉴스 가치",freshness:"최신성",reader_relevance:"독자 관련성",interest:"검색 관심도",article_potential:"기사화 가능성",analysis_value:"분석 가치" };
const base = "/api/research/editorial-intelligence";
async function request(path: string, method = "GET", body?: unknown) {
  const r = await fetch(base+path, { method, headers: {"Content-Type":"application/json"}, body: body === undefined ? undefined : JSON.stringify(body), cache:"no-store" });
  const data = await r.json();
  if (!r.ok) throw new Error(data.detail ?? data.error ?? `HTTP ${r.status}`);
  return data;
}
export default function EditorialSelection() {
  const [rows,setRows] = useState<Topic[]>([]),[total,setTotal] = useState(0),[q,setQ] = useState(""),[geo,setGeo] = useState(""),[blog,setBlog] = useState(""),[decision,setDecision] = useState(""),[minimum,setMinimum] = useState("0"),[slot,setSlot] = useState(""),[page,setPage] = useState(1);
  const [blogs,setBlogs] = useState<{id:string;display_name:string}[]>([]),[geos,setGeos] = useState<string[]>([]);
  const [aliases,setAliases]=useState<{id:number;geo:string;alias:string;canonical:string;reason:string}[]>([]);
  const [aliasGeo,setAliasGeo]=useState("KR"),[alias,setAlias]=useState(""),[canonical,setCanonical]=useState(""),[aliasReason,setAliasReason]=useState("");
  const [weights,setWeights] = useState<Record<string,number>>({}),[version,setVersion] = useState(""),[effective,setEffective] = useState(""),[monitor,setMonitor] = useState<Row|null>(null),[error,setError] = useState(""),[busy,setBusy] = useState(false),[loading,setLoading] = useState(true),[refresh,setRefresh] = useState(0);
  useEffect(()=>{ let active=true; Promise.all([request("/settings"),request("/monitor"),fetch("/api/research/trend-editorial/blog-geos").then(r=>r.json())]).then(([s,m,b])=>{if(!active)return;setWeights(s.versions[0].weights);setVersion(String(s.versions[0].id));setEffective(s.versions[0].effective_slot);setMonitor(m);setBlogs(b.blogs??[]);setGeos(b.geos??[]);}).catch(e=>{if(active)setError(String(e));});return()=>{active=false;};},[refresh]);
  useEffect(()=>{let active=true; const timer=setTimeout(()=>{setLoading(true); const p=new URLSearchParams({q,geo,decision,min_score:minimum||"0",page:String(page)});if(blog)p.set("blog_id",blog);if(slot)p.set("slot",new Date(slot).toISOString());request("/topics?"+p).then(d=>{if(active){setRows(d.items);setTotal(d.total);setError("");}}).catch(e=>{if(active)setError(String(e));}).finally(()=>{if(active)setLoading(false);});},250);return()=>{active=false;clearTimeout(timer);};},[q,geo,blog,decision,minimum,slot,page,refresh]);
  const run = useCallback(async (fn:()=>Promise<unknown>)=>{setBusy(true);setError("");try{await fn();setRefresh(x=>x+1);}catch(e){setError(String(e));}finally{setBusy(false);}},[]);
  const sum=Object.values(weights).reduce((a,b)=>a+b,0);
  const totals=(monitor?.totals??{}) as Record<string,number>;
  useEffect(()=>{let active=true;request("/aliases").then(d=>{if(active)setAliases(d.items);}).catch(e=>{if(active)setError(String(e));});return()=>{active=false;};},[refresh]);
  return <section className="workspace-panel" aria-label="지능형 주제 선정">
    <h2>지능형 주제 선정</h2><p>뉴스 가치·최신성·국가별 관심도를 함께 평가합니다. 점수는 조사 우선순위이며 사실 검증이나 게시 승인이 아닙니다.</p>
    <div className="toolbar"><button disabled={busy} onClick={()=>void run(()=>request("/assess-current","POST",{}))}>현재 회차 평가</button><button disabled={busy} onClick={()=>setRefresh(x=>x+1)}>선정 결과 새로고침</button></div>
    <p>이 평가는 Codex를 호출하거나 작성 Job을 만들지 않습니다. 실제 토큰 절약량·잔여 사용량은 측정하지 않았습니다.</p>
    {error&&<p role="alert" className="quality-held">{error}</p>}
    <details><summary>검토한 검색어 표기·별칭 관리</summary><p>같은 국가에서 확인한 약어·정식 명칭·표기만 등록하세요. 날짜와 후속 사건 표현은 유지합니다. 다음 수집 회차부터 적용하며, 자동 번역이나 의미 병합은 하지 않습니다.</p><form onSubmit={e=>{e.preventDefault();void run(()=>request("/aliases","POST",{geo:aliasGeo,alias,canonical,reason:aliasReason}));}}><div className="toolbar"><label>별칭 국가<select value={aliasGeo} onChange={e=>setAliasGeo(e.target.value)}>{geos.map(g=><option key={g}>{g}</option>)}</select></label><label>원문 표기<input required maxLength={200} value={alias} onChange={e=>setAlias(e.target.value)}/></label><label>동일 명칭<input required maxLength={200} value={canonical} onChange={e=>setCanonical(e.target.value)}/></label><label>동일 명칭 확인 근거<input required minLength={10} maxLength={1000} value={aliasReason} onChange={e=>setAliasReason(e.target.value)}/></label></div><button disabled={busy||aliasReason.length<10}>확인한 별칭 기록</button></form>{aliases.map(a=><p key={a.id}>{a.geo} · {a.alias} → {a.canonical} · {a.reason}</p>)}</details>
    <details><summary>평가 가중치 설정 · 버전 {version}</summary><p>반영 시작 회차: {(effective === "-infinity" || Date.parse(effective)===0) ? "초기 운영값" : effective} · 새 설정은 다음 회차부터 적용됩니다. 최적 성과가 입증된 값은 아닙니다.</p>
      <form onSubmit={e=>{e.preventDefault();void run(()=>request("/settings","PUT",weights));}}><div className="toolbar">{Object.entries(weights).map(([key,n])=><label key={key}>{weightsNames[key]??key}<input type="number" min="0" max="100" step="1" required value={n} onChange={e=>setWeights(w=>({...w,[key]:Number(e.target.value)}))}/></label>)}</div><p>합계 {sum}%</p><button disabled={busy||sum!==100||Object.values(weights).some(n=>!Number.isInteger(n)||n<0||n>100)}>다음 회차 가중치 저장</button></form>
    </details>
    {monitor&&<details><summary>선정·원고 품질 처리량</summary><p>Import 버전 {totals.import_versions??0} · 정적 평가 버전 {totals.evaluated??0} · 제안 있는 평가 {totals.with_suggestions??0} · 제안 적용 버전 {totals.edited_versions??0}</p><p>Trends 실제 작성 실행 {totals.authoring_executions??0} · 심층 CLI 실행 {totals.deep_cli_executions??0} · 정적 검사 통과 평가 {totals.static_checks_passed??0}</p>
      <p>선정 결과 (누적 평가 단위)</p>{((monitor.selection??[]) as {decision:string;n:number}[]).map(r=><span key={r.decision} style={{marginRight:12}}>{names[r.decision]} {r.n}</span>)}
      <p>Trends Codex 작업 (Job 단위)</p>{((monitor.trends_jobs??[]) as {state:string;error_code:string|null;n:number}[]).map((r,i)=><p key={i}>{r.state} · {r.error_code??"오류 없음"} {r.n}</p>)}
      <p>평가 단계</p>{((monitor.quality??[]) as {stage:string;status:string;n:number}[]).map((r,i)=><p key={i}>{r.stage} · {r.status} {r.n}</p>)}
      <p>국가별 Import·정적 평가 결과 (정적 점수는 가중치 30% 범위)</p>{((monitor.regional_outcomes??[]) as {geo:string;imported:number;evaluated:number;measured_static_average:number|null}[]).map(r=><p key={r.geo}>{r.geo} · Import {r.imported} · 평가 {r.evaluated} · 측정 범위 평균 {r.measured_static_average==null?"미평가":Number(r.measured_static_average).toFixed(1)}</p>)}<p>게시 준비 여부는 기존 수동 검토·승인 화면에서 별도로 확인하세요.</p></details>}
    <div className="toolbar"><label>선정 검색어<input type="search" value={q} onChange={e=>{setQ(e.target.value);setPage(1);}}/></label><label>선정 국가<select value={geo} onChange={e=>{setGeo(e.target.value);setPage(1);}}><option value="">전체</option>{geos.map(g=><option key={g}>{g}</option>)}</select></label>
      <label>대상 Blogger<select value={blog} onChange={e=>{setBlog(e.target.value);setPage(1);}}><option value="">전체</option>{blogs.map(b=><option key={b.id} value={b.id}>{b.display_name}</option>)}</select></label>
      <label>선정 상태<select value={decision} onChange={e=>{setDecision(e.target.value);setPage(1);}}><option value="">전체</option>{Object.entries(names).map(([k,n])=><option key={k} value={k}>{n}</option>)}</select></label>
      <label>최소 점수<input type="number" min="0" max="100" value={minimum} onChange={e=>{setMinimum(e.target.value);setPage(1);}}/></label><label>수집 회차<input type="datetime-local" value={slot} onChange={e=>{setSlot(e.target.value);setPage(1);}}/></label></div>
    {loading&&<p role="status">선정 평가 조회 중…</p>}
    <div className="data-grid-scroll"><table className="data-grid"><thead><tr>{["국가·검색어","검색량 원문","점수·상태","이유·중복 위험","대상 Blogger","Codex·Import"].map(t=><th key={t}>{t}</th>)}</tr></thead><tbody>{rows.map(r=><tr key={r.id}><td>{r.geo} · {r.query}<small>{new Date(r.collection_slot).toLocaleString("ko-KR")}</small></td><td>{r.source_volume_label??"미제공"}</td><td>{r.score} · {names[r.decision]}<details><summary>항목별 근거</summary>{Object.entries(r.result.components).map(([k,v])=><p key={k}>{weightsNames[k]??k}: {v}</p>)}</details></td><td><details><summary>{r.result.reasons.at(-1)}</summary>{r.result.reasons.map((s,i)=><p key={i}>{s}</p>)}{r.result.duplicate_matches.map((m,i)=><p key={i}>중복 근거: {String(m.type)} {m.import_id?<a href={`/imports?open_import_id=${m.import_id}`}>기존 원고</a>:"진행 중 작업"}</p>)}</details></td><td>{r.display_name}<small>{r.language_code}</small></td><td>{r.jobs?.length?r.jobs.map(j=><p key={j.job_id}>{j.state} {j.import_id&&<a href={`/imports?open_import_id=${j.import_id}`}>원고 보기</a>}</p>):"미실행"}</td></tr>)}</tbody></table></div>
    {!loading&&!rows.length&&<p>조건에 맞는 선정 평가가 없습니다. 현재 회차 평가 또는 다음 수집을 기다리세요.</p>}
    <div className="toolbar"><button disabled={page<=1} onClick={()=>setPage(p=>p-1)}>이전 평가</button><span>{page}쪽 · {total}건</span><button disabled={page*25>=total} onClick={()=>setPage(p=>p+1)}>다음 평가</button></div>
  </section>;
}
