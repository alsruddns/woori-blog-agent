# P5-CODEX-117 — 예약 실행 슬롯 조기 진입 복구

- 작업 일시: 2026-11-03 (Asia/Seoul)
- 작업 ID: P5-CODEX-117
- 브랜치 / 기준 HEAD: `develop` / `d8b03c693258fc19ee59bfa1b8ba8edb8097489a`
- 변경 사유: 등록된 예약 슬롯보다 몇 분 일찍 시작된 Codex Desktop 실행이 원고를 만들지 않고 진행 상태에 남음
- 관련 문서: `docs/operations/scheduled-outage-recovery.md`, `docs/operations/SCHEDULE-CODEX-003-common-instructions.md`

## 문제와 원인

2026-11-03 09:00 KST 슬롯의 실제 실행은 08:56:06 KST에 시작됐다. 실제 Codex Desktop 세션의 Automation ID는 `automation-7`, 저장된 RRULE은 `RRULE:FREQ=WEEKLY;BYDAY=TU,WE,TH,FR,SA;BYHOUR=9;BYMINUTE=0`이다. Automation TOML에는 별도 timezone 필드가 없으며 프로젝트 occurrence 검증 규칙의 `Asia/Seoul`을 사용한다.

실행 세션, task-start 이벤트와 등록된 RRULE을 대조한 결과 슬롯 계산은 09:00 KST로 정확했고, occurrence는 `codex-slot:automation-7:20261103T0900KST`로 보존됐다. 중복 사전 검사는 `local_status=not_found`, `draft_import_allowed=true`, `remote_status=not_checked`를 반환했다. 하지만 실행이 슬롯보다 이르다는 상황을 기다림 또는 재개 상태로 전환하는 처리가 없어 원고 작성 전에 종료됐고, 마지막 기록은 `duplicate_check_running`이었다. 이 실행에서 원고, Import 또는 Blogger 쓰기는 발생하지 않았다.

## 변경 전 / 변경 후

- 변경 전: 예약 슬롯보다 이른 실행이 즉시 다음 단계로 넘어가거나 원고 없이 종료될 수 있었고, 중복 검사 진행 이벤트가 최종 상태처럼 남을 수 있었다.
- 변경 후: 실제 세션과 등록 Automation을 먼저 검증한다. 예정 슬롯까지 5분 이내면 진행 상태를 기록하고 한 번만 최대 300초 대기한다. 5분을 초과해 이르거나, 대기가 중단되거나, 5분 넘게 늦게 시작하면 `deferred`를 기록하고 콘텐츠 생성을 차단한다. 정상·허용 지연 실행은 저장된 슬롯 및 동일한 deterministic occurrence를 유지한다.
- 같은 generation preflight가 `duplicate_check_running`과 `duplicate_check_completed`를 기록한다. 예상된 preflight 예외도 sanitized 결과로 종료 상태를 기록하며, 종료 상태를 기록할 수 없으면 `unknown`으로 fail-closed한다.
- 기존 08:56 실행에는 `deferred` 이벤트를 추가했다. 기존 progress/audit 행은 수정하지 않았고 해당 occurrence와 연결된 incoming/ready/pending 파일도 발견되지 않았다. 과거 회차를 다시 실행하거나 원고를 생성하지 않았다.

## 예약 정의 및 운영 보호

- 실제 Local Automation 정의는 읽기 전용으로 확인했다. `automation-7`은 `ACTIVE`이며 RRULE을 유지한다. 사용자 생성 DE/PT-BR/VI 예약의 `automation-11`~`automation-16`은 기존 활성 상태로 확인했다. `automation-10`은 기존 `PAUSED` 상태로 유지된다.
- 예약 정의, ID, RRULE, 언어·블로그 설정은 만들거나 변경하지 않았다.
- Google Trends 30분, Blogger 글로벌 발행 간격 15분, KST 일일 LIVE 상한 100, 예약→수동→Trends 우선순위, 6개 활성 Blogger, ZH-CN 신규 운영 중단, 기존 승인·OAuth 설정은 변경하지 않았다.
- DB Migration 없음. 기존 백업 `backups/20261103T051845Z.dump` (42,678,510 bytes)의 카탈로그 검증 결과를 시작 감사에 참조했다.
- 실제 Blogger API 쓰기 0건. 신규 원고 작성·Import 없음.

