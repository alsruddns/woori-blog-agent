# P5-CODEX-029 — 안전한 stop.ps1 및 서비스 종료 검증

- 작업 일시: 2026-10-29 (KST)
- 브랜치: `develop`
- 작업 시작 감사 ID: `P5-CODEX-029-9557efb2-ea05-4b2f-a6f9-c9fe81d922cc`
- 변경 사유: 기존 `stop.ps1`이 API/Dashboard 위주였고 실행 중인 Worker의 현재 작업을 보호하는 종료 경로가 없었다.
- 변경 목적: 현재 체크아웃 소유가 분명한 서비스만 대화형·WhatIf 방식으로 안전하게 종료하고, Worker는 작업 주기 완료 후 협조적으로 종료한다.

## 변경 전 / 변경 후

- 변경 전: API, Dashboard만 처리했고 PID 재사용, 자식 프로세스 확인, WhatIf, Worker 종료 요청 기능이 충분하지 않았다.
- 변경 후: `api`, `dashboard`, `worker`, `all`을 지원한다. 서비스 프로세스는 실행 경로·명령줄·체크아웃·시작 시각을 대조하고, API/Dashboard는 runtime manifest에 기록된 전용 runner의 자식 프로세스만 관리한다. `conhost.exe`, VS Code/사용자 부모 터미널, PostgreSQL, 다른 체크아웃은 종료 트리에 넣지 않는다.
- API/Dashboard는 연결이 남아 있으면 종료를 보류한다. 우선 정상 종료를 요청하고, 실패 후에도 `-Force`와 서비스명·PID 목록을 입력한 추가 확인 없이는 강제 종료하지 않는다.
- Research/Evaluation Worker에는 PID·서비스·체크아웃·OS 시작 시각을 포함한 원자적 JSON 종료 요청을 전달한다. Worker는 현재 동기 작업 주기 뒤에만 요청을 확인하고 heartbeat 및 advisory lock을 정상 정리한다. 실행 중인 작업은 강제 종료하지 않는다. 일회성 Publication Worker는 진행 중 Blogger 요청이 끝날 때까지 기다리고 강제 종료하지 않는다.
- PID 스냅샷이 달라졌거나 실행 경로/명령줄/시작 시각 확인에 실패하면 해당 프로세스를 건너뛴다. 중복 서비스 인스턴스는 PID별로 별도 표시한다.

## 수정 파일

- `scripts/stop.ps1`
- `scripts/server-common.ps1`
- `scripts/status.ps1`
- `scripts/tests/stop.Tests.ps1`
- `services/api/woori/worker.py`
- `services/api/tests/test_worker_stop_request.py`
- `docs/development/P5-CODEX-029.md`

## 검증 결과

- PowerShell AST 구문 분석: `server-common.ps1`, `stop.ps1`, Pester 스크립트 통과.
- Pester 3.4: 12/12 통과. 타 프로젝트 Python/VS Code/PostgreSQL 제외, 같은 checkout 중복 PID 처리, Next/npm 실행 체인 식별, 재사용 PID 차단, 상위 PowerShell 제외, Worker 작업 중 비강제 종료, PID 확인 문구 강제, `-Force` 미지정 시 프롬프트 미호출, 내부 서비스 연결 제외, 정상 종료 우선, force 확인 거절 시 미종료, 강제 종료 시 동일 프로세스 스냅샷만 대상으로 하는 것을 확인했다.
- Python 격리 테스트: `services/api/tests/test_worker_stop_request.py` 3/3 통과. PID·서비스·루트·시작 시각 불일치 요청 거부, 올바른 요청만 제거 확인.
- Ruff: 변경 Python 파일 통과.
- `git diff --check`: 통과.
- 실제 `scripts/stop.ps1 -Service all -WhatIf -TimeoutSeconds 5`: 종료 요청 없이 현재 PID/명령줄/실행경로와 전체 확인된 API/Dashboard 자식 프로세스를 표시했다. 같은 API 프로세스 트리 안의 loopback 연결은 내부 연결로 판정했고, 외부 established 연결만 차단한다. Dashboard·API·Worker 모두 WhatIf에서만 확인했다. `.runtime/worker-stop-*.json` 생성 없음.
- 종료 후 `scripts/status.ps1` 재확인: Dashboard PID 43556, API PID 34200(리스너 자식 21720), Worker PID 15720이 계속 실행 중임을 확인했다. 이는 WhatIf 검증이며 실제 종료 검증이 아니다.
- 실제 서비스 종료, force 종료, Blogger API 호출, DB 콘텐츠 변경은 수행하지 않았다. 운영 DB에는 작업 시작 감사 이벤트만 추가했다.
- `status.ps1`은 평가 Worker도 별도 프로세스 유형으로 표시한다.

