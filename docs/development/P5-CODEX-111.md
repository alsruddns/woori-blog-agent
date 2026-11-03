# P5-CODEX-111 — Automatic Publication Operator Approval Control

## 작업 기록

- 작업 ID: `P5-CODEX-111`
- 작업 일시: `2026-11-03` (Asia/Seoul)
- 브랜치 / 기준 커밋: `develop` / `952222c461b3da0d525c043dda25102a034130a6`
- 구현 커밋: `12aa235c4eccf7094414ee9eb4eb2d41f2ff43a1`
- 변경 사유: 운영 승인 OFF, `manual` 발행 모드, legacy `operations_auto_approved=false`로 자동 발행 상태가 차단되는 가운데 운영자가 Dashboard에서 별도 운영 승인 상태를 확인·제어할 수 있도록 함.
- 기존 문제: 운영 제어센터에 전체 및 경로별 자동 발행은 있었으나 별도의 운영 승인 스위치와 적용 상태가 없었음. legacy 운영 승인·외부 Blogger 쓰기 권한은 별도 정책 게이트로 유지되어야 함.
- 변경 목적: 관리자 확인, 변경 사유, 감사 기록, revision, Publication Worker 확인을 거치는 독립적인 fail-closed 승인 제어 추가.

## 변경 전 / 변경 후

- 변경 전: 운영 제어센터에는 운영 승인 전용 값이 없었음. Publication Worker는 `automation-controls/2`로 확인됨.
- 변경 후: `automatic_publication_operator_approved`를 추가하고 기본값은 OFF. 자동 경로의 등록·Job 허용·Worker claim에서 이 값을 검사함. 운영 승인 ON은 전체/경로 설정, 긴급 정지, Blogger 권한, zero-cost·외부 쓰기 승인, 품질·중복·속도·일일 상한 검사를 대신하지 않음.
- 기존 `publication_mode_settings.configured_mode=manual`, `operations_auto_approved=false`, `blogger_write_mode=manual_only`를 변경하지 않음. 본 작업은 외부 Blogger 쓰기 권한을 부여하지 않음.
- 현재 운영 승인값은 OFF이며, 개발 완료만으로 ON으로 바꾸지 않음.
- 자동 발행의 과거 Job은 재승인·재실행하지 않음. 수동 발행은 기존 별도 수동 승인 게이트를 유지함.

## 운영 사전 상태 및 보존

- DB 백업: `backups/20261103T020838Z.dump`; `pg_restore --list` 검증 완료; SHA-256 `11FBF02DD2D174A5C0CEAEF40C21403E2EAA8EC46F13A5F20E49DF9B88BE3D3`.
- Migration: additive `083_automatic_publication_operator_approval.sql` 적용, 운영 schema 82 → 83. 새 승인 값은 기본 OFF.
- 설정 revision은 Migration 전후 모두 16. 기존 자동화·발행 설정은 바꾸지 않음.
- 운영값 확인: Trends ON/30분, 자동 원고 ON, 전체/Trends/예약 자동 발행 ON, 수동 ON, 큐 간격 15분, KST 일일 LIVE 상한 100, 긴급 정지 OFF. Approval OFF.
- 별도 보호 상태: `configured_mode=manual`, `operations_auto_approved=false`, `blogger_write_mode=manual_only`, Blogger 제한 감지 OFF. 이 값은 새 토글로 바꾸지 않음.
- DB 스냅샷: Content Version 508, Publishing Job 43, 발행 기록 20, 폐기 원고 2. Migration 후 원고/Job/발행/폐기 건수는 보존됨. 감사 이벤트는 마이그레이션 및 개발 상태 기록으로 추가됨.
- 기존 stash `stash@{0}` 및 초기 존재한 두 `.playwright-mcp/` 미추적 디렉터리는 보존함.
- 작업 전 API/Dashboard는 HTTP 200, Research Worker PID 36300 및 Publication Worker PID 29224의 heartbeat는 정상. 작업 중 Blogger API 쓰기는 0건.
- 안전한 반영 스크립트가 각 프로세스 트리를 graceful stop한 뒤 최신 커밋으로 재기동함. API PID `1884 → 7204`, Dashboard `18464 → 29788`, Research Worker `36300 → 14128`, Publication Worker `29224 → 26632`. 모두 프로젝트 소유 프로세스이며 PostgreSQL은 재시작하지 않음.
- 반영 후 API health 및 Dashboard automation 페이지 HTTP 200. 두 Worker가 revision 16 / `automation-controls/3`을 ack함. 예약 작업 스케줄러는 `Ready`, 기존 작업 설정은 변경하지 않음.

## 구현 내용

