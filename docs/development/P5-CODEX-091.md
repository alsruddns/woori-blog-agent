# P5-CODEX-091 — 예약 자동화 수동 실행 및 사용량 제한 복구

- 작업 일시: 2026-10-31 02:14 KST
- 작업 브랜치: `develop`
- 시작 기준 HEAD: `7b2644162c8671d0a0b3e6eadd7bbf50f07bc689`
- 작업 상태: 코드·프롬프트 반영 및 격리 검증 완료, 새 실행의 운영 Import와 런타임 반영은 미검증

## 변경 사유와 기존 문제

예약 실행은 실제 예약 occurrence만 허용했으며, Desktop의 명시적 Run now를 별도 수동 실행으로 분류하는 경로가 없었다. `automation-8`의 2026-10-30 20:00 KST 예약 실행은 `usage_limit_exceeded`로 실패했다. 같은 날 23:17:22 KST Run now 세션은 실제 `automation_cron_run_now` trigger를 가졌지만 당시 프롬프트가 occurrence를 요구해 조사 전에 중단됐다.

예약 실행과 수동 실행을 정확한 현재 Desktop 세션 trigger로 구분하고, 예약 provenance를 만들지 않는 별도 수동 ID·감사·Import 계약을 추가했다. 수동 Import는 기존의 human-review-only 경로를 유지하며 Publishing Job이나 Blogger 쓰기 권한을 부여하지 않는다.

## 변경 전후

- 전: occurrence 정보가 없으면 명시적 Run now도 예약 실행과 동일하게 차단됐다.
- 후: `automation_cron_scheduled`만 기존 RRULE 슬롯 및 결정적 occurrence 경로로 처리한다. `automation_cron_run_now`는 `codex-manual:<automation_id>:<uuid>` 형식 ID와 `manual_codex_import` provenance를 사용한다. 식별 불가·미지원 trigger는 fail-closed다.
- 동일 Desktop 세션의 재호출은 UUIDv5 기반 manual run ID를 재사용한다. 다른 Run now 세션은 별도 ID를 가진다.
- 최근 실제 예약 usage-limit 실패가 하나로 명확히 확인될 때만 recovery link를 기록한다. 실패 예약 실행은 성공으로 덮어쓰지 않는다.
- 예약 경로의 `chatgpt_scheduled_export`, occurrence 및 기존 자동 발행 권한은 바뀌지 않았다. 수동 경로는 원고 Import 후 검토 대기이며 자동 공개하지 않는다.

## 실제 Automation 설정 확인 및 반영

Codex Desktop 로컬 Automation 저장 파일에서 15개 ID를 확인하고 manual/scheduled trigger 분기 지침을 각 프롬프트 끝에 추가했다. 프롬프트 이외의 `id`, `kind`, `name`, `status`, `rrule`, `model`, `reasoning_effort`, `execution_environment`, `target`, `cwds`, `created_at` 값은 변경 전 백업과 비교해 모두 동일함을 확인했다. 15개 모두 `ACTIVE`다.

대상 ID: `ai`, `automation`, `automation-2`~`automation-10`, `fed-sec`, `it-ai`, `k-beauty`, `k-pop`.

원본 TOML 백업: `%USERPROFILE%\.codex\automation-backups\P5-CODEX-091-20261030T170623Z`.

변경 전후 prompt SHA-256 및 일정 검증 manifest: `docs/development/P5-CODEX-091-prompt-hashes.json`.

로컬 Codex 앱 제어 채널이 제공되지 않아 Desktop UI에서 저장 상태를 별도로 교차 확인하지 못했다. 저장된 활성 TOML 파일의 재파싱과 원본 대비 일정·모델·식별자 보존은 확인했다.

## 수정 파일

