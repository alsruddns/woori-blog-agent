import ManuscriptWorkspace from "./workspace";
import { ExternalImportQueue } from "../imports/external-import-workspace";

export const dynamic = "force-dynamic";

export default function ManuscriptsPage() {
  return <main className="workspace-main"><div className="page-heading"><div><p className="eyebrow">콘텐츠 스튜디오</p><h1>작성 원고</h1><p>저장된 원고의 품질과 검토 이력을 살펴보고, 외부 원고는 별도 대기열에서 확인합니다.</p></div></div><ExternalImportQueue /><ManuscriptWorkspace /></main>;
}
