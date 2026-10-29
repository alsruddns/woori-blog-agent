import Link from "next/link";
import { API_BASE, headers } from "../../../lib/server";
import AutomationDashboard, { type Snapshot } from "./automation-dashboard";
export const dynamic = "force-dynamic";
export default async function OperationsResearchPage() {
  let data: Snapshot | null = null;
  try { const response=await fetch(`${API_BASE}/admin/operations/dashboard`,{headers:headers(),cache:"no-store",signal:AbortSignal.timeout(5000)}); if(response.ok)data=await response.json() as Snapshot; } catch {}
  return <main className="workspace-main"><header><Link href="/operations">운영 및 진단</Link></header><div className="page-heading"><div><p className="eyebrow">콘텐츠 운영</p><h1>자동화 관리</h1><p>자료 수집부터 원고 검증과 Blogger 발행까지 실제 운영 상태를 확인합니다. 예약 원고 자동 전달은 검증된 실행만 집계합니다.</p></div></div><AutomationDashboard data={data}/></main>;
}
