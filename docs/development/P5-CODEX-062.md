# P5-CODEX-062 — Windows 로그인 자동 시작 및 검증 코드 반영

- 작업 일시: 2026-10-30 (Asia/Seoul)
- 브랜치: `develop`
- 변경 사유: Windows 로그인 후 Dashboard, API, Research Worker, Publication Worker를 기존 환경에서 안전하게 시작하고, 검증 완료된 코드만 선택적으로 반영하기 위함.
- 기존 문제: 기존 `WooriBlogAgent-Worker` 작업은 Research Worker 전용이었고, 나머지 서비스 시작·DB 준비 대기·코드 검증 후 서비스별 안전 재시작 경로가 통합되지 않았다. Python 부모/자식 프로세스도 중복으로 오인할 수 있었다.
- 변경 목적: 기존 Task Scheduler 작업을 재사용해 중복 등록을 피하고, 로그인 시 PostgreSQL과 운영 DB가 준비된 후 네 서비스를 복구한다. 코드 반영은 명시적인 검증 단계에서만 허용한다.

## 변경 전후

- 변경 전: 로그인 작업은 `run-worker.ps1`를 호출했고 네 서비스의 일괄 복구 경로가 없었다. 변경 미검증 상태가 실행 중 서비스에 반영될 수 있었다.
- 변경 후: `WooriBlogAgent-Worker`가 `start-services.ps1`를 호출한다. 기존 사용자/로그온 트리거와 설정은 보존하고 같은 작업을 idempotent하게 갱신한다. PostgreSQL 서비스 및 `woori_blog_agent` 연결 확인 뒤 API, Dashboard, Research Worker, Publication Worker를 누락된 경우에만 시작한다. 로그인 자동 시작의 Publication Worker 인수는 `--operations-scheduled-auto --continuous`다.
- 이미 실행 중인 서비스는 모드가 다르더라도 자동으로 종료하거나 전환하지 않는다. 따라서 현재 Worker 프로세스 모드 변경은 별도 정상 종료가 필요하며 자동 시작 경로가 다음 로그인 때 새 모드를 사용한다.
- 검증된 코드 반영은 별도 `apply-verified-changes.ps1 -Apply` 명령이다. clean `develop`, 커밋된 HEAD 및 변경 범위 검사 성공을 요구한다. Dashboard는 commit별 분리 빌드 디렉터리를 사용하고 Next가 생성하는 추적 설정 파일은 원래 바이트로 복원한다. DB migration이 감지되면 자동 수행하지 않고 중단한다.
- 검증 실패 시 서비스 중지 전에 종료한다. 서비스 재시작이 필요하면 프로젝트 소유 프로세스만 graceful stop/start한다. 소유권이 불명확하거나 정상 종료를 거부하면 강제 종료하지 않는다.

## 수정 파일

- `scripts/start-services.ps1`
- `scripts/manage-autostart.ps1`
- `scripts/start-research-worker.ps1`
- `scripts/service-runtime-status.py`
- `scripts/apply-verified-changes.ps1`
- `scripts/server-common.ps1`
- `scripts/start.ps1`
- `scripts/run-dashboard.ps1`
- `scripts/start-publication-worker.ps1`
- `scripts/status.ps1`
- `scripts/stop.ps1`
- `scripts/register-worker.ps1`
- `scripts/tests/service-lifecycle.Tests.ps1`
- `docs/development/P5-CODEX-062.md`

## 자동 시작 및 관리

- 작업 이름: `WooriBlogAgent-Worker` (기존 작업 재사용)
- 트리거: 현재 Windows 사용자 로그인, 대화형 사용자 세션
- 설치/갱신: `scripts/manage-autostart.ps1 -Action install`
- 켜기/끄기: `-Action on` / `-Action off`; 작업 비활성은 실행 중 프로세스를 종료하지 않는다.
- 상태/삭제: `-Action status` / `-Action remove`; 삭제는 소유권 확인 후 수행한다.
- 서비스는 기존 `start.ps1`, `stop.ps1`, `status.ps1` 및 전용 Worker 시작 스크립트를 통해 독립 관리한다.
- 서비스 로그: `.runtime/logs/{api,dashboard,research-worker,publication-worker}.{stdout,stderr}.log`
- 공통 lifecycle 로그: `.runtime/logs/service-lifecycle.log` (회전 제한 적용)
- `status.ps1`는 PID/실행 경로/heartbeat 기준으로 Worker를 판별하고 적용 커밋, 시작 시각, 로그 경로, Task Scheduler 상태를 표시한다.
- 무인 로그인 없는 실행은 구성하지 않았다. 현재 로컬 파일, OAuth 환경, 사용자 프로필 의존성을 유지한다.