- 운영 승인 스위치, 승인 범위·대기 Job 수·외부 게이트·Worker revision 상태를 Dashboard에 표시.
- 승인 변경 시 확인 모달, 확인 체크박스, 변경자/사유 2자/10자 이상 검증, 낙관적 revision 검사 및 저장 결과/Worker 적용 상태 분리.
- API는 변경 전·후 승인값, 변경자·사유, 범위, revision, 정책 점검 결과를 append-only 감사 이벤트로 기록. 새 토글로 외부 쓰기 권한이나 기존 Job을 승인하지 않는 사실을 기록.
- Publication Worker claim 및 공통 자동 큐 등록이 운영 승인 OFF일 때 자동 경로를 차단함. 수동 발행 경로는 새 자동 승인 설정과 독립.
- 운영 발행 capability 조회가 새 설정 및 `automation-controls/3` Worker ack를 확인.
- 테스트 DB provisioning 및 Migration runner에 083 추가.

## 변경 파일

- `scripts/083_automatic_publication_operator_approval.sql`
- `scripts/migrate.py`
- `scripts/provision-test-database.py`
- `services/api/woori/automation_controls.py`
- `services/api/woori/automation_auto.py`
- `services/api/woori/publication_worker.py`
- `services/api/woori/publications.py`
- `services/api/tests/test_automation_controls.py`
- `services/api/tests/test_publication_origin_controls.py`
- `apps/dashboard/app/operations/automation/controls.tsx`
- `apps/dashboard/e2e/P5-CODEX-103-controls.spec.ts`
- `apps/dashboard/e2e/P5-CODEX-104-operational.spec.ts`
- `apps/dashboard/e2e/P5-CODEX-106-operational.spec.ts`
- `apps/dashboard/e2e/P5-CODEX-111-operator-approval.spec.ts`
- `docs/development/P5-CODEX-111.md`

## 검증

- Backend 변경 범위: `79 passed` — controls, provenance/worker admission, queue priority, interval, publication mode, discard.
- Ruff, mypy, `py_compile`: 통과.
- Dashboard ESLint 및 TypeScript typecheck: 통과.
- Playwright P111: 데스크톱 1440px / 모바일 390px `2 passed`; 승인 ON/OFF, 확인 모달, scope 표시, API body/revision, Worker 적용 확인, Blogger API 요청 0건, 모바일 가로 넘침 없음.
- 운영 Playwright P104 및 P106: 각각 데스크톱·모바일 `2 passed`. 실제 운영값을 읽기 전용으로 확인하고 저장 요청은 보내지 않음. 운영에 설정된 자동화 Blogger ID 선택은 3개이며 수정하지 않음.
- 운영 화면 캡처 갱신: `docs/development/assets/P5-CODEX-104-live-{desktop,mobile}.png`, `docs/development/assets/P5-CODEX-106-live-{desktop,mobile}.png`. 8개 설정 스위치, 운영 승인 OFF, Worker revision 상태의 실제 운영 화면을 기록함.
- Migration runner: 운영 DB schema 83 확인. 격리 테스트 DB Migration 경로 검증.
- 최초 통합 실행 중 provenance fixture 4건이 새 fail-closed 기본값으로 실패했으며, 자동 경로 테스트가 운영 승인을 명시적으로 설정하도록 수정 후 전체 변경 범위 79건 통과.
- 반영 스크립트의 통합 API 테스트 `60 passed`; Windows 기본 pytest 임시 폴더 ACL 문제를 격리된 `--basetemp`로 해결함. 1개의 기존 `.pytest_cache` 쓰기 경고는 테스트 실패가 아님.
- Blogger 실계정 쓰기 테스트는 수행하지 않음.

## 남은 작업 / 제한

- 코드 및 Migration 반영, API/Dashboard HTTP, Worker heartbeat 및 revision 동기화 확인을 완료함.
- 실시간 운영 변경 승인 값은 OFF. 현재 legacy `manual` / `manual_only` / zero-cost·외부 쓰기 게이트도 별도로 유지되므로 본 스위치를 ON으로 저장해도 이 조건들이 해소되지는 않음.
- 본 작업은 실제 Blogger 발행 성공이나 외부 쓰기 권한을 검증하지 않음.
- 코드 반영은 기존 실패·보류·게시 작업을 재실행하지 않음. 마지막 상태에는 과거 `automatic_publication_suspended` 및 실패 Job 이력이 그대로 남아 있음.
- 후속 개발 기록 커밋은 구현 커밋 `12aa235`를 가리키며, 자체 커밋은 `git log`로 확인 가능.

## 관련 문서

- `AGENTS.md` — Blogger write, scheduled publication, zero-cost, 감사, 서비스 수명주기 정책
- `docs/development/P5-CODEX-106.md`
- `docs/development/P5-CODEX-110-OPS.md`
