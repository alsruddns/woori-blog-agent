# P5-CODEX-112 — Blogger 연결 관리·언어 정책 UI/UX 개선

## 작업 정보

- 작업 ID: P5-CODEX-112
- 작업 시각: 2026-11-03 11:37 KST (완료 감사 시각; 별도 착수 시각은 기록하지 않음)
- 브랜치: `develop`
- 시작 커밋: `823c14491a61004516ad8887188afee22c319796`
- 변경 사유: Blogger 연결 화면의 OAuth 카드가 계정과 인증 이력을 혼동시키고, 로그가 화면을 길게 차지하며, 언어 정책 화면과 별도 메뉴처럼 보였다. 다크 모드·모바일에서 폼과 연결 버튼의 표현도 정돈이 필요했다.
- 목표: 계정/연결/시도 기록을 근거에 따라 분리하고 공통 Blogger 관리 탭, 정렬된 연결 카드, 지연 조회 로그, 읽기 쉬운 반응형 폼을 제공한다.

## 운영 데이터 확인

운영 DB의 비밀값을 출력하지 않는 읽기 확인에서 Google 계정 식별자는 저장되어 있지 않아 실제 고유 Google 계정 수를 확인할 수 없었다. 현재 확인된 OAuth 연결 레코드는 7건(connected 3, pending 4)이다. 연결 완료 3건 중 Blogger 전체 scope는 2건, readonly scope는 1건이다. 인증 시도는 7건이며, pending 레코드 4건은 모두 미소비 만료 상태이고 활성 인증 시도는 없다. 연결된 Blogger 레코드는 4건이며 1개의 distinct OAuth 연결 레코드에 매핑되어 있다.

기존 화면은 계정 그룹이 아니라 `google_connections`의 각 레코드를 카드로 표현했다. 그러므로 카드 수는 Google 계정 수가 아니며, pending 인증 레코드도 별도 카드로 보였다. 현재 DB에는 8개 카드가 아니라 7개 연결 레코드가 있다. 저장된 계정 이메일/Google subject가 없으므로 8개 표시의 당시 고유 계정 수나 정확한 과거 행 구성을 단정하지 않는다. OAuth scope나 Blogger profile ID를 Google 계정 식별자로 취급하지 않는다.

OAuth token/ciphertext, refresh token 값, client secret, 인증 코드는 열람하거나 UI·로그·기록에 노출하지 않았다. OAuth 연결, Blogger 매핑, operation 설정은 변경하지 않았다. 실제 Blogger API 쓰기 요청은 0건이다.

## 변경 전 / 변경 후

- 변경 전: 연결 레코드와 scope·만료 등의 정보가 한 줄 목록으로 섞였고 해제 버튼 위치가 일정하지 않았다. API/감사/초안 테스트 이력이 페이지에서 즉시 노출됐다. `/blogger`와 `/config`는 별개의 화면 구조로 보였다.
- 변경 후: 각 OAuth 연결을 상태·scope·연결/시도 시각·Blogger profile ID·연결된 블로그로 구분해 표시한다. 이메일이 저장되지 않으면 고유 계정 수를 확인 불가로 명시한다. 모든 연결 카드는 동일한 하단 액션 영역을 사용하고, 연결 해제는 대상·영향 확인 대화상자 후에만 실행하도록 했다.
- Blogger 관리 상위 탭을 `/blogger`(연결 관리, 기본)와 `/config`(언어·정책)로 통일했다. 기존 URL은 유지하고 브라우저 탐색 및 좌측 메뉴의 활성 상태를 확인했다.
- API 호출/오류, Blogger 초안 테스트, 인증·Blogger 감사 이력은 기본 접힘 아코디언으로 바꿨다. 열 때만 페이지당 최대 50개의 안전 필드를 조회하며 필터와 페이지 이동을 지원한다. 원고 제목·본문이나 요청 payload는 반환하지 않는다.
- 다크/라이트 테마 입력·선택·카드 대비와 모바일 그리드를 조정했다. 테마 초기화 시 Next `Script`의 개발 렌더 오류가 발생해 해당 스크립트 삽입을 제거하고 기존 클라이언트 테마 선택 동작을 유지했다. 첫 하이드레이션 전 잠깐의 테마 전환 깜빡임 가능성은 남아 있다.