## 검증 결과

- PowerShell AST 구문 분석: 변경 lifecycle 스크립트 10개 통과.
- Pester lifecycle 및 stop 회귀: 21 passed, 0 failed.
- Python 상태 helper: Ruff 및 `py_compile` 통과.
- 런타임 read-only 확인: PostgreSQL 서비스 `postgresql-x64-16` 실행, `woori_blog_agent` 연결 준비, Research Worker heartbeat 정상.
- 중복 방지: `start.ps1 -Service research_worker`는 기존 PID 43420을 감지하고 새 Worker를 만들지 않았다.
- Dashboard production build: commit별 격리 디렉터리 `.next-p5-<commit>`에서 성공. `next-env.d.ts` 및 `tsconfig.json`은 빌드 전 바이트로 복원된다.
- 최초 전체 `scripts/verify.ps1`는 기존 `services/api/tests/test_publication_daily.py` import 정렬 Ruff 오류에서 중단됐다. 이 파일은 이번 작업 범위가 아니며 수정하지 않았다. 변경 범위 검증은 별도로 성공했다.
- Task Scheduler 등록을 기존 작업에 적용하고 재적용해 중복 없는 idempotent 동작을 확인했다. ON/OFF 실제 전환을 확인했으며 Remove는 `-WhatIf`만 수행해 작업을 보존했다.
- 사용 중 서비스는 종료·재시작하지 않았다. Blogger API 쓰기 및 발행 Job 생성도 수행하지 않았다.
- 실제 PC 재부팅 검증은 아직 수행하지 않았다. 새 Task Scheduler action의 마지막 실행 기록도 없으므로 로그인 자동 실행 성공은 미검증이다.

## 관측된 런타임 및 제한

최종 점검 시 API PID 57288 (8100), Dashboard PID 57016 (3100), Research Worker PID 43420, Publication Worker PID 53164가 실행 중이었다. API health와 `/publishing` HTTP 응답은 200, 운영 DB readiness는 성공, 두 Worker heartbeat는 fresh였다. Publication Worker의 현재 모드는 `scheduled-auto-and-manual`이었고, 이를 불필요하게 재시작하지 않았다. 자동 로그인 시작 경로는 새로 필요한 경우 `scheduled-auto` 모드로 실행한다. 기존 실행 서비스 manifest에 적용 커밋 메타데이터가 없어 status에는 PID/heartbeat와 경로는 표시되지만 해당 서비스의 과거 적용 커밋은 비어 있다.

기존 Task Scheduler 기록은 action 교체 전 실행(`2026-10-29 오전 6:49:23`, 결과 `3221225786`)이며, 재시도는 3회/1분 간격으로 설정되어 있다. 새 시작 action은 재부팅/로그인 이후 확인해야 한다. PC를 로그인한 뒤 `scripts/status.ps1` 및 작업 스케줄러의 `WooriBlogAgent-Worker` LastRun/LastTaskResult를 확인하고 lifecycle 로그를 검토한다.

## Git 및 개발 기록

- 개발 기록은 이 문서다. 기록 당시 커밋은 Git 로그에 연결한다.
- 구현 커밋: `e518095`, `7f99401`, `d7a0ebe`, `a08729c`, `f5c99b6` (모두 `develop`).
- 최종 커밋은 Git 로그의 `P5-CODEX-062` 변경 기록으로 연결한다. 원격 푸시는 마무리 단계에서 수행한다.
- 남은 문제: 실제 재부팅 후 Task Scheduler 자동 실행 확인, 전체 저장소 verify의 기존 import-order 오류 해결, 현재 Publication Worker의 실행 모드 정합성은 다음 계획된 안전한 운영 창에서 확인해야 한다.
