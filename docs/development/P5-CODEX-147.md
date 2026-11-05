# P5-CODEX-147 Codex 예약 및 Run now 조사 브로커 호출 복구

## 작업 정보

- 작업 시각: 2026-11-05 KST
- 작업 시작 HEAD: `296b9b9dcad89c249d36eee02e9cca0e698622fe`
- 시작 origin/develop: `296b9b9dcad89c249d36eee02e9cca0e698622fe`
- 시작 감사 이벤트: PostgreSQL append-only `agent.work.started`, ID `375105`
- 운영 schema/settings revision: schema 92, 설정 revision 23

## 원인

14:58 예약 실행과 15:08 공식 Run now 세션의 실제 Desktop transcript를 확인했다. 두 세션 모두 해당 실행의 Resolver와 generation Duplicate Preflight 명령은 실제로 호출했지만, 그 뒤 `scheduled-research-broker.py` 또는 `manual-research-broker.py` 호출은 없었다. 예약 프롬프트는 브로커 사용을 설명했지만 실행 순서를 강제하는 단일 명령이 없어, preflight 결과를 읽고 종료할 수 있었다.

Run now의 `CODEX_HOME` 오류는 잘못된 중단 사유였다. 프로세스 환경변수는 비어 있었지만 표준 사용자 `.codex` 디렉터리와 로그인 상태가 존재했다. Codex CLI는 ChatGPT 로그인, `codex-cli 0.166.0`, API-key fallback 비활성, 감지된 billable credential 이름 없음으로 확인했다. 격리 임시 위치에서 기존 `codex_runner`의 `--search` 경로를 실행해 웹 검색 이벤트와 결과를 확인했다. 이 프로브는 원고/스냅샷/Import/게시를 생성하지 않았다.

따라서 이 장애는 서비스 재기동만으로 해결되지 않는 Desktop 프롬프트의 명령 연결 누락이었다. 두 운영 세션이 기존 서비스를 통과해 resolver/preflight까지 도달했으므로, 원인은 API 또는 Worker heartbeat 부재가 아니었다.

## 변경

- `scripts/automation-research-stage.py` 추가: 한 실행에서 기존 generation preflight를 한 번 수행하고, 그 응답의 공식 invocation identity에 맞춰 scheduled/manual 고정 브로커 하나를 호출한다. 생성 가능한 local preflight만 통과시키고 원격 중복 상태 `not_checked`와 종합 `unknown`을 보존한다. invocation별 preflight/research package는 불변 저장하고 기존 산출물을 덮어쓰지 않는다.
- Research Package가 존재하면 동일 실행에서 Codex를 재호출하지 않고 identity를 검증해 재사용한다.
- `scripts/update-codex-automation-authoring-recovery.py` 변경: 명령을 먼저 실행하도록 최우선 절차를 교체하고, CODEX_HOME 부재/메모리 미존재가 중단 사유가 되지 않도록 표준 경로 fallback을 명시했다. 기존 resolver/preflight를 별도 중복 실행하지 않도록 하고, 동일 Desktop turn에서 research package 이후 원고 envelope, 검증, handoff를 이어가게 했다.
- 활성 로컬 TOML Automation 20개 프롬프트 업데이트. 기존 ID/활성 상태/RRULE/모델/언어/대상/작업 메타데이터를 백업과 비교해 모두 보존했다. 일시중지 1개는 그대로 유지했고 신규 Automation은 만들지 않았다.
- 백업: `C:\Users\achie\.codex\automation-backups\P5-CODEX-147-20261105T063213Z`
- 로컬 TOML 정의는 갱신했으나 Codex Desktop 공식 UI의 실제 로드 상태는 이 작업에서 확인하지 못했다. 컴퓨터 사용 skill의 제한 때문에 Desktop UI를 자동 조작하지 않았다.
- Google Trends, 발행 승인, Blogger OAuth, 게시 이력, 기존 큐 설정은 변경하지 않았다.

## 사전 운영 확인

- Research Worker: PID 21732, heartbeat 정상.
- Publication Worker: PID 20068, heartbeat 정상, mode `operations-scheduled-auto-and-manual-and-trends`.
- 활성 Research authoring 작업: 0. Publication Worker 진단상 due live/scheduled/manual 작업: 0. 기존 queued/preserved 항목은 유지했다.
- 발행 상태: AutoMode `auto`, AutoPolicyActive `true`, operations approval `true`, write mode `public_write_approved`, 최소 간격 15분, 일일 자동 한도 100, 승인 블로그 6개.
- 현재 발행 보류 사유가 붙은 기존 항목과 기존 Import 이력은 변경하지 않았다.

## 검증

- 격리 CLI 테스트: research stage, prompt updater, scheduled research, invocation 경로 **41 passed**. pytest 공유 임시폴더 권한 문제를 피하도록 고유 `.runtime` basetemp를 사용했다.
- Ruff: 변경 Python 파일 통과.
- py_compile: 변경 Python 파일 통과.
- `git diff --check`: 통과.
- 별도 API key/종량제 AI API 호출: 0.
- Blogger write: 0.
- 격리 테스트는 preflight 뒤 수동/예약 broker 선택과 identity/status 보존을 검증했다. 실제 공식 새 Desktop 예약 또는 Run now에서 원고 파일/Import Receipt가 생성됐다는 증거는 아직 없다. 과거 실패 슬롯은 재실행하지 않았다.

## 운영 반영 계획 및 남은 확인

- 코드/테스트/기록을 develop에 커밋·푸시한 뒤 `scripts/apply-verified-changes.ps1 -Apply -Confirm:$false`로 공식 검증·반영을 실행한다.
- 사용자 요청에 따라 변경 적용 후 FastAPI, Dashboard, Research Worker, Publication Worker를 공식 스크립트로 정상 종료·재기동하고 HTTP 상태, PID, heartbeat, 정책을 재검증한다. 강제 종료 및 Blogger 쓰기는 하지 않는다.
- 로컬 Automation prompt 파일 반영은 확인됐지만 실제 Desktop 예약에서 새 stage를 실행한 E2E는 아직 미검증이며 다음 새 공식 Run now/예약 실행에서 확인해야 한다.

## 변경 파일 및 커밋

- `scripts/automation-research-stage.py`
- `scripts/update-codex-automation-authoring-recovery.py`
- `services/api/tests/test_automation_research_stage_cli.py`
- `services/api/tests/test_update_automation_authoring_recovery.py`
- `docs/development/P5-CODEX-147.md`
- 구현/운영 반영 commit 및 완료 감사 이벤트는 반영 후 이 기록의 후속 항목으로 추가한다.
