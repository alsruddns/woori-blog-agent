import Link from "next/link";
export default function OperationsPage() {
  return <main className="workspace-main"><div className="page-heading"><div><p className="eyebrow">관리자 전용</p><h1>운영 및 진단</h1><p>시스템 실행 정보와 개발자용 상세 기록은 필요할 때 별도 화면에서 확인합니다.</p></div></div><section className="workspace-panel link-cards">
    <Link href="/operations/research"><strong>자동화 관리</strong><span>자료 수집, 원고 수신, 품질 검증과 Blogger 발행 현황</span></Link>
    <Link href="/config"><strong>언어·블로그·정책 설정</strong><span>등록 언어와 국가별 작업 설정</span></Link>
    <Link href="/blogger"><strong>Blogger 연결 상태</strong><span>OAuth 권한과 연결 확인</span></Link>
    <Link href="/publishing"><strong>발행 안전 점검</strong><span>Mock 발행 및 발행 차단 상태</span></Link>
  </section></main>;
}
