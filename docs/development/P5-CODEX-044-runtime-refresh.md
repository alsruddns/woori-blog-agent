# P5-CODEX-044 — 예약 Auto UI 표시 및 런타임 갱신

- 작업 시각: 2026-10-29 (Asia/Seoul)
- 작업 브랜치: `develop`
- 변경 사유: 실행 중 Dashboard에서 예약 원고 Auto 관리 영역과 승인 이력이 보이지 않는다는 보고를 확인하고 최신 UI/API를 적용한다.
- 변경 전: `/publishing`은 활성 상태에 따라 승인 또는 중지 버튼 중 하나만 렌더링했다. 실행 중 API가 최신 승인 이력 조회 코드보다 오래되어 활성 정책 이력은 응답에 나타나지 않았다.
- 변경 후: 승인·중지 버튼을 항상 표시하고 현재 정책 상태에 맞지 않는 동작은 비활성화한다. API를 정상 재시작한 뒤 기존 예약 Auto 이력이 Dashboard에 표시되는 것을 확인했다.

## 변경 내용

- `apps/dashboard/app/publishing/publication-manager.tsx`: 예약 Auto 승인 및 중지 버튼을 함께 표시하고 상태와 처리 중 여부에 따라 비활성화한다.
- `apps/dashboard/app/style.css`: 두 정책 버튼을 반응형으로 배치하는 액션 레이아웃을 추가한다.
- `apps/dashboard/e2e/P5-CODEX-044-scheduled-auto.spec.ts`: 실제 페이지 구조에서 탭, 블로그 선택, 읽기 확인 버튼, 정책 버튼, 승인 이력, 비활성/활성 상태를 확인한다. API 쓰기 요청이 발생하지 않는지 확인한다.

## 런타임 적용 및 검증

- 변경 전 3100 Dashboard는 구 Production Build였다. 기존 프로세스가 API에 연결되어 있어 첫 graceful stop은 대기했다. 연결이 자연히 끝난 뒤 기존 `scripts/stop.ps1` 및 `scripts/start.ps1`로 Dashboard만 정상 종료·재시작했다. 강제 종료는 하지 않았다.
- `npm run build`를 `apps/dashboard`에서 실행해 Production Build를 갱신하고 기존 스크립트로 포트 3100에 적용했다.
- API 프로세스 시작 시각이 P5-CODEX-044 변경보다 이전이었고 승인 이력이 누락되어, `scripts/stop.ps1 -Service api -TimeoutSeconds 30 -Confirm:$false` 후 `scripts/start.ps1 -Service api`로 API만 정상 재시작했다. Health 응답은 HTTP 200이었다.
- Research Worker와 Publication Worker는 종료·재시작하지 않았다. Publication Worker heartbeat는 기존 PID에서 fresh 상태였으며 실제/Mock 큐는 0건이었다.
- 실제 `http://localhost:3100/publishing`에서 예약 Auto 영역, 네 블로그 선택 항목, 연결 확인, 승인·중지 버튼, 정책 승인 이력 및 최초 게시 승인 이력 영역을 확인했다. 데스크톱과 모바일에서 HTTP 200, 브라우저 콘솔 오류 없음, 쓰기 요청 0건을 확인했다.
- 당시 DB 정책은 이미 활성 상태였다(이 작업에서 변경하지 않음). 그 결과 승인/활성화 버튼은 비활성, 중지 버튼은 활성으로 표시되었다. 읽기 연결 확인 버튼은 블로그를 선택했을 때 활성화되며, 테스트에서는 선택 상태만 로컬 UI에서 검증했다. 연결 확인 API는 호출하지 않았다.
- 화면에 표시된 기존 정책 이력은 2026-10-29 18:25 KST, 네 등록 블로그, 일 1건 상한이었다. 별도의 최초 원고 게시 승인 이력은 없었다. 일반 Auto 상태는 manual / OFF로 유지되었다.
- 실제 예약 Auto 승인·중지, Blogger API 쓰기, 공개 게시를 실행하지 않았다.
- 화면 캡처: `.runtime/reports/P5-CODEX-044/publishing-1440.png`, `.runtime/reports/P5-CODEX-044/publishing-390.png` (로컬 검증 산출물, 커밋 대상 아님).

## 검사 결과

- Dashboard Production Build: 통과
- ESLint: 통과
- TypeScript `tsc --noEmit`: 통과
- Playwright `e2e/P5-CODEX-044-scheduled-auto.spec.ts`: 2/2 통과 (desktop/mobile)
- `git diff --check`: 통과
- API health 및 Dashboard route: HTTP 200

## 보존 및 남은 조건

- 운영 DB, 원고, OAuth 및 감사 이력은 수정·삭제하지 않았다.
- `.playwright-mcp/`, `.runtime/`, 테스트 임시 파일은 커밋하지 않는다.
- 현재 예약 Auto 정책은 작업 시작 전부터 활성 상태였다. 최초 원고별 게시 승인은 별도 상태이며 아직 기록이 없다. 이 작업은 정책을 활성화하거나 게시 승인을 만들지 않았다.
- 현재 기록의 커밋 해시는 본 문서 추가 이후 생성되는 Git 커밋으로 확인한다.
