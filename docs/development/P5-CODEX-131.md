# P5-CODEX-131 — Codex Desktop 예약 원고 작성 복구

- 작업 일시: 2026-11-04 (Asia/Seoul)
- 브랜치: `develop`
- 시작 HEAD: `0f851e3b6c83914a32ffcf8e4851826b50f40b45`
- 구현 커밋 HEAD: `4a7e8c23e11705a433fa5439097be81875811339`
- 관련 기록: P119, P122, P123, P126, P129, P130 및 `docs/operations/scheduled-outage-recovery.md`

## 작업 사유 및 기존 상태

예약 원고가 Resolver·중복 사전검사 이후 Research Snapshot, Article envelope, ready handoff까지 이어지지 않았다. 2026-11-04 실제 Codex Desktop session transcript에서 `automation_cron_scheduled`와 공식 `automation_cron_run_now`가 확인되었고 기존 Resolver는 두 trigger를 인식했다. `composer` turn은 `current_automation_trigger_unrecognized`로 차단되었으며 이는 일반 개발 세션을 예약 실행으로 오인하지 않는 정상 보호 동작이다.

Run now 사례 두 건(k-pop, fed-sec)은 Resolver가 `execution_mode=manual`, 중복 조회 `local_status=not_found`, `draft_import_allowed=true`, `remote_status=not_checked`를 반환했다. 이후 실행은 `scripts/validate-scheduled-import.py`가 manual 계약을 처리하지 못한다고 잘못 판단하고 중단했다. 실제로 해당 validator는 `validate_envelope()`의 Pydantic union을 사용하며 scheduled와 manual 계약을 모두 받는다. manual JSON Schema도 이미 존재했다. 그래서 해당 실패 원인은 Resolver trigger 부재나 스키마 부재가 아니라 실행 지침의 오해와, 완료된 incoming 파일을 ready로 넘기는 검증 가능한 단일 명령이 없었던 점으로 확인했다.

예약 resolver의 `waiting_for_slot` progress가 기록된 뒤 실제 조사/파일 생성 없이 Desktop turn이 완료된 16:00 KST `automation-9` 세션도 확인했다. 이는 resolver 성공이나 원고 성공으로 집계하지 않았다. 기존 Task UI의 Automation 등록 상태는 로컬 TOML로만 확인할 수 있었으며 Desktop Scheduled UI 자체의 교차 확인은 불가능했다.

## 변경 목적 및 변경 전후

**변경 전:** 예약·Run now prompt에 P091/P102 관련 지침이 중첩되어 있었다. P102의 outage pending 지침과 정상 eligible import 절차가 혼재했고, Run now validator 지원 여부를 잘못 해석할 여지가 있었다. `incoming → ready` 전달은 직접 파일 이동 지침에 의존했다.

**변경 후:** 기존 `automation_cron_scheduled` 및 `automation_cron_run_now`만 지원하고 composer/불명확 실행은 계속 fail-closed다. active Automation prompt에는 최신 공통 실행 절차를 추가했다. 분명한 generation preflight(`not_found`/`failed_only` 및 `draft_import_allowed=true`)와 현재 실행 identity, envelope를 다시 검증하고, 기존 파일을 덮지 않는 exclusive handoff 명령을 추가했다. snapshot, manuscript save, schema validation, ready handoff, Research Import가 각기 독립 단계로 기록되도록 지침을 명확히 했다.

## 예약 작업 상태 조사

- 로컬 `~/.codex/automations/*/automation.toml`: 전체 21개, `ACTIVE` cron 20개, `PAUSED` 1개(`automation-10`, zh-CN). 기존 ID, RRULE, 상태, 모델, 대상, 작업 경로는 유지했다.
- 6개 Blogger 언어의 관련 예약 ID: EN/KO/JA 기존 활성 작업 및 신규 언어 `automation-11/12`(VI), `automation-13/14`(DE), `automation-15/16`(pt-BR). 로컬 설정으로만 확인했으며 공식 Desktop task list 확인은 미검증이다.
- 2026-11-04 transcript에서 Resolver가 인식한 scheduled trigger 8개(automation-6, -7, -11, -12, -3, fed-sec, it-ai, -9)와 Run now 2개(k-pop, fed-sec)를 확인했다. 이 중 완전한 Snapshot → validated file → ready handoff → Research Worker Import receipt까지 확인된 신규 종단 간 성공은 0건이다. 해당 20개 등록 전체의 오늘 정상/실패 여부를 같은 날 실행 기록만으로 분류할 수는 없어 나머지는 미확인이다.
- 기존 import root의 오늘 파일: `ready/` 0, `processing/` 0. 2026-11-04 이전 실행이 남긴 2개 `incoming/*.part`와 4개 연구 파일은 변경하지 않았다. 새 스냅샷/원고 파일을 테스트로 만들지 않았다.

