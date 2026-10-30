"use client";
import {useEffect,useState} from "react";

type Settings={enabled:boolean;interval_minutes:number;pending_interval_minutes:number|null;effective_at:string|null;last_run:string|null;next_run_at:string|null;backoff_until:string|null;requested_window_hours:string;regions:{geo:string;slot_at:string;result:{status?:string;item_count?:number;failure_category?:string}}[]};
const time=(s:string|null)=>s?new Intl.DateTimeFormat("ko-KR",{dateStyle:"short",timeStyle:"short",timeZone:"Asia/Seoul"}).format(new Date(s)):"기록 없음";
export default function TrendSettings(){
 const [data,setData]=useState<Settings|null>(null),[enabled,setEnabled]=useState(true),[interval,setInterval]=useState(10),[busy,setBusy]=useState(false),[message,setMessage]=useState("");
 async function load(){const r=await fetch("/api/research/trends/settings",{cache:"no-store"});if(!r.ok)throw new Error(`설정 조회 실패 HTTP ${r.status}`);const d=await r.json() as Settings;setData(d);setEnabled(d.enabled);setInterval(d.pending_interval_minutes??d.interval_minutes);}
 useEffect(()=>{void Promise.resolve().then(load).catch(e=>setMessage(String(e)));},[]);
 async function save(){setBusy(true);setMessage("");try{const r=await fetch("/api/research/trends/settings",{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({enabled,interval_minutes:interval})});if(!r.ok)throw new Error(`설정 저장 실패 HTTP ${r.status}`);await load();setMessage("설정이 저장됐습니다. 수집 주기는 다음 회차부터 적용됩니다.");}catch(e){setMessage(String(e));}finally{setBusy(false);}}
 return <section className="workspace-panel"><h2>Google Trends 수집 설정</h2><p>11개 지역을 각 회차에 순차 수집합니다. HTTP 429 또는 접근 거부 시 수집을 일시 중지합니다.</p>
 <div className="toolbar"><label><input type="checkbox" checked={enabled} onChange={e=>setEnabled(e.target.checked)}/> 자동 수집</label><label>수집 주기<select value={interval} onChange={e=>setInterval(Number(e.target.value))}>{[5,10,15,20,30,60].map(m=><option value={m} key={m}>{m}분</option>)}</select></label><button type="button" disabled={busy||!data} onClick={()=>void save()}>{busy?"저장 중…":"설정 저장"}</button></div>
 <p>최근 수집: {time(data?.last_run??null)} · 다음 회차: {time(data?.next_run_at??null)} KST</p><p>주기 환산: {data?.requested_window_hours??"—"}시간. RSS 조회 기간 적용은 확인되지 않아 이 값을 요청에 보내지 않습니다.</p>{data?.effective_at&&<p>변경 적용 시각: {time(data.effective_at)} KST</p>}{data?.backoff_until&&new Date(data.backoff_until)>new Date()&&<p role="status">제공자 응답으로 {time(data.backoff_until)}까지 수집 대기</p>}
 <details><summary>지역별 최근 수집 결과</summary><ul>{data?.regions.map(r=><li key={r.geo}>{r.geo} · {time(r.slot_at)} · {r.result.status??"정보 없음"} · {r.result.item_count==null?"건수 정보 없음":`${r.result.item_count}건`} {r.result.failure_category??""}</li>)}</ul></details>{message&&<p role="status">{message}</p>}</section>;
}
