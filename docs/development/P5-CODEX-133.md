# P5-CODEX-133 — Codex Run now 수동 실행 계약 및 Import Handoff 복구

- 작업 일시: 2026-11-04 (Asia/Seoul)
- 작업 브랜치: `develop`
- 시작 HEAD / origin/develop: `edc382e85a123dbd46853285007d7859417f9cd2`
- 작업 ID: `P5-CODEX-133`
- 관련 기록: P5-CODEX-122, P5-CODEX-123, P5-CODEX-131, P5-CODEX-132 및 `docs/operations/scheduled-outage-recovery.md`

## 기존 문제 및 원인

사용자가 보고한 Run now는 실제 trigger `automation_cron_run_now`로 확인되며 resolver가 `execution_mode=manual`로 분류한다. 기존 P131 코드와 로컬 활성 Automation 프롬프트에는 manual envelope 및 handoff 지원이 이미 있었다. 따라서 validator가 manual 계약을 모른다는 가설은 코드와 맞지 않았다.

확인된 구현 간 공백은 generation 중복 사전검사 CLI 결과가 정확한 resolver invocation과 해당 실행의 봉투 계약을 함께 고정하지 않았다는 점이다. 원고 작성 단계가 별도 명령과 자연어 안내에 의존해, Run now와 scheduled가 동일한 preflight 결과를 사용하면서도 서로 다른 봉투·생성 방법·출처를 선택한다는 정보가 단일 결과에 연결되지 않았다. Import Worker는 성공 결과를 표준 출력 및 DB 감사에 반환했지만, 수동 Import 완료를 증명하는 영속 파일 Receipt는 만들지 않았다.

P131 기록상 로컬 TOML 정의는 총 21개(활성 cron 20개, 일시중지 1개)였다. 이 작업은 실행 중 재확인에서도 로컬 정의만을 근거로 삼았으며 공식 Codex Desktop UI 목록과 실제 작업 수는 확인하지 않았다. 기존 Automation ID, RRULE, 상태, 모델, 프롬프트, 대상은 수정하지 않았다.

## 변경 전 / 변경 후

- 이전: Resolver가 scheduled 또는 Run now를 분류하고, 중복검사와 envelope 작성은 따로 수행됐다. 서로 다른 계약의 선택이 generation preflight 결과에 포함되지 않았다.
- 변경: resolver가 제공한 실행 정보에 대해 공통 계약 선택기를 추가했다. `scheduled + automation_cron_scheduled`만 scheduled schema / `chatgpt_scheduled_export`를, `manual + automation_cron_run_now`만 manual schema / `manual_codex_import`를 받는다. preflight JSON에 정확한 invocation과 선택된 contract를 함께 반환한다. 검증되지 않거나 혼합된 실행은 계약을 받지 않는다.
- 이전: Import 성공 응답은 worker 호출 결과와 감사 이벤트로 확인할 수 있었으나 별도 Import Receipt 파일이 없었다.
- 변경: API Import, provenance 감사, 평가가 성공한 뒤 해시 기반의 immutable `import_receipts/*.json`을 원자적으로 생성한다. Receipt는 import/content/run IDs, 파일 해시, 평가 결과 및 `blogger_write_performed=false`만 보유한다. Receipt 기록 실패 시 원고 파일은 `processed/`로 이동하지 않아 재처리·복구 가능성을 유지한다.

## 수정 파일

- `services/api/woori/automation_authoring_contract.py`: 실행 모드·trigger·run identity를 검증하고 정확한 import 계약을 선택한다. 일반 composer 및 다른 trigger는 거부한다.
- `scripts/scheduled_duplicate_check.py`: generation preflight 출력에 resolver의 invocation과 contract를 결합한다. 계약을 선택할 수 없으면 `contract=null`과 안전한 오류 코드를 내며 기존 duplicate status/exit 의미는 보존한다.
- `services/api/woori/scheduled_import_inbox.py`: Research Import 완료 Receipt의 원자적·비덮어쓰기 저장과 성공 결과의 receipt 경로를 추가했다.
- `services/api/tests/test_automation_authoring_contract.py`: scheduled/Run now contract 선택, identity mismatch, 일반 실행 차단 및 preflight 결합 검증.
- `services/api/tests/test_scheduled_import_inbox.py`: Receipt 멱등성·불변성, 수동 envelope의 격리 API DB Import 및 감사 기록/Receipt 연결 검증.
- `docs/operations/scheduled-outage-recovery.md`: preflight의 invocation/contract 필드 및 Import Receipt 위치와 완료 기준을 문서화했다.
- `docs/development/P5-CODEX-133.md`: 본 작업 기록.

## 계약 및 handoff 결과

