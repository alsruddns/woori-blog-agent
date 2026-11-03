# P5-CODEX-122 — Codex 예약 원고 작성 긴급 복구

- 작업일: 2026-11-03 (Asia/Seoul)
- 브랜치: `develop`
- 시작 HEAD: `a7cebfac8be3c818e5802a2e8095c3aa41ac98d3`
- 작업 ID: `P5-CODEX-122`
- 최종 커밋: 이 기록을 포함한 커밋은 `git log -- docs/development/P5-CODEX-122.md`에서 확인한다.

## 목표와 기존 상태

automation-15(브라질 정치, `pt-BR`, Blogger `2780805325207451782`) 예약 실행에서 `memory.md`가 없고 실행 모드 확인이 30초 안에 끝나지 않아 작성·Import가 중단됐다. 기존 등록 예약은 수정하거나 재생성하지 않고, 해당 문제의 실제 명령·진행 기록을 조사해 6개 활성 언어의 공통 예약 경로를 안전하게 복구한다.

시작 시 `develop`이었고 HEAD는 `a7cebfac8be3c818e5802a2e8095c3aa41ac98d3`였다. 추적 파일 변경은 없었으며 기존 stash와 다수의 사전 미추적 파일을 보존했다. 추가 Migration은 없고, 원고·OAuth·Job·게시 이력에는 변경을 가하지 않았다.

## 원인 조사

실제 Desktop 세션 `01a1a10f-5945-70a3-b4ee-793ec544c10e`는 2026-11-03 19:58:20 KST에 `automation_cron_scheduled`로 시작했고, 유효한 Automation ID는 `automation-15`, 설정 슬롯은 20:00 KST였다. 저장된 실행 도구 호출은 다음 명령을 하나로 묶었다.

```powershell
Get-Content -Raw C:\Users\achie\.codex\automations\automation-15\memory.md; Get-Content -Raw docs/operations/scheduled-outage-recovery.md; .\.venv\Scripts\python.exe .\scripts\resolve-codex-automation-run.py --automation-id automation-15
```

작업 디렉터리는 `C:\Users\achie\git\woori-blog-agent`, 실행 도구의 대기 한도는 30초였다. 세션 기록에는 memory 파일 부재 오류와 운영 문서 출력이 남아 있고, 도구 결과는 30.3초 후 반환됐으나 resolver JSON·종료 코드·PID/session ID가 상위 호출에 보존되지 않았다. 따라서 이 실행의 resolver 종료 상태와 하위 PID는 사후 확인할 수 없다.

같은 세션의 진행 기록은 19:58:27 KST에 `waiting_for_slot`이었고, 예약 슬롯은 20:00 KST였다. resolver는 확인된 예약 실행에 대해 최대 5분까지 한 번 대기하는 기존 정책을 수행 중이었다. 30초 반환은 실행 모드 판정의 30초 정지가 아니며, 예약 슬롯 대기보다 짧은 도구 대기 한도와 session ID 미보존이 결합된 문제였다. 세션은 19:58:58 KST에 완료됐고 실행 도구 호출은 한 건이었다. 해당 슬롯의 완료 receipt, terminal progress, `incoming`/`ready`/`pending` 원고는 없었다. 같은 슬롯의 현재 resolver 프로세스도 발견되지 않았다.

실제 세션을 사후 읽기 전용으로 resolver 함수에 전달했을 때 `scheduled`와 `2026-11-03T20:00:00+09:00`가 확인됐고 처리 시간은 777ms였다. 이는 사후 세션 판정만 검증하며, 해당 회차가 작성·Import된 증거는 아니다.

같은 패턴이 `automation-2`의 30.2초 resolver 호출에서도 관찰됐다. 2026-11-03 로컬 설정에는 16개 정의(15 ACTIVE, 1 PAUSED)가 있다. 이는 로컬 TOML 수치이며 Codex Desktop Scheduled 화면에서 확인한 실제 등록 수와 동일하다고 보증하지 않는다. 당일 활성 설정 15개 중 작성 성공을 증명하는 `ready` 원고/Import artifact는 0개였다. 현재 로컬 증거 기준 분류는 다음과 같다.

