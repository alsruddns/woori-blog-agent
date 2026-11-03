# P5-CODEX-119 — DE·PT-BR·VI Codex 예약 원고 작성 경로 수정

## 작업 기록

- 작업 ID: P5-CODEX-119
- 작업 시각: 2026-11-03 16:59 KST
- 브랜치: `develop`
- 시작 HEAD: `5ad1d99d0c48f2fc9a88f5479771fac901c37a43`
- 변경 사유: DE·PT-BR·VI Desktop 예약 원고가 CLI 언어 제한과 Import DB 제약 때문에 원고 작성/Import 전에 막힐 수 있음.
- 관련 문서: `AGENTS.md`, `docs/operations/P5-CODEX-038-scheduled-task-catalog.md`, `docs/operations/SCHEDULE-CODEX-003-common-instructions.md`

## 기존 문제와 변경 목적

이전에는 중복 사전 확인 CLI가 `ko/en/ja/zh-CN`만 고정 허용해 신규 예약 언어를 거부했다. 또한 API 모델은 신규 BCP 47 언어를 받아들였지만 PostgreSQL의 Import 및 현지화 이력 테이블에는 과거 4개 언어만 허용하는 CHECK 제약이 남아 실제 Import를 막았다. `CODEX_HOME`가 없는 실행 환경에서는 사용자 기본 Codex 경로를 쓰는 동작이 암묵적이었고, resolver의 일반 오류 응답은 실패 원인을 구분하기 어려웠다.

목표는 기존 Desktop 실행 증명·슬롯·중복·Import 정책을 그대로 유지하면서 언어 입력과 저장 스키마를 등록 언어 레지스트리와 일치시키고, 운영자가 안전한 오류 원인을 확인할 수 있게 하는 것이다.

## 변경 전 / 변경 후

| 구분 | 변경 전 | 변경 후 |
|---|---|---|
| 중복 확인 CLI 언어 | 4개 언어 고정 선택지 | 공통 BCP 47 검증·정규화. `de`, `pt-BR`, `vi` 허용 |
| Import 저장 제약 | 기존 4개 언어 CHECK | 등록 언어 테이블 FK. API는 활성 언어 검증을 계속 수행 |
| Codex 경로 | `CODEX_HOME` 설정을 기대하는 코드 경로 | 값이 없으면 사용자 프로필의 `.codex` 사용. 세션 증명이 없으면 fail-closed |
| Invocation 오류 | 일반 `scheduled_invocation_unverified` | 안전한 내부 reason code 보존. 파일시스템 오류는 경로를 노출하지 않는 일반 코드 |
| 예약 증명 | 사용자 자기 보고만으로 인증 불가 | 실제 Desktop session/automation 기록으로 확인. `provenance_self_reported=true`는 실행 권한이 아닌 한계 표식으로 유지 |

## 실행 환경 조사

- `develop` 시작 HEAD는 `5ad1d99d0c48f2fc9a88f5479771fac901c37a43`; 기존 stash `stash@{0}`와 미추적 파일을 보존했다.
- 사용자가 생성한 자동화 `automation-11`~`automation-16`이 `%USERPROFILE%\\.codex\\automations`에서 확인됐다. 모두 `ACTIVE`, `cron`, 프로젝트 경로 일치였다. 저장된 시각은 KST 프로젝트 슬롯으로 확인했다. 기존 15개 자동화와 구분했고 task TOML을 수정하거나 새 자동화를 만들지 않았다.
- 신규 6개 슬롯은 automation-11 10:00, automation-12 10:20, automation-13 16:00, automation-14 16:20, automation-15 20:00, automation-16 20:20 (매일)로 확인됐다. TOML에는 timezone 항목이 없어 프로젝트가 정한 `Asia/Seoul` 슬롯 정책을 적용했다.
- automation-13 및 automation-14의 실제 Codex Desktop session transcript는 각각 `automation_cron_scheduled` trigger, `Codex Desktop` originator, automation/project 경로와 일치했다. resolver는 프로젝트 파생 KST 슬롯 occurrence를 만들었고 `scheduler_occurrence_id=null`을 유지했다. `provenance_self_reported=true`는 Desktop 외부 실행의 독립 증명 한계를 표현하므로 제거하거나 성공 인증으로 취급하지 않았다.
- 관찰한 두 세션에는 연구 원고나 ready envelope가 없어 실제 작성·Import까지는 확인되지 않았다. automation-11/12/15/16 실행 세션도 관찰 범위에서 찾지 못했다. 따라서 정상 Desktop invocation resolver 확인과 실제 원고 생성 검증을 구분한다.
- `$env:CODEX_HOME`는 현재 셸에서 비어 있었으나 사용자 기본 `%USERPROFILE%\\.codex` 경로가 존재했다. 신규 자동화별 `memory.md`는 없었고 해당 프롬프트는 메모리 파일을 요구하지 않아 작성 차단 조건으로 취급하지 않았다. 메모리 부재는 예약 실행 증명으로 사용하지 않았다.
- 운영 예약 정의, OAuth 연결, Blogger 설정 및 발행 설정은 수정하지 않았다.

