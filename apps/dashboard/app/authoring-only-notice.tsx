"use client";

export default function AuthoringOnlyNotice() {
  return <section role="status" className="workspace-panel" data-testid="authoring-only-notice">
    <strong>원고 작성 자동화 ON / Blogger 자동 발행 OFF / 수동 API 발행 전용</strong>
    <p>수집·원고 작성·Import는 계속됩니다. 기존 대기 Job은 보존되며 자동 초안·공개·수정·재시도는 중지됐습니다. Google 계정의 Blogger API 접근 제한이 확인되어 수동 API 쓰기도 현재 차단됩니다. 제한 해제는 Google의 공식 이의신청 절차로 진행하세요.</p>
    <a href="https://www.blogger.com/" target="_blank" rel="noopener noreferrer">Blogger 관리자에서 직접 검토·게시</a>
  </section>;
}
