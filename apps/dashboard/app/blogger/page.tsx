import Link from "next/link";
import { API_BASE, headers } from "../../lib/server";
import Manager from "./manager";
export const dynamic = "force-dynamic";
export default async function Blogger({
  searchParams,
}: {
  searchParams: Promise<{ oauth?: string }>;
}) {
  let status = null;
  try {
    const response = await fetch(`${API_BASE}/admin/blogger/status`, {
      headers: headers(),
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
    if (response.ok) status = await response.json();
  } catch {}
  const query = await searchParams;
  return (
    <main className="workspace-main blogger-page">
      <div className="page-heading"><div><p className="eyebrow">계정 및 대상 블로그</p><h1>Blogger 연결 관리</h1><p>등록된 블로그, OAuth 권한과 읽기 연결 상태를 확인합니다.</p></div><Link className="secondary-button" href="/config">언어·정책 설정</Link></div>
      <aside className="blogger-policy-note">
        Blogger 전용 프로젝트 소유자 비용 승인이 기록된 경우에만 블로그 조회와 사용자가 확인한 비공개 테스트 초안 1건 생성을 허용합니다. 공개 게시·예약 게시·수정·삭제·자동 발행 및 다른 유료 API는 계속 차단됩니다.
      </aside>
      {query.oauth && (
        <p role="status">
          {query.oauth === "connected"
            ? "Google OAuth 연결을 완료했습니다. 허가된 권한과 블로그별 연결 상태를 확인하세요."
            : "Google 인증을 완료하지 못했습니다. 설정과 권한을 확인하고 다시 시작하세요."}
        </p>
      )}
      {status ? (
        <Manager initial={status} />
      ) : (
        <p role="alert">API 연결 또는 인증 설정을 확인하세요.</p>
      )}
    </main>
  );
}
