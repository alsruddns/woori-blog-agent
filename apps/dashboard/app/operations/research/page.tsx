import Link from "next/link";
import { API_BASE, headers } from "../../../lib/server";
import Research, { type State } from "../../research/research";
export const dynamic = "force-dynamic";
export default async function OperationsResearchPage() {
  let data: State | null = null;
  try { const response = await fetch(`${API_BASE}/admin/research/state`, { headers: headers(), cache: "no-store", signal: AbortSignal.timeout(5000) }); if (response.ok) data = await response.json() as State; } catch {}
  return <main className="workspace-main"><header><Link href="/operations">운영 및 진단</Link></header><div className="page-heading"><div><p className="eyebrow">기술 상세</p><h1>리서치·실행 기록</h1><p>내부 실행 상태, 모델 지표 및 원본 데이터는 이 진단 화면에 분리되어 있습니다.</p></div></div>{data ? <Research initial={data}/> : <p role="alert">진단 정보를 조회할 수 없습니다.</p>}</main>;
}
