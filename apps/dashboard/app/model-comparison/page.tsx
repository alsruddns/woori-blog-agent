import ModelComparison from "./view";

export const dynamic = "force-dynamic";

export default function ModelComparisonPage() {
  return <main className="workspace-main"><div className="page-heading"><div><p className="eyebrow">평가 전용</p><h1>AI 원고 비교</h1><p>동일한 조사 자료를 사용한 저장 평가를 나란히 살펴봅니다. 비교 화면은 원고를 발행하지 않습니다.</p></div></div><ModelComparison /></main>;
}
