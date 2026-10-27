import ManuscriptWorkspace from "./workspace";

export const dynamic = "force-dynamic";

export default function ManuscriptsPage() {
  return <main className="workspace-main"><div className="page-heading"><div><p className="eyebrow">콘텐츠 스튜디오</p><h1>작성 원고</h1><p>저장된 원고를 검색하고 근거와 검토 이력을 확인합니다.</p></div></div><ManuscriptWorkspace /></main>;
}