## 안전 동작 및 운영 한계

- API established 연결이 있거나 연결 상태를 검사할 수 없으면 종료를 요청하지 않는다. 연결을 종료한 뒤 다시 실행한다.
- API/Dashboard의 정상 GUI 종료가 불가능하거나 timeout 되면 대상과 영향 정보를 표시한다. `-Force`를 지정해도 정확한 확인 문구가 맞아야 한다. 관리 대상은 별도 manifest runner 및 확인된 서비스 자식뿐이다.
- Worker 종료는 `worker-stop-<PID>.json` 신호 방식이다. 새 코드로 시작된 Worker가 작업 주기 사이에서 신호를 읽어야 한다. 구 코드 Worker는 신호를 읽지 않을 수 있으며, timeout 후 실행을 보류하고 신호 파일을 남긴다. 기존 실행 터미널에서 `Ctrl+C`로 정상 종료한 뒤 `scripts/run-worker.ps1`로 최신 코드를 시작해야 한다.
- 실행 중인 VS Code 터미널, 부모 PowerShell, conhost, 다른 프로젝트 및 PostgreSQL은 종료하지 않는다. unmanaged 프로세스는 원래 터미널에서 운영자가 직접 정상 종료해야 한다.
- `scripts/start.ps1`은 API/Dashboard 전용이므로 stop의 `worker` 지원이 start/restart의 Worker 자동 실행을 의미하지 않는다. Worker는 기존 `scripts/run-worker.ps1`에서 시작한다.

## 사용 방법

```powershell
# 아무 프로세스도 건드리지 않고 대상과 현재 상태 확인
.\scripts\stop.ps1 -Service all -WhatIf

# 서비스 하나씩 대화형 정상 종료
.\scripts\stop.ps1 -Service api
.\scripts\stop.ps1 -Service dashboard
.\scripts\stop.ps1 -Service worker

# API와 Dashboard 및 Worker 종료 시도
.\scripts\stop.ps1 -Service all

# 정상 종료 실패 후 강제 종료를 고려할 때: 매번 정확한 PID 확인 문구 입력 필요
.\scripts\stop.ps1 -Service dashboard -Force
```

Worker에는 강제 종료 경로가 없다. foreground/unmanaged 서비스 또는 API 연결이 남은 경우 원래 서비스 터미널에서 `Ctrl+C`를 누르고 다시 `scripts/status.ps1`로 확인한다.

## 데이터·감사·Git

- 기존 원고, OAuth, 운영 DB 콘텐츠 및 감사 기록은 보존했다. DB 스키마 변경은 없다.
- 운영 DB `audit_events`에 작업 시작 이벤트를 append했다. 완료 이벤트는 검증·Git 완료 후 추가한다.
- 커밋 해시는 이 기록 작성 뒤 `git log` 및 후속 완료 이벤트에 기록한다.
- 남은 문제: 현재 실행 중인 프로세스는 WhatIf로만 확인했고 실제 종료는 실행하지 않았다. API 연결 2건이 남아 있어 안전 종료가 차단됐다. Worker에 새 협조 종료 코드를 적용하려면 기존 Worker를 원래 터미널에서 정상 재시작해야 한다.
