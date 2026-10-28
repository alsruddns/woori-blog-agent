import Link from "next/link";
import { API_BASE, headers } from "../../lib/server";
import PublicationManager, { type PublicationData } from "./publication-manager";

export const dynamic = "force-dynamic";

export default async function Page() {
  let data: PublicationData | null = null;
  let loadState: "ready" | "unauthenticated" | "unavailable" | "server_error" = "unavailable";
  try {
    if (process.env.ADMIN_TOKEN) {
      const response = await fetch(`${API_BASE}/admin/publications`, {
        headers: headers(), cache: "no-store", signal: AbortSignal.timeout(5000),
      });
      if (response.ok) data = await response.json() as PublicationData;
      loadState = response.ok ? "ready" : response.status === 401 || response.status === 403 ? "unauthenticated" : "server_error";
    } else loadState = "unauthenticated";
  } catch {}
  return <main className="workspace-main publication-workspace">
    <div className="page-heading"><div><p className="eyebrow">콘텐츠 배포</p><h1>발행 관리</h1><p>승인 대기 원고, 게시 이력과 블로그별 게시 정책을 확인합니다.</p></div><Link className="secondary-button" href="/blogger">Blogger 연결 확인</Link></div>
    {data ? <PublicationManager initial={data} /> : <section className="workspace-panel"><p role="alert" className="quality-held">{loadState === "unauthenticated" ? "인증되지 않았습니다. 로컬 관리자 인증 설정을 확인하세요." : loadState === "server_error" ? "서버가 발행 정보를 불러오지 못했습니다. 잠시 후 다시 시도하거나 운영 진단을 확인하세요." : "로컬 API 서버에 연결할 수 없습니다. API 서버가 실행 중인지 확인하세요."}</p></section>}
  </main>;
}
