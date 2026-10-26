export const dynamic = "force-dynamic";
type Summary = {runs: {id:string; status:string; attempts:number}[]; events:{id:number; event_type:string; created_at:string}[]};
export default async function Page() {
 let data: Summary | null = null;
 try {
  if(process.env.ADMIN_TOKEN) {
   const response = await fetch("http://127.0.0.1:8000/admin/summary", {headers:{Authorization:`Bearer ${process.env.ADMIN_TOKEN}`},cache:"no-store",signal:AbortSignal.timeout(3000)});
   if(response.ok) data = await response.json();
  }
 } catch {}
 return <main><header><span>WOORI / OPERATIONS</span><small>PHASE 01 · LOCAL</small></header><h1>블로그 운영 현황</h1><p>네 개 언어, 하나의 운영 공간.</p><aside>안전 모드 · 실제 발행 및 AI 호출 차단</aside><section className="grid">{["ko · 한국어","en · English","zh-CN · 简体中文","ja · 日本語"].map(x=><article key={x}><h2>{x}</h2><p>블로그 연결 대기</p><small>운영 연결은 별도 승인 후 활성화</small></article>)}</section><h2>작업 실행</h2>{data ? <table><thead><tr><th>실행 ID</th><th>상태</th><th>시도</th></tr></thead><tbody>{data.runs.map(r=><tr key={r.id}><td>{r.id}</td><td>{r.status}</td><td>{r.attempts}</td></tr>)}</tbody></table> : <p role="status">API 연결 또는 관리자 인증 설정을 확인하세요. 실시간 데이터가 없습니다.</p>}<h2>최근 감사 이벤트</h2>{data?.events.length ? <ul>{data.events.map(e=><li key={e.id}>{e.event_type} · {e.created_at}</li>)}</ul> : <p>표시할 이벤트가 없습니다.</p>}<footer>금융 · 주식 · 암호화폐 · K-pop · K-Beauty · 한국 관광 · 맛집</footer></main>
}
