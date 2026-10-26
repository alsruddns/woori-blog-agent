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
    <main>
      <header>
        <Link href="/">WOORI / OPERATIONS</Link>
        <Link href="/config">언어·정책 설정</Link>
      </header>
      <h1>Blogger 연결 관리</h1>
      <aside>
        읽기 전용 운영 · 실제 생성·수정·삭제·발행과 유료 AI 호출은 차단됩니다.
      </aside>
      {query.oauth && (
        <p role="status">
          {query.oauth === "connected"
            ? "Google 읽기 권한 연결을 완료했습니다. 블로그별 연결을 검증하세요."
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