## DB 및 운영 보호

- Migration 적용 전 운영 DB schema version 84를 읽기 전용으로 확인했다. Import 169건 및 현지화 이벤트 12건에서 기존 언어 레지스트리 orphan은 없었다.
- 백업: `backups/20261103T075714Z.dump` (43,463,213 bytes, archive 검증 완료). 백업 파일은 커밋 대상이 아니다.
- additive Migration 085를 적용했다. 두 기존 CHECK 제약을 `languages(code)` FK로 대체해 신규 언어는 등록 레지스트리로 제한하고 기존 데이터를 보존한다. API의 active-language 검사와 운영 발행 정책은 변경하지 않았다.
- 적용 후 schema version 85. 기존 데이터 건수: external imports 169, content versions 521, publishing jobs 46, publishing records 21, audit events 144771. 운영 설정 revision 18 및 값은 유지됐다. Google Trends 30분, 자동 발행 및 승인, 긴급 정지 등 P119 대상 외 설정을 수정하지 않았다.
- Migration 상태 검증: `scripts/migrate.py --status` → `woori_blog_agent`, schema 85.
- API `http://127.0.0.1:8100/health`와 Dashboard `http://127.0.0.1:3100/`는 HTTP 200. Research Worker PID 20256 및 Publication Worker PID 5912의 heartbeat는 최신이었다. Worker 재시작은 불필요해 수행하지 않았다.
- 실제 Blogger API POST 횟수: 0. 실제 Blogger 글을 생성하지 않았다.

## 수정 파일

- `services/api/woori/automation_invocation.py`
- `scripts/scheduled_duplicate_check.py`
- `scripts/085_registered_import_languages.sql` (신규 Migration)
- `scripts/migrate.py`
- `services/api/tests/test_automation_invocation.py`
- `services/api/tests/test_scheduled_duplicate_cli.py`
- `services/api/tests/test_scheduled_import_inbox.py`
- `docs/operations/P5-CODEX-038-scheduled-task-catalog.md`
- `docs/operations/SCHEDULE-CODEX-003-common-instructions.md`
- `docs/development/P5-CODEX-119.md`

## 검증 결과

- 집중 pytest: 78 passed (6.30초). 범위: invocation resolver, duplicate CLI, scheduled Import inbox, slot gate, generation progress, pending state.
- DE, PT-BR, VI 각각 격리된 Mock API Import 경로를 통과했고 실제 Content Version 연결을 확인했다. 각 케이스는 transaction rollback으로 종료했고 Blogger writes=0, `publish_ready=false`를 확인했다.
- CLI accepts: `ko`, `en`, `ja`, `zh-CN`, `de`, `pt-BR`, `vi`; `pt-br`는 `pt-BR`로 정규화되고 잘못된 BCP 47 태그는 거부된다.
- CODEX_HOME 미설정 시 사용자 프로필 기본 경로에서 유일한 실제 session을 찾을 수 있으며, 해당 세션이 없으면 계속 fail-closed임을 테스트했다.
- Ruff: 통과. Mypy (`automation_invocation.py`): 통과. `git diff --check`: 통과.
- 격리 테스트 DB도 schema 85로 올린 뒤 통합 테스트를 수행했다. 운영 DB와 물리적으로 분리된 테스트 설정을 사용했다.

## 남은 문제 및 제한

- 실제 automation-13/14 예약 실행은 resolver와 슬롯 식별까지 확인했지만 이 관찰 회차에서 원고 파일·Research Import가 생성되지 않아 종단 간 실제 예약 작성 성공은 아직 검증되지 않았다. 다음 정상 예약 회차의 원고 작성과 Import 상태를 따로 확인해야 한다.
- automation-11/12/15/16의 실제 실행 결과는 관찰 시점에 없어 검증하지 못했다.
- task TOML은 사용자가 직접 관리하는 설정이라 변경하지 않았다. 공유 작업 지침은 BCP 47 태그 표기로 갱신했다.
- 운영 자동 발행 승인, 게시 경로, 기존 원고/Job은 변경하지 않았다.

## 완료 및 커밋

- 상태: 코드, Migration, 격리 Import 검증 완료. 실제 Desktop 예약 원고 작성·Import는 다음 실행 확인 대기.
- 커밋: 후속 `git log` 기록에서 확인.
- 원격: `origin/develop` 푸시 결과는 작업 종료 보고에 기록.