## 수정 파일

- `services/api/woori/automation_ready_handoff.py`: exact resolver result, allowed local preflight, valid scheduled/manual envelope를 확인하고 same-volume exclusive hard-link로 `ready/`에 노출한다. 기존 `ready` 목적지가 있으면 실패하며 source를 보존한다. Blogger/API/DB 쓰기와 Publishing Job 생성은 하지 않는다.
- `scripts/handoff-automation-manuscript.py`: 현재 Desktop invocation을 실제 resolver로 다시 확인하고 preflight JSON을 받아 새 handoff 모듈을 호출하는 로컬 CLI.
- `scripts/update-codex-automation-authoring-recovery.py`: dry-run 기본, `--apply` 시 기존 active project Automation prompt만 갱신. task ID/RRULE/status/model/target/cwd는 검증하며 원본 TOML 백업 및 SHA-256 manifest를 보존.
- `services/api/tests/test_automation_ready_handoff.py`: 6개 언어 manual contract의 validator/handoff, scheduled slot provenance, trigger mismatch, ambiguous preflight, 기존 ready 파일 덮어쓰기 방지를 검증.
- `services/api/tests/test_update_automation_authoring_recovery.py`: dry-run 불변성, active prompt 수정, paused·외부 task 보존, 설정값 보존과 백업을 검증.
- `docs/operations/scheduled-outage-recovery.md`: unknown duplicate 상태에서 새 원고를 만들지 않도록 정리하고 scheduled/Run now schema, research snapshot, Pydantic validation 및 helper handoff를 문서화.
- `docs/development/P5-CODEX-131.md`: 본 개발 기록.

## Codex Automation prompt 반영

2026-11-04 15:55 KST에 local TOML 20개 ACTIVE prompt만 갱신했고, 16:11 KST에 실제 16:00 예약 결과에 맞춰 짧은 실행 우선 블록을 prompt 맨 앞에 추가했다. `automation-10`은 PAUSED여서 수정하지 않았다. 두 변경 모두 ID/RRULE/status/model/target/cwd 보호 검사를 통과했고 원본 20개와 manifest를 각각 별도 백업했다:

- `%USERPROFILE%\.codex\automation-backups\P5-CODEX-131-20261104T065535Z`
- `%USERPROFILE%\.codex\automation-backups\P5-CODEX-131-20261104T071105Z`

16:00 KST 실제 예약 세션(`automation-13`)은 scheduled resolver, revision 20 policy gate, duplicate preflight(`not_found`, `draft_import_allowed=true`, `remote_status=not_checked`)를 통과했으나 연구·snapshot·원고 파일 생성 전에 남은 실행 예산이 부족하다며 종료했다. 이를 성공으로 세지 않았고, 장문 진단을 줄이고 같은 turn에서 연구와 파일 handoff를 우선하도록 앞머리 실행 지침을 추가했다. Desktop Scheduled UI 반영은 별도로 확인하지 못했다.

## 테스트 및 검증 결과

- `pytest ... test_automation_ready_handoff.py test_update_automation_authoring_recovery.py test_automation_invocation.py test_resolve_scheduled_automation_cli.py test_scheduled_execution_receipts.py test_scheduled_import_inbox.py test_scheduled_pending.py`: **77 passed** (실행 우선 prefix 포함).
- Ruff 대상 파일 검사: 통과.
- 변경 Python 파일 `py_compile`: 통과.
- Import/ready handoff test: 임시 경로만 사용; 운영 `.local/gpt-scheduled-import`에 파일을 쓰지 않았다.
- Blogger 실제 쓰기/API 호출: 0건. AI API 호출: 0건. DB schema/migration: 변경 없음.
- API 8100과 Dashboard 3100 listener는 실행 중이었고 이번 수정에는 서비스 runtime 모듈을 바꾸지 않아 재기동하지 않았다. PostgreSQL 5432도 실행 중이었다.
- P130 Worker 권한 수정은 변경하지 않았다. 이번 작업에서 Worker heartbeat나 운영 Import 상태를 수정/재기동하지 않았다.

