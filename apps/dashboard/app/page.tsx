import { API_BASE } from "../lib/server";
import Link from "next/link";
export const dynamic = "force-dynamic";
type Summary = { language_details: { code: string; display_name: string; active: boolean }[]; blogs: { language_code: string }[]; operations?: { warning: boolean; free_disk_percent: number; backup_ok: boolean; backup_stale: boolean } };
const areas = [
  { href: "/sources", eyebrow: "조사", title: "수집 자료", description: "국가별 트렌드 관측과 연결된 근거 자료" },
  { href: "/manuscripts", eyebrow: "편집", title: "작성 원고", description: "원고 목록, 본문, 품질 및 검토 이력" },
  { href: "/model-comparison", eyebrow: "평가", title: "AI 원고 비교", description: "실제로 저장된 모델 평가 결과" },
  { href: "/publishing", eyebrow: "발행", title: "발행 관리", description: "승인 이력과 발행 안전 상태" },
];
export default async function Page() {
  let data: Summary | null = null;
  try { if (process.env.ADMIN_TOKEN) { const response = await fetch(`${API_BASE}/admin/summary`, { headers: { Authorization: `Bearer ${process.env.ADMIN_TOKEN}` }, cache: "no-store", signal: AbortSignal.timeout(3000) }); if (response.ok) data = await response.json() as Summary; } } catch {}
  return <main className="workspace-main"><div className="page-heading"><div><p className="eyebrow">WOORI CONTENT STUDIO</p><h1>콘텐츠 운영</h1><p>수집 자료부터 검토까지 한곳에서 관리합니다.</p></div><span className="safe-indicator">안전 모드 · 자동 발행 꺼짐</span></div>
    <section className="grid dashboard-cards" aria-label="주요 작업"><>{areas.map(area => <Link key={area.href} href={area.href}><article><p className="eyebrow">{area.eyebrow}</p><h2>{area.title}</h2><p>{area.description}</p><span>열기 →</span></article></Link>)}</></section>
    {data ? <section className="workspace-panel"><div className="section-heading"><div><p className="eyebrow">설정된 운영 범위</p><h2>언어 및 블로그</h2></div><Link href="/config">언어·국가 정책 보기 →</Link></div><div className="grid">{data.language_details.map(language => <article key={language.code}><p className="eyebrow">{language.active ? "활성" : "비활성"}</p><h3>{language.display_name} <small>{language.code}</small></h3><p>등록 블로그 {data!.blogs.filter(blog => blog.language_code === language.code).length}개</p></article>)}</div>{data.operations?.warning && <p className="notice" role="status">운영 진단 항목이 있습니다. 상세 내용은 <Link href="/operations">운영·진단</Link>에서 확인하세요.</p>}</section> : <section className="workspace-panel"><p role="status">운영 요약을 불러오지 못했습니다. 각 자료 화면은 개별적으로 조회합니다.</p></section>}
  </main>;
}
