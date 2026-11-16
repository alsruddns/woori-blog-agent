import Link from "next/link";
import Controls from "./controls";
export default function AutomationControlsPage() {
  return <main className="workspace-main"><header><Link href="/operations">운영 및 진단</Link></header><div className="page-heading"><div><p className="eyebrow">콘텐츠 운영</p><h1>자동화 운영 제어센터</h1><p>수집, 원고 작성, 자동 발행과 수동 발행을 독립적으로 관리합니다.</p></div></div><Controls /></main>;
}