## 운영 보호 및 미완료 사항

EN/KO/JA/DE/pt-BR/VI 예약 설정, zh-CN pause, OAuth, 발행 이력, 운영 설정, stash 및 사전 존재 untracked 파일은 변경하지 않았다. 기존 예약 실패 세션이나 incoming 파일을 재실행·이동·삭제하지 않았다.

**코드 및 로컬 Automation prompt 지침 변경은 완료했으나 실제 Desktop 예약 컨텍스트에서 신규 원고 파일 저장 및 Research Import는 미검증이다.** 다음 실제 공식 예약 또는 Run now 실행에서 `research/*.research.json`, 검증된 incoming 원고, `ready/*.ready.json`, Research Worker Import receipt를 확인해야 한다. 단위 테스트와 개발 세션은 이 검증을 대체하지 않는다. 공식 Scheduled UI 반영 상태도 미확인이다.

Git 결과: `4a7e8c23e11705a433fa5439097be81875811339` (`Fix : [P5-CODEX-131] Restore scheduled authoring handoff`)을 `origin/develop`에 푸시했고 확인 당시 원격 HEAD와 일치했다. 개발 기록의 이번 보완은 뒤따르는 문서 커밋의 `git log`로 연결한다.

## 2026-11-04 16:20 KST — 운영 실행 증거 재확인 및 정정

기존 기록의 “오늘 확인된 신규 E2E/Import 0건”은 부정확해 정정한다. 2026-11-04 07:00 KST `automation-6` 실제 Desktop scheduled transcript(`rollout-2026-11-04T07-02-03-01a1a36e-fea0-7442-8e12-b8c0c1e7d17c.jsonl`)와 결과물을 대조했다. 예약 슬롯 `2026-11-04T07:00:00+09:00`, Automation ID `automation-6`, occurrence `codex-slot:automation-6:20261104T0700KST`, locale `en`인 실행이다. Research Snapshot 파일이 존재하고 JSON 파싱되며 source 5건을 포함한다. 이후 UTF-8 원고 envelope가 `processed/market-close-us-2026-11-03-en-67ac928d-0d28-4cf7-b91f-33c66d5705a4.processing.json`에 존재하고 `validate_envelope(bytes)` 검증을 통과했다. 본문 2,534자, 제목 비어 있지 않음을 확인했다. PostgreSQL 읽기 전용 조회에서 import ID `afa961f3-5687-4df8-acef-39542ed63000`, 상태 `awaiting_human_review`, 수신 시각 07:09:33 KST 및 `content.import.scheduled_origin_recorded` 감사 이벤트 ID `335282`를 확인했다. 이는 예약 실행부터 snapshot, 저장, schema 검증, Research Import까지 실제 성공한 사례 1건이다. Import 성공은 게시 승인이나 Blogger 게시를 뜻하지 않는다.

이 성공은 P131 코드 및 15:55/16:11 prompt 갱신 전 07:00 실행이므로 신규 P131 변경의 E2E 검증으로 간주하지 않는다. automation-13의 16:00 KST 실행은 Resolver와 중복 preflight까지 통과했지만 실행 예산 부족으로 조사·파일 작성 전에 끝났고, P131 우선 실행 prompt block은 16:11에 추가됐으므로 그 이후 prompt를 사용한 새 예약 실행 증거는 아직 없다. 16:20 KST automation-14 실행 transcript도 로컬 세션 기록에서 확인되지 않았다.

현재 로컬 Automation 정의는 총 21개(활성 20, 일시중지 1)다. 오늘 실제 scheduled 실행 evidence로 확인한 9개 중 완전한 Import 성공 1건(automation-6), 후속 원고 저장/Import가 확인되지 않은 미완료 2건(automation-9, automation-13), 나머지 6건은 downstream 결과를 확정할 충분한 증거가 없다. 나머지 활성 정의 11건은 오늘 실행 여부를 확인하지 못했다. Run now 2건은 invocation 및 duplicate preflight까지는 확인됐으나 파일 저장/Import까지는 확인되지 않았다. 따라서 모든 예약 자동화가 복구됐다고 단정하지 않는다.

이번 재검증은 파일 읽기와 DB SELECT만 수행했다. Blogger 쓰기 0건, 스키마/운영 설정 변경 0건이다. P131 변경 이후 공식 예약 컨텍스트에서 새 원고 파일 저장과 Import는 여전히 미검증이다.
