import SourceWorkspace from "./workspace";

export const dynamic = "force-dynamic";

export default function SourcesPage() {
  return <main className="workspace-main"><div className="page-heading"><div><p className="eyebrow">조사 데스크</p><h1>수집 자료</h1><p>Google Trends 관측값과 연결된 주제·출처를 확인합니다. 순위는 원천에서 제공한 값만 표시합니다.</p></div></div><SourceWorkspace /></main>;
}
