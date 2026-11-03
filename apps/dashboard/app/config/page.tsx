import { API_BASE } from "../../lib/server";
import Manager from "./manager";
import type { Config } from "./types";
import BloggerManagementTabs from "../blogger-management-tabs";
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
    <main className="workspace-main blogger-page">
      <div className="page-heading"><div><p className="eyebrow">Blogger 관리</p><h1>언어·정책 설정</h1><p>언어, 블로그 매핑 및 국가별 콘텐츠 정책을 관리합니다.</p></div></div>
      <BloggerManagementTabs active="language-policy" />
      <aside className="blogger-policy-note">언어·블로그 등록은 자동 발행 승인이 아닙니다. 기존 운영 제한과 콘텐츠 기록은 별도로 유지됩니다.</aside>
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