- `services/api/woori/automation_invocation.py` — current session trigger 판정, RRULE occurrence 검증, 수동 run ID 및 유일한 quota recovery 링크
- `services/api/woori/content_imports.py` — 명시적 manual automation origin 모델 및 트랜잭션 내 멱등 감사 이벤트
- `services/api/woori/scheduled_import_inbox.py` — 기존 예약 envelope와 manual envelope의 검증·Import 경로 분리
- `services/api/woori/worker.py` — Import outcome 감사 이벤트에 실행 모드·Automation·run 식별자 추가
- `scripts/resolve-codex-automation-run.py` — 실제 Desktop session trigger 확인 CLI
- `scripts/validate-scheduled-import.py` — 예약/수동 envelope 검증 CLI
- `scripts/update-codex-automation-manual-run-instructions.py` — 15개 로컬 프롬프트의 백업·검증 갱신기
- `docs/schemas/woori-manual-automation-content-import-1.0.schema.json` — 수동 Automation Import 계약
- `services/api/tests/test_automation_invocation.py`
- `services/api/tests/test_scheduled_import_inbox.py`
- `services/api/tests/test_content_imports.py`
- `docs/development/P5-CODEX-091-prompt-hashes.json`
- `docs/development/P5-CODEX-091.md`

DB migration은 추가하지 않았다. 이미 존재하는 append-only `audit_events`를 사용한다.

## 검증 결과

- 실제 과거 `automation-8` Run now session record를 resolver에 읽기 전용으로 전달: `automation_cron_run_now` → `execution_mode=manual`, `codex-manual:automation-8:ac81fac3-b7f8-5c72-a0e9-2893506605a6`로 분류. 유일하게 확인된 기존 usage-limit 예약 실패인 2026-10-30 20:00 KST 슬롯과 `usage_limit_exceeded` recovery relation을 반환했다. 이 검증은 과거 세션의 판정 검증이며 새 Codex 실행이나 원고 생성을 뜻하지 않는다.
- resolver 예약 trigger fixture: 결정적 `codex-slot:automation-8:20261030T2000KST` 식별자 확인.
- 수동·예약 Import 계약, 중복 감사, review-held 상태 및 기존 예약 Import 회귀: 변경 범위 테스트 **10 passed** (`.env.test` 전용 DB, 명령 실행 한정 test token).
- Ruff: 통과.
- Mypy 변경 모듈: 통과.
- Python compileall 및 JSON 문서 파싱: 통과.
- 운영 DB 변경 및 migration: 없음.
- Codex 모델 호출, 유료 API 호출, Blogger 게시: 없음.

## 운영 상태 및 남은 문제

- 2026-10-31 상태 확인에서 API PID 63296과 Research Worker PID 62884는 이 체크아웃 소유였으나 이전 코드 커밋을 실행 중이었다. Publication Worker와 Dashboard는 변경하지 않았다.
- Research Worker 안전 종료를 요청했지만 30초 안에 동기 작업 주기가 끝나지 않아 스크립트가 강제 종료 없이 중단했다. 생성한 stop request는 PID·시작 시각·체크아웃이 동일한 현 프로세스임을 확인한 뒤 취소해 Worker의 의도치 않은 이후 종료를 막았다. API도 재시작하지 않았다.
- 따라서 변경 코드는 테스트됐지만 API/Research Worker 운영 런타임에는 아직 반영되지 않았다. 다음 실제 Automation Run now, ready 전달 및 운영 Import ID/Content Version ID도 아직 검증되지 않았다.
- 실제 새 Automation 실행은 사용자의 Codex Desktop Run now가 필요하다. 현 세션은 Automation 실행 컨텍스트가 아니며, 과거 세션 재생으로 새 원고를 만들지 않았다.
- 이 작업에서 발생한 lifecycle stop 실패는 `.runtime/logs/service-lifecycle.log`에서 확인 가능하다. 오류 시각은 2026-10-31 02:10 KST 전후이며 Worker는 살아 있고 heartbeat가 fresh였다.
- 사용자 키워드·원고·Import·Publishing Job·Blogger 이력은 변경하지 않았다. 자동화 RRULE 15개도 변경하지 않았다.

## Git

- 커밋 해시: 후속 `git log`로 연결한다.
- 원격: `origin/develop` push 결과는 작업 완료 시 기록한다.
- 관련 문서: `docs/development/P5-CODEX-091-prompt-hashes.json`, `docs/schemas/woori-manual-automation-content-import-1.0.schema.json`.