## 수정 파일

- `services/api/woori/scheduled_slot_gate.py` — 1회 제한 대기, KST-aware 슬롯 비교, 조기/지연 보류 상태
- `services/api/woori/automation_invocation.py` — 현재 검증된 Desktop 세션에서 정확한 Automation ID를 읽는 helper
- `services/api/woori/scheduled_pending.py` — 대기·중복검사 완료·생성·Import·발행·보류 progress 상태 허용
- `scripts/resolve-codex-automation-run.py` — 예약 정책 처리 전에 슬롯 대기/종료 gate 적용
- `scripts/scheduled_duplicate_check.py` — 실행 ID 검증, slot gate 적용, 중복 검사 시작/완료 이벤트 기록
- `scripts/scheduled-progress.py` — 새 단계 상태 기록 지원
- `services/api/tests/test_scheduled_slot_gate.py`
- `services/api/tests/test_scheduled_duplicate_generation_progress.py`
- `services/api/tests/test_automation_invocation.py`
- `services/api/tests/test_scheduled_pending.py`
- `docs/operations/scheduled-outage-recovery.md`
- `docs/operations/SCHEDULE-CODEX-003-common-instructions.md`
- `docs/development/P5-CODEX-117.md`

## 테스트 및 서비스 반영

- 집중 테스트: 42 passed. Mock clock/sleep 및 mocked duplicate preflight만 사용했고 Blogger 호출은 없다.
- Ruff: 통과. 변경 API 모듈 3개 mypy: 통과.
- 첫 pytest 실행은 테스트 자체는 통과했으나 공용 Windows pytest temp 경로 정리에서 권한 오류가 발생했다. 격리된 `--basetemp`와 cache plugin 비활성화로 재실행해 42건 정상 종료를 확인했다.
- 반영 전 PID: Dashboard 28792, API 20260, Research Worker 31708, Publication Worker 34796. 저장소 검증 후 서비스 반영 스크립트가 API와 Dashboard를 정상 종료·재기동했고, Research/Publication Worker도 graceful stop 후 새 코드로 시작했다. 강제 종료는 없었다.
- 반영 후: Dashboard PID 8212 / HTTP 200, API PID 5704 / HTTP 200, Research Worker PID 37424 / heartbeat fresh, Publication Worker PID 26404 / heartbeat fresh. 네 서비스 모두 적용 커밋 `b478091dc105b5ce151938ef31ce4c9a1b7c6a40`을 사용한다. 다른 프로젝트와 PostgreSQL 서비스는 건드리지 않았다.
- 작업 시작 append-only 감사 이벤트: `agent.p5_codex_117.started`, ID `315991`. 기존 08:56 실행의 `deferred` progress는 API에 동기화됐고 audit ID는 `316041`이다. 기존 `duplicate_check_running` 행은 보존됐다.
- 안전 반영 검증은 API 변경 테스트 77 passed, API 전체 Ruff, 변경 모듈 mypy 7개 통과, 격리 Python wheel 생성, Dashboard lint/typecheck/build를 완료한 뒤에만 서비스를 재기동했다. 별도 집중 테스트 42건도 통과했다.

## 남은 문제 / 완료 기록

- 과거 09:00 실행은 실제 세션에서 종료되어 원고와 Import가 없다. 복구를 위해 해당 슬롯을 재실행하지 않았다. 다음 정상 등록 슬롯부터 새 gate가 적용된다.
- 구현 커밋: `b478091dc105b5ce151938ef31ce4c9a1b7c6a40`. 최종 개발 기록 커밋은 `git log -- docs/development/P5-CODEX-117.md`로 확인한다.
- 개발 기록 자체의 커밋·원격 반영과 작업 완료 감사 이벤트는 최종 `git log`, `origin/develop` HEAD, PostgreSQL `agent.p5_codex_117.completed` 이벤트로 확인한다.
