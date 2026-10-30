# P5-CODEX-062 — Windows 로그인 자동 시작 및 검증된 소스 반영

- 작업 일시: 2026-10-30 (Asia/Seoul)
- 브랜치: `develop`
- 변경 사유: Windows 로그인 후 Dashboard/API/Research Worker/Publication Worker를 안전하게 복구하고, 검증되지 않은 소스 변경이 실행 중 서비스에 자동 반영되는 위험을 막는다.
- 기존 문제: `WooriBlogAgent-Worker` 작업은 Research Worker 전용이었고 API/Dashboard/Publication Worker 자동 시작이 없었다. Worker 부모·자식 Python 실행 파일은 프로세스 목록에서 별도 프로세스처럼 보일 수 있었다. 서비스별 마지막 적용 commit과 오류 로그가 status에 노출되지 않았다.
- 변경 전: Task Scheduler의 프로젝트 작업 1개가 로그인 시 `run-worker.ps1`을 실행. PostgreSQL 대기, 전체 서비스 복구, 안전한 소스 반영 게이트 없음.
- 변경 후: 같은 프로젝트 소유 로그인 작업을 4서비스 조정 진입점으로 idempotent 업데이트한다. PostgreSQL 및 전용 DB 준비 확인 후 기존 start/status/stop 경로로 필요한 서비스만 시작한다. Publication Worker는 `scheduled-auto --continuous`로 새 부팅에서 시작하고, 이미 실행 중인 다른 모드는 중복/강제 전환하지 않고 오류로 남긴다.
- 운영 데이터: DB, OAuth, 예약 원고, Blogger 작업을 읽거나 변경하지 않는 lifecycle 검사만 수행. Worker 실행 모드·기존 작업·15개 Codex 예약은 이 변경에서 변경하지 않았다.

## 변경 내용

- `scripts/start-services.ps1`: 로그인 조정기. PostgreSQL 서비스와 `woori_blog_agent` 연결 확인, 서비스별 bounded 재시도, 기존 서비스 skip, 포트 충돌 및 heartbeat/프로세스 불일치 fail-closed.
- `scripts/manage-autostart.ps1`: `status/install/on/off/remove`. 기존 `WooriBlogAgent-Worker` 작업을 프로젝트 경로·사용자·로그온 트리거를 검증한 후 action만 갱신해 중복 등록을 방지한다. ON/OFF와 제거는 실행 중 서비스에 영향을 주지 않는다.
- `scripts/start-research-worker.ps1`, `scripts/start.ps1`: Research Worker를 숨김·분리 실행하고 DB heartbeat PID로 자식 Python 런처를 식별한다. `start.ps1 -Service research_worker|worker`를 추가했다.
- `scripts/status.ps1`: 부모 런처를 Worker 중복으로 세지 않고 heartbeat PID, 실행 모드, 작업 스케줄러, 적용 commit, 시작 시각, 로그 경로를 확인한다.
- `scripts/stop.ps1`: `research_worker`를 별도 서비스로 관리하고 `all`은 요청된 4개 서비스만 대상으로 한다. 평가 Worker는 `evaluation_worker`로 별도 지정한다. 협력 종료/Job 보호 기존 경로를 사용한다.
- `scripts/apply-verified-changes.ps1`: 명시적 `-Apply`, clean `develop`, committed HEAD, 변경 범위 PowerShell/Python/API/Dashboard 검사가 성공한 뒤 실행 코드가 변경된 서비스만 graceful stop/start한다. PowerShell 시작/상태 관리 스크립트 변경만으로 살아 있는 서비스를 재시작하지 않는다. SQL migration 경로가 포함되면 중단한다. stop 거부/불명확한 소유권에는 강제 종료하지 않는다.
- Dashboard 빌드는 현재 실행 중인 Production dist를 덮어쓰지 않도록 commit별 `.next-p5-<sha>`에 생성한다. 성공한 검증 마커의 dist만 `run-dashboard.ps1`이 사용한다.
- `scripts/service-runtime-status.py`: 운영 DB 이름을 확인하는 read-only DB/Research heartbeat 상태 명령. 예외 메시지·접속 문자열·비밀값을 출력하지 않는다.
- `scripts/register-worker.ps1`: 이전 호출 경로를 새 멱등 등록 관리기로 위임한다.

## 작업 스케줄러 동작

- 작업명: `WooriBlogAgent-Worker` (기존 이름을 유지해 중복 등록 방지)
- 트리거: 현재 Windows 대화형 사용자 로그인
- 재시도: 신규 작업은 Task Scheduler 2분 간격 최대 5회, 기존 프로젝트 작업은 등록 전 설정을 보존
- 복구 순서: PostgreSQL Windows 서비스 running + 프로젝트 DB 연결 → API `127.0.0.1:8100/health` → Dashboard `127.0.0.1:3100/research` → Research heartbeat → Publication Worker `--operations-scheduled-auto --continuous`
- 자동 시작 ON/OFF는 예약 작업만 활성/비활성화한다. OFF/Remove는 현재 실행 중 서비스들을 종료하지 않는다.
- 서비스 로그: `.runtime/logs/{api,dashboard,research-worker,publication-worker}.{stdout,stderr}.log`; lifecycle JSON 로그 `.runtime/logs/service-lifecycle.log` 및 2MiB 회전본.

## 소스 변경 반영

파일 저장 이벤트는 감시하지 않는다. 변경을 commit한 후 `scripts/apply-verified-changes.ps1`로 preview하고 `-Apply`를 명시하면 변경 범위 PowerShell/Python/API 테스트 및 타입 검사와 Dashboard lint/typecheck/Production Build(필요 범위)를 실행한다. 매 적용 시 Dashboard는 기존 실행본과 분리된 commit별 dist에 빌드한다. 실패하면 stop 요청 전에 종료한다. 성공 시 현재 commit과 Dashboard build 경로를 `.runtime/validated-source.json`에 기록하고 영향받는 서비스만 재시작한다. 부팅 조정기는 clean tracked tree와 검증된 현재 HEAD가 일치하지 않으면 시작을 거부한다. 적용 전 DB migration은 자동 실행하지 않는다.

## 테스트 및 실제 적용

- PowerShell AST 구문 분석: 결과 기입 예정.
- Pester lifecycle + stop 회귀: 결과 기입 예정.
- Python compile 및 read-only DB/heartbeat 확인: 결과 기입 예정.
- 기존 실행 서비스: 변경 전에 PID/heartbeat 확인; 불필요한 종료·재시작 없음.
- 작업 스케줄러 등록/ON/OFF/Remove 미리보기 결과: 결과 기입 예정.
- 실제 PC 재부팅 확인: 결과 기입 예정.
- Blogger 공개 게시/실제 API 호출: 0건. 이 작업에서는 Worker를 재기동하거나 새 Publishing Job을 만들지 않는다.

## Git

- 수정 파일 목록: 이 문서와 lifecycle/start/status/stop PowerShell/Python 스크립트 및 회귀 테스트.
- 테스트 결과: 기입 예정.
- 커밋 SHA: 후속 git log 참조.
- 원격: `origin/develop` push 결과 기입 예정.
- 남은 제한: 실제 재부팅은 수행하지 않음. 현재 부팅 세션의 Publication Worker 실행 모드는 기존 `scheduled-auto-and-manual`이며, 이 프로세스는 종료하지 않았다. 새 로그인 부팅에서는 새 시작 경로가 `scheduled-auto`를 지정한다. OAuth/파일 실행 환경은 사용자 로그인 세션에서만 접근하는 기존 권한 모델을 유지한다.
