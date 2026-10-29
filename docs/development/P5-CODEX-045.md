# P5-CODEX-045 — 운영 Dashboard UI/UX 및 테마 개선

- 작업 시각: 2026-10-29 18:38 KST 시작, 2026-10-29 완료
- 브랜치: `develop`
- 변경 사유: 기존 운영 Dashboard의 콘텐츠 폭이 제한적이고, 공통 메뉴가 가로형이며, 밝은 테마만 제공되어 넓은 화면·모바일에서 운영 상태를 빠르게 파악하기 어려웠다.
- 목적: 기존 API와 업무 동작을 유지하면서 공통 운영 셸, 탐색, 테마 및 주요 화면 표시를 정돈한다.

## 변경 전 / 변경 후

- 변경 전: 상단 수평 메뉴, 1480px 콘텐츠 상한, 단일 라이트 테마. Blogger 연결은 다른 메뉴에서 직접 찾기 어려웠다.
- 변경 후: 접기 가능한 좌측 메뉴, 고정 헤더, Light/Dark/System 테마 선택 및 새로고침 후 유지, 가용 너비 기반 반응형 본문, Blogger 바로가기, 실데이터 기반 8개 Home KPI.
- 발행 관리의 예약 Auto·승인·중지 기능과 API 호출은 기존 코드를 유지했다. Auto 상태 및 실제 Blogger 쓰기는 변경하거나 실행하지 않았다.
- 자동화와 Blogger 데이터는 기존 API 응답만 표시한다. Codex 예약 작업의 실시간 상태를 새로 추정하거나 가짜 수치를 만들지 않았다.

## 수정 파일

- `apps/dashboard/app/navigation.tsx` — 그룹 메뉴, 아이콘, 활성 경로, 접기/모바일 Drawer, 키보드 제어, 테마 선택
- `apps/dashboard/app/layout.tsx` — 공통 셸과 초기 테마 적용
- `apps/dashboard/app/style.css` — 디자인 토큰, 다크 테마, 넓은 화면·모바일 규칙, 운영 카드·표 스타일
- `apps/dashboard/app/page.tsx` — 기존 Dashboard 응답을 사용하는 KPI 추가
- `apps/dashboard/app/blogger/page.tsx` — Blogger 연결 페이지를 공통 제목·본문 레이아웃에 적용
- `apps/dashboard/app/blogger/manager.tsx` — OAuth 연결 항목을 카드형 목록에 연결
- `apps/dashboard/next.config.ts` — 운영 빌드 산출물을 덮지 않는 검증 전용 dist 경로 지원
- `apps/dashboard/e2e/P5-CODEX-045-dashboard-shell.spec.ts` — 경로, 활성 메뉴, 반응형, 테마 지속, 모바일 Drawer 회귀 검증

## 검증

- `npm run lint`: 통과
- `npx tsc --noEmit`: 통과
- 격리 Production build (`WOORI_DASHBOARD_DIST_DIR=.next-p5-code045`): 통과. 기존 실행 중 Dashboard/API를 재시작하지 않았다.
- Playwright P5-CODEX-045 전용: 4/4 통과 (desktop/mobile 프로젝트). `/`, `/publishing`, `/operations/research`, `/blogger`를 390, 768, 1280, 1920px에서 확인했다.
- 실제 브라우저 검사: 다크 테마 저장·새로고침 유지, 모바일 메뉴 열기·Escape 닫기, 활성 메뉴 정확성 확인. 콘솔 오류 0건, 브라우저에서 발생한 비-GET 요청 0건.
- 발행·승인·OAuth 쓰기 핸들러는 UI 검증 중 실행하지 않았다.
- `git diff --check`: 통과.

## 브라우저 증거

로컬 스크린샷은 `.runtime/reports/P5-CODEX-045/`에 생성했다.

- `home-1920-light.png`, `home-1920-dark.png`, `home-390-light.png`
- `publishing-1920-light.png`, `publishing-390-light.png`
- `automation-1920-light.png`, `automation-390-light.png`
- `blogger-1920-light.png`, `blogger-390-light.png`

검증용 빌드는 3101에서 별도로 실행했으며, 운영 포트 3100/8100 프로세스는 유지했다.

## 데이터 및 운영 안전

- DB 스키마·데이터·OAuth·감사 기록 변경 없음
- Blogger 실제 게시 및 예약 Auto 활성화 없음
- `.playwright-mcp/`는 기존 미추적 사용자 자료로 보존하고 커밋 대상에서 제외

## 남은 문제

- 3100에서 이미 실행 중인 Dashboard 프로세스는 사용자가 시작한 기존 빌드를 계속 사용한다. 이번 변경을 그 프로세스에 적용하려면 운영자가 정상 재시작해야 한다. 이 작업에서는 사용자 프로세스를 중단하지 않았다.
- 브라우저 검증은 개발 PC의 격리 Production build와 실제 로컬 API 읽기 경로를 대상으로 했다. 원격 배포는 수행하지 않았다.

## 커밋

- 구현 커밋: `632245d70d8fd519f5557e16b854732bcdd69107`
- 원격 푸시: `origin/develop` 성공 (`97a1c5e..632245d`). 개발 기록 후속 커밋은 `git log`로 확인한다.
