import ManuscriptManager from "./manager";

export const dynamic = "force-dynamic";

export default function ManuscriptsPage() {
  return <main className="workspace-main"><div className="page-heading"><div><p className="eyebrow">콘텐츠 스튜디오</p><h1>원고 관리</h1><p>저장 원고를 찾고, 검토하거나 외부 원고를 가져옵니다.</p></div></div><ManuscriptManager /></main>;
}