- Run now: `automation_cron_run_now` → `execution_mode=manual` → `woori-manual-automation-content-import/1.0` + `manual_codex_import` + exact `manual_origin`.
- 정기 예약: `automation_cron_scheduled` → `execution_mode=scheduled` → `woori-scheduled-content-import/1.0` + `chatgpt_scheduled_export` + scheduled occurrence/slot 유지.
- 두 경로 모두 같은 generation duplicate preflight 및 P131 exclusive `incoming → ready` handoff를 사용한다. Handoff에서 현재 Desktop invocation을 다시 resolve하고, clear local duplicate 상태만 허용한다. `remote_status=not_checked`는 계속 표시되며 원격 중복 확인을 의미하지 않는다.
- Research Import Receipt는 Import 후 감사 및 기계 평가가 완료된 경우에만 생성된다. Import 상태는 quality, publication approval 또는 Blogger 게시 성공을 뜻하지 않는다.
- 기존 로컬 Automation prompt들은 scheduled와 Run now의 올바른 계약 및 helper 경로를 이미 포함해 프롬프트는 변경하지 않았다. Desktop UI 자체의 prompt 동기화 여부는 확인하지 못했다.

## 테스트 및 검증

- 집중/통합 API 테스트: **101 passed**, 1 pytest cache 권한 경고. 격리 `.env.test` 데이터베이스에서 수동 Run now envelope 파일을 inbox에 넣고 FastAPI Import API(MockTransport를 TestClient로 연결)를 수행했다. Import 1건, manual-origin 감사 이벤트 1건, Receipt 파일 및 import ID/run ID 연결을 확인했으며 Blogger 쓰기는 0건이었다.
- 실행 범위에는 execution contract, ready handoff, invocation resolver, duplicate CLI/progress, scheduled/manual inbox Import, pending recovery, execution receipt, P131 prompt-updater 회귀가 포함됐다.
- Ruff: 변경 파일 검사 통과.
- mypy: 변경 API 모듈 2개 통과.
- py_compile: 변경 Python 모듈·스크립트·테스트 통과.
- 첫 pytest 호출은 사용자 Temp pytest 루트의 Windows 권한 문제로 종료 정리 단계에서 오류가 났다. 고유한 저장소 격리 basetemp로 다시 실행했고 위 결과를 얻었다. 두 번째 회귀 실행의 cache 경고는 기존 `.pytest_cache` 권한 제한이며 테스트 결과에는 영향이 없었다.
- DB schema/Migration 변경: 없음. 운영 DB 데이터 및 DB 설정 변경: 없음.
- 실제 Desktop Run now, 최신 웹 조사, Research Snapshot 생성, 원고 파일 저장, 운영 Import는 이번 작업에서 실행하지 않았다. 실제 자동화 컨텍스트에서 Import Receipt까지 확인한 운영 E2E는 미검증이다. Windows UI skill은 Codex Desktop UI 자동화를 금지하므로 Run now를 UI에서 누르지 않았다.
- 실제 Blogger API 쓰기/초안: 0건. 유료 AI API 호출: 0건.

## 운영 및 기존 데이터 보호

- 기존 예약 작업, OAuth, Blogger 연결, 원고·Job·게시 이력, 운영 설정, stash 및 사전 미추적 파일은 변경하지 않았다.
- 실제 Desktop 예약 목록, Dashboard/API/Research Worker 운영 revision 및 운영 heartbeat는 이 코드 변경 과정에서 변경/재기동하지 않았다. 이번 변경은 Research Worker import 모듈에 적용되어 있으므로 운영 반영은 커밋 후 안전한 verified service reflection을 별도로 수행해야 한다.
- 운영 적용 전 상태 조회에서 Research Worker heartbeat는 fresh였고 `job_runs` 및 `research_stage_runs`의 running 항목은 0건이었다. Publication Worker도 fresh였고 live due 및 queued는 0건이었다. 운영 설정은 읽기 전용으로 확인했으며 이 runtime의 global interval/daily limit과 블로그 scope가 기존 요청서에 적힌 값과 일치하지 않는 항목이 있어 변경하지 않았다.

## 최종 상태

- 코드 계약 선택 및 durable Import Receipt 구현: 완료.
- 격리 수동 Import/Receipt E2E 및 회귀 테스트: 완료.
- 실제 Codex Desktop Run now에서 research-to-file 생성 및 운영 Import: 미검증.
- 운영 서비스 반영: 미완료.
- 커밋 해시: 작업 마감 후 `git log`로 연결.
- 원격 push: 작업 마감 후 기록.
- 남은 문제: 공식 Desktop Run now 컨텍스트에서 연구 스냅샷, 원고 파일, `ready/` handoff, 운영 Import Receipt를 확인해야 운영 복구로 판정할 수 있다.

