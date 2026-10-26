import { API_BASE } from "../../lib/server";
import Link from "next/link";
import Manager from "./manager";
import type { Config } from "./types";
export const dynamic = "force-dynamic";
export default async function Configuration() {
  let config: Config | null = null;
  try {
    if (process.env.ADMIN_TOKEN) {
      const response = await fetch(`${API_BASE}/admin/config`, {
        headers: { Authorization: `Bearer ${process.env.ADMIN_TOKEN}` },
        cache: "no-store",
        signal: AbortSignal.timeout(3000),
      });
      if (response.ok) config = await response.json();
    }
  } catch {}
  return (
    <main>
      <header>
        <Link href="/">WOORI / OPERATIONS</Link>
        <span>언어 및 블로그 설정</span>
      </header>
      <h1>다국어 운영 설정</h1>
      <aside>
        등록은 자동 발행을 활성화하지 않습니다. 운영 블로그 요청과 AI 호출은
        차단되어 있습니다.
      </aside>
      {config ? (
        <Manager config={config} />
      ) : (
        <p role="alert">
          설정을 불러오지 못했습니다. API 및 인증 설정을 확인하세요.
        </p>
      )}
    </main>
  );
}
