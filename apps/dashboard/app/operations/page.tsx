import Link from "next/link";
export default function OperationsPage() {
  return <main className="workspace-main"><div className="page-heading"><div><p className="eyebrow">관리자 전용</p><h1>운영 및 진단</h1><p>시스템 실행 정보와 개발자용 상세 기록은 필요할 때 별도 화면에서 확인합니다.</p></div></div><section className="workspace-panel link-cards">
    <Link href="/operations/research"><strong>리서치·실행 기록</strong><span>작업 단계, 출처 조사, 평가 지표 및 상세 JSON</span></Link>
    <Link href="/config"><strong>언어·블로그·정책 설정</strong><span>등록 언어와 국가별 작업 설정</span></Link>
    <Link href="/blogger"><strong>Blogger 연결 상태</strong><span>OAuth 권한과 연결 확인</span></Link>
    <Link href="/publishing"><strong>발행 안전 점검</strong><span>Mock 발행 및 발행 차단 상태</span></Link>
    <Link href="/model-comparison"><strong>AI 원고 평가 기록</strong><span>저장된 모델 비교 결과 · 운영 진단용</span></Link>
  </section></main>;
}