- 정상 원고 저장 확인: 0
- 미완료 상태: 4 (automation, automation-2, automation-3, automation-15; 각각 슬롯 대기 또는 terminal duplicate 결과가 남지 않음)
- 정책상 defer: 2 (automation-7, automation-8; 기사 작성 성공으로 세지 않음)
- 실행/작성 결과 미확인: 9 (resolver/progress 일부만 있거나 당일 실행 증거 없음)

`automation-3`은 `duplicate_check_running`에서 terminal 결과가 확인되지 않아 별도 미완료로 분류했다. 같은 날 6개 활성 언어의 설정과 BCP 47 정규화 경로를 검증했지만, 실제 예약 세션에서 신규 원고 생성이 완료됐다는 의미는 아니다. `zh-CN` 설정은 기존 PAUSED 상태로 유지했고 신규 작성 경로를 실행하지 않았다.

## 변경 사항

### `C:\Users\achie\git\woori-blog-agent\scripts\resolve-codex-automation-run.py`

resolver 시작, 실제 실행 모드 판정, 슬롯 대기 시작/완료, 종료/오류 시점을 JSON 형식의 stderr 진단으로 즉시 flush한다. PID, 실행 위치, automation ID, 슬롯, 대기 초, 경과 ms를 출력하고 최종 JSON에 PID와 전체 경과 시간을 넣는다. 오류 메시지는 `ValueError` 내부 사유 코드만 유지하며 OS 오류의 개인 경로를 출력하지 않는다. 실행 모드를 판정하지 못하면 `resolved=false`로 fail-closed한다. 프로세스를 임의 종료하거나 예약 모드를 추측하지 않는다.

### `C:\Users\achie\git\woori-blog-agent\docs\operations\scheduled-outage-recovery.md`

예약별 memory 파일이 없는 경우를 최초 실행으로 처리하고, 정확한 `CODEX_HOME/automations/<verified-id>/memory.md`만 동일 디렉터리 임시 파일과 exclusive atomic rename으로 초기화하도록 규칙을 추가했다. 문서 읽기와 resolver 실행을 분리하고, 긴 슬롯 대기 때 반환된 동일 process/session ID를 최종 결과까지 polling하도록 했다. 프로세스나 결과가 불확실하면 `BLOCKED`로 남기고 재실행하지 않으며, 다른 슬롯 메모리 복사·기존 기록 덮어쓰기·실행 중 잠금 삭제를 금지한다.

### `C:\Users\achie\git\woori-blog-agent\services\api\tests\test_resolve_scheduled_automation_cli.py`

resolver 진단 순서, 슬롯 대기 관찰 가능성, 시간 초과/모드 미확인 시 차단 동작을 mock으로 검증한다.

### `C:\Users\achie\git\woori-blog-agent\services\api\tests\test_scheduled_execution_receipts.py`

동일 occurrence receipt의 재호출은 멱등이고, 다른 세션이 같은 슬롯을 선점하려 하면 충돌로 차단되며 최초 영수증을 덮어쓰지 않는 것을 격리 경로에서 검증한다. 운영에는 이미 있던 고유 receipt 경로를 사용하며 receipt를 삭제하지 않는다.

### `C:\Users\achie\.codex\automations\automation-15\memory.md` (저장소 외부)

검증된 자동화 디렉터리에는 memory 파일이 없었고, 링크/재분석점이 아니며 해당 슬롯 실행 프로세스도 없음을 확인했다. 기존 파일이 없을 때만 동일 디렉터리 임시 파일에 task-specific 최초 실행 안내를 쓰고 `fsync` 후 원자 rename했다. 다른 예약의 메모리는 복사하지 않았고 기존 파일은 덮어쓰지 않았다. 20:00 슬롯은 미완료로 사실대로 적었으며 원고 성공으로 표기하지 않았다.

## 검증 결과

최종 집중 테스트 명령(격리된 local test DB와 테스트 전용 임시 `ADMIN_TOKEN` 사용):

