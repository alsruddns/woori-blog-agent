# P5-G-SHARED-001 — 공통 Blogger OAuth 연결 단순화

- 작업 ID: P5-G-SHARED-001
- 작업 일시: 2026-10-27 (Asia/Seoul)
- 변경 사유: 단독 운영자의 4개 Blogger에 동일한 기존 전체 권한 OAuth 연결을 사용하고, 읽기 전용 연결과 감사 이력을 보존하면서 공통 매핑을 안전하게 전환할 경로가 필요함.
- 기존 문제: 연결된 `blogger` scope 토큰이 있어도 블로그별로 기존 읽기 연결을 수동 교체해야 했고, 두 번의 동의 흐름이 추가 연결을 생성할 수 있었다. 공통 계정 접근 검증과 단일 승인·감사 경로가 없었다.
- 변경 목적: 새 OAuth나 DB 컬럼을 만들지 않고 기존 연결을 선택, 읽기 전용 접근 검증, 명시적 승인, 원자적 공통 매핑의 순서로 사용하도록 지원한다.
- 변경 전 상태: DB 조회에서 전체 Blogger scope 쓰기 연결 두 건이 `connected`였고 암호화 Refresh Token이 존재했다. 연결 생성 시각은 17:53:20 및 17:53:37 KST, 마지막 상태 갱신은 17:53:29 및 17:53:45 KST, Access Token 만료 시각은 18:53:28 및 18:53:44 KST였다. 20:31 KST 재조회 시 두 토큰의 만료 시각이 지났지만 상태 행은 연결 상태이고 Refresh Token은 남아 있었다. 갱신은 실행하지 않았다.
- 계정 신원: DB와 감사 이벤트에서 Google 계정 식별자를 찾지 못했다. 두 연결이 동일 계정인지 확인하거나 추측하지 않았다.
- 기존 블로그 매핑: en, ja, ko, zh-CN 모두 기존 읽기 연결 ID를 참조했다. 네 매핑은 변경하지 않았다. 기존 읽기 및 쓰기 OAuth 행을 삭제하지 않았다.
- 비용 상태: Blogger provider `calls_allowed=false`, `manual_zero_cost_review_required` / `provider_cost_unverified`. 실제 Google API 요청은 수행하지 않았다.
- 데이터 상태: 조회 시 `publishing_records=0`, `blogger_write_operations=0`, `audit_events=1319`. 본 작업은 운영 데이터베이스에 변경을 수행하지 않았다.
- 구현: 전체 `blogger` scope를 읽기/쓰기 범위에 공통 사용, 연결된 writer 또는 진행 중인 유효 writer 동의가 있으면 중복 OAuth 시작 차단, 새 DB 컬럼 없이 기존 블로그 연결 FK 재사용. 비용 게이트 허용 이후에만 같은 토큰으로 계정 블로그 목록 GET 및 등록 URL/실제 Blog ID 비교. 5분 유효 검증 감사 이벤트 후 별도의 명시적 관리자 승인으로 모든 활성 매핑을 한 트랜잭션에서 교체하고 이전/새 연결 참조를 append-only 감사 기록. 검증 실패·만료·매핑 변동 시 기존 연결 보존.
- 수정 파일: `AGENTS.md`, `services/api/woori/google_oauth.py`, `services/api/woori/blogger_service.py`, `services/api/woori/blogger_routes.py`, `services/api/tests/test_google.py`, `apps/dashboard/app/api/blogger/[...path]/route.ts`, `apps/dashboard/app/blogger/manager.tsx`, `docs/architecture/blogger-integration.md`, `docs/development/P5-G-shared-oauth-001.md`, `CHANGELOG.md`.
- 안전 상태: OAuth 토큰·Refresh Token 값은 API·로그·감사 기록에 내보내지 않음. 실제 Blogger POST/PATCH/PUT/DELETE 없음. `writes_enabled=false`, 자동 발행 비활성, `publish_ready=false` 유지. 실제 계정/블로그 접근 및 공통 연결 지정은 아직 검증/승인되지 않음.
- 테스트 결과: 신규 회귀 테스트 4건 포함 Google OAuth 테스트 29건 통과. `scripts/verify.ps1` 통과: 전체 pytest 185건, Ruff, mypy 28개 소스, wheel, Dashboard ESLint, production build, TypeScript typecheck, `git diff --check`. 별도 `scripts/verify-secrets.py`도 통과하여 비밀정보 스캔 및 발행 차단 상태를 확인했다.
- 구현 커밋 해시: `b1bc50c` (`Update : [Blogger] Simplify shared OAuth connection management`).
- 원격 푸시: 구현 커밋 `b1bc50c`를 `origin/develop`에 푸시 완료. 개발 기록에 커밋/푸시 증거를 추가한 후속 문서 커밋도 동일 브랜치에 푸시한다.
- 관련 문서: `docs/architecture/blogger-integration.md`, `docs/operations/zero-cost-policy.md`.
- 남은 문제: 사용자가 기존 두 OAuth 연결 중 하나를 선택해야 한다. Blogger 비용의 0원 근거와 프로젝트 Billing 조건이 확인되어 게이트가 승인되기 전까지 Google API 접근 검증은 차단된다. 게이트 통과 뒤 UI에서 읽기 전용 검증을 실행하고, 결과를 확인한 후 별도의 공통 연결 지정 승인을 해야 한다. 계정 신원은 API가 검증하지 않는 한 미확인으로 유지한다.
