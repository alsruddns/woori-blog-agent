# P5-CODEX-038 — Codex Local Scheduled authoring policy alignment

## 작업 기록

- 작업 ID: `P5-CODEX-038`
- 작업 일시: `2026-10-29 16:05–16:19 KST`
- 브랜치: `develop`
- 변경 사유: project baseline이 Codex/GPT 무인 예약 실행 전체를 미구현으로 간주해, 2026-10-29 15:51:06 KST Codex desktop Scheduled probe 사실과 불일치했다.
- 변경 목적: Codex Local Scheduled의 외부 초안 파일 작성만 정식 허용하고 내부 AI Provider, Import, 검증, 권리/사람 검토, auto eligibility, Blogger 공개 쓰기를 서로 독립된 게이트로 유지한다.

## 변경 전

- AGENTS, README, architecture/operations 문서가 Codex/GPT Scheduled 전체를 미구현 또는 로컬 전달 불가로 표현했다.
- 운영 상태 API는 예약 실행 상태를 알 수 없다고만 표시했고, 실제 확인된 probe와 원고 생성/Import 0건을 구분하지 않았다.
- `ai.py`의 in-process Provider 없음, generation API/내부 schedule fail-closed, scheduled importer의 review-held 출력은 실제 상태에 맞았다.

## 변경 후

- 공식 Codex desktop Scheduled Local project 실행을 **외부 draft-file exporter**로 허용한다고 명시했다. 2026-10-29 probe 실행을 사용자 확인 및 로컬 파일/hash 근거로 append-only audit event `codex.scheduled_local_file_probe.confirmed`에 기록했다.
- probe 1회와 원고 envelope/Import 0건을 분리해 Dashboard API와 자동화 화면에 표시한다. `provider_connected=false`, `generation_ready`, `auto_eligible`, `publish_ready`, Blogger write permission은 probe에 의해 변경되지 않는다.
- Codex task는 기존 Research Package와 JSON 규격만 읽고, 검증된 완성 envelope를 `incoming/`에서 원자적으로 `ready/`로 옮기도록 정책화했다. 외부 네트워크, DB/API, Blogger, Git, 승인 변경은 금지한다. 근거/권리/스키마가 불충분하면 ready 파일을 만들지 않는다.
- 11개 task의 제안 일정과 복사 가능한 주제별 지시문을 준비했다. 이 일정들은 등록 값이 아니며, Scheduled UI에서 만든 task는 0건이다.

## 실행 증거 및 제한

- probe: `.local/gpt-scheduled-import/probe/scheduled-test.json`, 268 bytes, SHA-256 `dbafc020c20ab8b97a22ca7a1d04bc6d17c2a197206a2943fcbd18a92a8651da`. JSON execution timestamp / LastWrite는 `15:51:06 KST`; NTFS CreationTime은 `15:33:29 KST`. 사용자가 Codex desktop Scheduled 실행이라고 확인했으며 이 확인을 append-only event에 기록했다. 파일은 probe metadata이지 article envelope가 아니다.
- 외부 Web/AI 호출, 예약 원고 생성, ready-file 자동 전달, Import, 자동 품질 심사, auto eligibility, Publishing Job, Blogger 쓰기/게시 실적은 각각 `0`이다. 운영 Auto OFF, Blogger write gate OFF 유지.
- 11개 실제 task 등록은 수행하지 않았다. Official task management는 Codex desktop Scheduled UI에 있고 저장소/CLI에 등록 API가 없다. 개별 cadence는 제안값이며, 계정에 추가 Codex credits가 켜져 있는지와 무과금 사용량 여유를 저장소에서 확인할 수 없어 등록·실행하지 않았다.
- 기존 research/import worker는 재시작하지 않았다. API/Dashboard 실행 프로세스도 종료·재시작하지 않았다.

## 수정 파일

- `AGENTS.md`
- `README.md`
- `services/api/woori/operations_dashboard.py`
- `services/api/tests/test_integration.py`
- `apps/dashboard/app/page.tsx`
- `apps/dashboard/app/operations/research/automation-dashboard.tsx`
- `docs/architecture/live-research.md`
- `docs/architecture/pipeline-stages.md`
- `docs/operations/live-research.md`
- `docs/operations/research-runbook.md`
- `docs/operations/multilingual-publication.md`
- `docs/operations/content-import.md`
- `docs/operations/P5-CODEX-024-gpt-work-prompts.md`
- `docs/operations/P5-CODEX-038-scheduled-task-catalog.md`
- `docs/operations/zero-cost-policy.md`
- `docs/development/P5-CODEX-037.md`
- `docs/development/P5-CODEX-038.md`

## 검증

- `pytest services/api/tests/test_integration.py::test_operations_dashboard_is_read_only_and_reports_unverified_automation services/api/tests/test_scheduled_import_inbox.py -q`: `11 passed` (격리 DB).
- `pytest services/api/tests/test_content_imports.py -q`: `11 passed` (격리 DB).
- `ruff check services/api/woori/operations_dashboard.py services/api/tests/test_integration.py`: 통과.
- Operations DB read-only snapshot: probe `1`, scheduled article import `0`, in-process Provider `false`, Codex external export supported `true`, Scheduled status `partial`, `live_writes_enabled=false`, `auto_enabled=false`.
- Frontend lint/typecheck 미완료. 시도 중 dependency가 없는 것을 확인했고 `pnpm`이 원격 dependency 다운로드를 시작해 즉시 중단했다. 전송 byte 정확량은 알 수 없으며 sanitized audit `external.provider_call.interrupted`에 남겼다. 재시도하지 않았다.
- Browser UI 확인과 실제 예약 task 실행/Import는 수행하지 않았다.
- API/Dashboard 기존 프로세스는 재시작하지 않았다. 운영 DB를 직접 읽은 새 read model 결과는 probe `1`, scheduled article import `0`, Provider `false`, external Codex export supported `true`, schedule `partial`, live writes/Auto `false`였다. 코드가 실행 중인 API 프로세스에 반영됐다고 주장하지 않는다.

## 남은 항목

- 계정 사용량/추가 크레딧 설정을 확인하고 운영자가 제안 cadence를 승인해야 한다.
- Codex desktop Scheduled에 우선 한국어/Fed 패키지 단일 1회 검증 task를 등록·실행하고, 실제 `.ready.json`/SHA-256, Import receipt, content version 및 assessment를 확인해야 한다.
- 검증·권리·사람 검토와 게시 승인이 분리되어 있다. Auto OFF 및 Blogger real writes disabled 상태로 유지한다.
- 마지막 commit SHA와 push 결과는 후속 개발 기록 커밋에 연결한다.
- 구현 커밋: `cf8f309` (`origin/develop` push 대기). 이 SHA와 푸시 결과는 후속 개발 기록 커밋으로 연결한다.
