# P5-CODEX-030 — 원고 상세 탭 및 FOMC 근거 검증 개선

- 작업 일시: 2026-10-29 (Asia/Seoul)
- 작업 ID: P5-CODEX-030
- 브랜치: develop
- 작업 실행 ID: `e20bf26d-fd2f-4628-9020-0a7a13d4a9bb`
- 관련 원고 Import: `b4c45d23-0c74-4b12-92fd-382633093afa`
- Research Package: `c0b6f2b2-7a74-4b3f-a4f1-f4219c12321d`

## 변경 사유와 전후 상태

가져온 원고 상세 시트에서 긴 근거 경고가 탭을 아래로 밀었고, 원고 탭의 출처 정보는 제출된 자료만 보여 공식 원문 재확인 결과를 운영자가 확인하기 어려웠다. 기계 검사도 Markdown 링크 뒤 문장부호를 URL의 일부로 오인했고, 전체 기관명의 정상적인 일부 단어를 누락된 고유명사로 판단할 수 있었다.

상세 시트는 간결한 고정 헤더, 검토 상태 안내, 항상 보이는 가로 스크롤 탭, 단일 세로 스크롤 콘텐츠 영역으로 바뀌었다. 출처 탭은 실제 원문 확인 이벤트, HTTP 상태, 문서명, 날짜, URL, 근거 구간과 미완료 권리·사람 검토 상태를 보여준다. 품질 탭은 기계 검사와 SEO 결과를 범주별로 요약하며 원시 JSON은 접힌 개발자 영역에 둔다. 편집 입력은 탭을 전환해도 React 상태에 유지된다.

## 공식 자료 및 원고 버전

Fed 공식 원문 `https://www.federalreserve.gov/newsevents/pressreleases/monetary20261028a.htm`을 외부 정책 게이트의 허용된 요청 경로로 다시 조회해 HTTP 200, 2026-10-28 발표, 목표 범위, 표결, 반대 위원, 경제활동·고용·물가 평가와 추가 정보 평가 원칙을 확인했다. 해당 페이지의 공식성 확인과 저장된 Research Package 상태는 별개다. 독립 출처 수는 0이며, 권리 및 의미·편집 검토를 승인하지 않았다.

운영 Import의 기존 버전 4와 그 이전 이력은 보존했다. 앞선 수동 편집 버전 및 평가도 덮어쓰지 않았다. 최종 수동 Codex 편집은 새 버전 7로 저장했다.

- 새 Import 버전: `ed85a5c4-a387-40ad-84c7-8299cddee46f`
- 연결된 content version: `65133867-88d3-427a-bc24-b6994625eb38`
- 본문/메타데이터 해시: `b084fe97c6777c854600e6255816869b39a017eaad36158e3a4dac78a46a90d5`
- 편집 과정에서 생성된 v6는 초기에 검사 보류였고 삭제하지 않았다. v7에서 확인된 출처 구간·단위 정규화와 제목 날짜를 정리한 뒤 모든 결정론적 본문 검사가 통과했다.
- 평가: `machine_passed=true`, `publish_ready=false`
- SEO 준비: 제목·설명·핵심 검색어·소제목 구조·공식 출처 링크 및 원문 공식성 상태 준비됨
- 사람 확인: 검색 의도 실측, 두 번째 독립 출처, 주장 의미 일치, 이용 권리, 편집, Blogger 테마 검색 표시
- HTML: 1,183자, SHA-256 `b50207b541a25e0a52169309360c00eb2d8d64f0b7c304a0126f9359169dd1fb`
- 내부 `[source:...]` 마커: 게시용 HTML에서 제거됨

정규화된 수치는 원문의 분수 표기와 대조한 변환 정보를 별도 append-only 원문 검증 이벤트에 기록했다. 이는 별도 독립 출처나 의미 검증으로 간주하지 않는다. 개발용 원고 JSON은 `P5-CODEX-030-fomc-ko-revision.json`에 둔다.

## UI와 브라우저 확인

실제 운영 Dashboard 프로세스를 중단하지 않았다. 새 UI 코드를 적용한 임시 로컬 Dashboard를 별도 포트에서 실행하고, API 읽기 응답만 연결해 확인한 뒤 해당 임시 프로세스를 정상 종료했다. 실제 저장·승인·Blogger 쓰기 요청은 실행하지 않았다.

- 1920×1080: 여섯 탭 즉시 표시, 헤더 101 px, 탭 48 px
- 1366×768: 여섯 탭 즉시 표시, 콘텐츠 영역 내부 스크롤
- 390×844 / 375×812: 한 줄 가로 스크롤 탭, 현재 탭 자동 노출, 닫기 버튼 헤더 오른쪽 표시
- 키보드 좌우 화살표 탭 이동 확인
- 편집 내용을 변경한 뒤 탭을 왕복해도 입력 보존 확인
- 저장되지 않은 편집, 원고 저장, 검토 승인, 게시 동작은 수행하지 않음
- 네 화면 캡처: `docs/development/assets/P5-CODEX-030-import-detail-*.png`

## 수정 파일

- `apps/dashboard/app/imports/external-import-workspace.tsx`
- `apps/dashboard/app/style.css`
- `services/api/woori/content_imports.py`
- `services/api/woori/grounding.py`
- `services/api/tests/test_content_imports.py`
- `services/api/tests/test_live_research.py`
- `docs/development/P5-CODEX-030-fomc-ko-revision.json`
- `docs/development/assets/P5-CODEX-030-import-detail-desktop1920.png`
- `docs/development/assets/P5-CODEX-030-import-detail-desktop1366.png`
- `docs/development/assets/P5-CODEX-030-import-detail-mobile390.png`
- `docs/development/assets/P5-CODEX-030-import-detail-mobile375.png`

## 검증

- 격리 DB의 Fed Import·평가·HTML 회귀 테스트: 1 passed
- Markdown 링크 문장부호 URL 회귀 테스트: 1 passed
- Ruff 변경 범위: 통과
- Dashboard TypeScript 검사: 통과
- Dashboard ESLint: 통과
- `git diff --check`: 통과
- Playwright 네 가지 뷰포트와 여섯 탭·키보드 이동·편집 보존·저장된 HTML 미리보기: 통과

pytest는 `.env.test`의 `woori_blog_agent_test` / `woori_test_app`으로 실행했으며 운영 DB 쓰기는 사용하지 않았다. 개발 기록 및 구현 해시는 이번 커밋 뒤 `git log`에 연결한다.

## 남은 문제와 안전 상태

- 실제 Blogger 비공개 초안 및 공개 게시: 0건
- publish_ready: false
- Auto: 기존 OFF 유지
- 독립 출처·이용 권리·사람의 의미/편집 검토가 미완료이므로 발행하지 않는다.
- 운영 API/Worker는 종료하거나 재시작하지 않았다. 임시 Dashboard만 종료했다.
- 운영 Import 버전은 추가되었고 이전 버전 및 감사 기록은 삭제·수정하지 않았다.

## 커밋

- 커밋 해시: 이 기록과 같은 커밋을 가리키는 후속 `git log` 기록을 사용한다.
- 원격 푸시 결과: 커밋 후 기록한다.