## 변경 파일

- `apps/dashboard/app/api/blogger/[...path]/route.ts`
- `apps/dashboard/app/blogger/manager.tsx`
- `apps/dashboard/app/blogger/page.tsx`
- `apps/dashboard/app/blogger-management-tabs.tsx` (신규)
- `apps/dashboard/app/config/page.tsx`
- `apps/dashboard/app/layout.tsx`
- `apps/dashboard/app/navigation.tsx`
- `apps/dashboard/app/style.css`
- `apps/dashboard/e2e/P5-CODEX-112-connection-management.spec.ts` (신규)
- `services/api/woori/blogger_routes.py`
- `services/api/woori/blogger_drafts.py`
- `services/api/tests/test_google.py`
- `docs/development/assets/P5-CODEX-112-connections-desktop.png`
- `docs/development/assets/P5-CODEX-112-connections-mobile.png`
- `docs/development/assets/P5-CODEX-112-language-policy-desktop.png`
- `docs/development/assets/P5-CODEX-112-language-policy-mobile.png`

DB Migration은 추가하지 않았다. 운영 콘텐츠·OAuth 연결·Blogger 매핑을 변경하지 않았으며, P111 운영 승인 및 발행 설정도 변경하지 않았다. 보존된 stash `stash@{0}`는 조회만 했고 적용/삭제하지 않았다.

## 검증

- `services/api/tests/test_google.py`: 30 passed (격리 테스트 DB; pytest cache ACL 경고 1건은 테스트 실패가 아님).
- Ruff: 변경 Python 3개 파일 통과.
- Dashboard ESLint: 통과.
- Dashboard TypeScript typecheck: 통과.
- Playwright P5-CODEX-112: desktop 1440px 및 mobile 390px, 2/2 통과. 탭·새로고침·뒤로 가기, OAuth 요약, 로그 기본 접힘/열 때 조회, 연결 해제 모달 취소, 다크/라이트에서 표시 요소 4.5:1 이상 대비, 가로 넘침 없음, 페이지 오류 없음, OAuth/블로그 변경 요청 0건을 확인했다.
- UI 캡처: 연결 관리 및 언어·정책 화면 각각 desktop/mobile 4장.
- `git diff --check`: 통과.
- 실제 Blogger API 쓰기/연결 해제: 0건. DB 설정/연결 변경: 0건.
- append-only PostgreSQL 실행 감사: `agent.p5_codex_112.completed`, event ID `312788`, 2026-11-03 11:37:18 KST. 작업 ID·브랜치·검증 요약만 기록했다.

## 운영 반영 및 남은 항목

- 개발 검증 중 production API/Dashboard/Worker를 종료하거나 재시작하지 않았다. 변경을 커밋한 뒤 `scripts/apply-verified-changes.ps1`의 안전 반영 절차를 실행해 영향 서비스(API, Dashboard, Publication Worker)를 검증·반영한다. Research Worker 및 PostgreSQL은 변경 범위에 없어 재시작하지 않는다.
- 현재 확인 불가: 고유 Google 계정 수 및 과거 화면 캡처 시점에 8로 보였던 구체적인 DB 행 구성. 계정 식별자가 저장되지 않아 추론하지 않는다.
- 남은 UI 한계: 최초 테마 값은 클라이언트가 적용하므로 첫 로드에서 잠깐 깜빡일 수 있다.
- 커밋 해시와 원격 반영 결과는 작업 완료 후 Git 이력에 확인한다.

## 관련 문서

- `AGENTS.md`
- `docs/development/P5-CODEX-111.md`
- `docs/development/P5-CODEX-112.md`