```powershell
python -m pytest -p no:cacheprovider --basetemp=<isolated-p122-temp> -q `
  tests/test_resolve_scheduled_automation_cli.py `
  tests/test_automation_invocation.py `
  tests/test_scheduled_slot_gate.py `
  tests/test_scheduled_duplicate_cli.py `
  tests/test_scheduled_duplicate_generation_progress.py `
  tests/test_language_codes.py `
  tests/test_scheduled_pending.py `
  tests/test_scheduled_occurrence.py `
  tests/test_scheduled_import_inbox.py
```

- 최종 통합 결과: **102 passed in 6.65s**, 0 failed/error. receipt 경합 회귀 테스트도 포함했다.
- 테스트에는 `CODEX_HOME` 미설정 fallback, 검증 불가 모드 차단, KST 슬롯 대기/지연, 중복 및 pending idempotency, de/pt-BR/vi 지원, 기존 언어 코드, Import inbox를 포함한다. 별도 확인에서 `en`, `ko`, `ja`, `de`, `pt-BR`, `vi`는 정상 정규화됐다.
- 호출 도구가 30초 대기 후 계속 실행 중인 session ID를 반환하면 기존 호출을 polling해야 한다는 절차를 운영 문서에 명시했다. timeout을 강제종료나 무조건 재시도로 처리하지 않는다.
- 현재 일반 개발 세션에서 Automation ID는 있지만 `CODEX_THREAD_ID`가 없는 resolver CLI는 `status=blocked`, `current_codex_thread_id_unavailable`, exit 2, 223ms로 차단됨을 확인했다. scheduled라고 가장하거나 작성 경로를 열지 않았다.
- 처음 실행한 테스트 명령은 저장소 루트 import path 누락으로 수집 실패했고, 다른 1회는 테스트 전용 `ADMIN_TOKEN` 미설정으로 DB fixture 오류가 발생했다. 격리 DB에 테스트 문자열을 설정한 최종 실행은 정상 통과했다.
- 실제 Blogger write: **0건**. 유료 AI 호출: **0건**. 운영 승인·예약 설정·자동 발행 값 변경: 없음.

## 운영 복구 판정

- automation-15의 2026-11-03 20:00 KST 슬롯은 기한이 지나 이미 미완료이며 재실행하지 않았다.
- automation-15 최초 실행용 memory 파일은 생성 완료됐다.
- CLI/공통 복구 지침 개선 및 mock/격리 테스트는 완료됐다.
- **실제 Codex Desktop 예약 컨텍스트에서 새 원고 생성 및 파일 저장은 미검증**이다. 다음 실제 automation-15 예약 실행(기존 RRULE 유지)에서 resolver 단계 진단과 최종 process 결과, duplicate preflight, 검증된 `ready` 파일까지 별도 확인해야 운영 복구 완료로 판정할 수 있다. 예약/프롬프트를 변경하거나 수동 Run now로 위장하지 않았다.

## 보존 및 남은 문제

- 기존 15개 ACTIVE 및 1개 PAUSED 로컬 TOML, ID, RRULE, 프롬프트, Blogger/OAuth/승인/게시 이력은 수정하지 않았다.
- 기존 stash, 미추적 파일, 실행 중 프로젝트 서비스는 보존했다. 같은 슬롯을 소유한 활성 resolver 프로세스는 없었고 이를 강제 종료하지 않았다.
- DB Migration 없음. PostgreSQL 개발 감사 로그에 작업 시작 이벤트를 append했다. 완료 이벤트는 코드·문서 커밋 이후 append한다.
- 실제 예약 UI 등록 개수, 실제 예약 컨텍스트 생성·파일 저장, 그 뒤 Import 성공은 다음 일정 실행/운영 Worker 확인이 남았다.
- 관련 정책 문서: `docs/operations/scheduled-outage-recovery.md`, `docs/operations/SCHEDULE-CODEX-003-common-instructions.md`, `docs/operations/P5-CODEX-024-gpt-work-prompts.md`.
