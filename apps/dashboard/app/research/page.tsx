import Link from "next/link";
import { API_BASE, headers } from "../../lib/server";
import Research, { type State } from "./research";
export const dynamic = "force-dynamic";
export default async function Page() {
  let data: State | null = null;
  try {
    const response = await fetch(`${API_BASE}/admin/research/state`, {
      headers: headers(), cache: "no-store", signal: AbortSignal.timeout(5000),
    });
    if (response.ok) data = await response.json() as State;
  } catch {}
  return <main><header><Link href="/">WOORI / OPERATIONS</Link><Link href="/config">언어·국가 정책</Link></header>
    <h1>콘텐츠 리서치·실제 AI 내부 초안</h1>
    <aside>평가 초안은 품질 보류 상태로 저장됩니다. 규칙 검사는 의미적 사실·번역 품질을 보증하지 않습니다. 운영 발행·유료 AI는 차단됩니다.</aside>
    {data ? <Research initial={data}/> : <p role="alert">API 연결 또는 인증 설정을 확인하세요.</p>}
  </main>;
}
