# SCHEDULE-CODEX-003 — 예약 작업 Export 계약 및 중복 사전 조회

- 작업 일시: 2026-10-29 (KST)
- 브랜치: `develop`
- 변경 사유: P5-CODEX-043 중복 조회 API는 구현돼 있었으나, 공통 Scheduled prompt가 API 호출을 전면 금지하고 Pydantic validator만 허용해 실제 예약 절차와 저장소 계약이 어긋나 있었다.
- 변경 목적: 예약 작업에 비밀값·DB 직접 접근 없이 기존 읽기 전용 중복 조회를 사용할 수 있도록 고정 로컬 CLI와 공통 지침을 연결한다.
- 변경 전: 중복 endpoint `POST /admin/research/content-imports/duplicate-check` 존재. Codex prompt에서는 이 호출이 금지되어 예약 작업이 로컬 파일만으로 중복 확인하거나 중단할 수 있었다. 저장소에는 Scheduled task live 설정을 관리하는 API가 없다.
- 변경 후: `scripts/scheduled_duplicate_check.py`가 고정 주소 `127.0.0.1:3100`의 same-origin Dashboard 프록시만 호출한다. Origin을 고정하고 redirect를 거부하며, 전송/응답 오류는 모두 `unknown`으로 반환한다. 프록시는 서버 보관 admin credential을 주입한다. 중복 preflight가 만드는 bounded audit event 외에는 원고·DB 콘텐츠·승인·발행·Blogger 상태를 변경하지 않는다.
- 처리 규칙: `already_published`면 중단, `already_imported`면 새 원고 생성 금지, `failed_only` 또는 `not_found`면서 `blogger_read_complete=true`일 때만 새 `original` ID 허용, `unknown` 또는 부분 읽기는 중단한다. Pydantic envelope validator는 동일하게 `scripts/validate-scheduled-import.py`를 사용한다. 최종 파일은 `incoming/*.part`에서 검증한 뒤 `ready/*.ready.json`으로 원자적 이동한다.
- 안전 정책: 예약 작업은 실제 Scheduled export일 때만 `generation_method=chatgpt_scheduled_export`를 사용한다. 신규 원고는 `relation=original`, `parent_content_id=null`, 고유 UUID. 예약 작업은 Blogger API 직접 호출·DB 직접 연결·게시 Job 생성·승인 변경을 하지 않는다.

## 실제 예약 설정 및 현재 운영 증거

- 공식 OpenAI 안내는 예약 작업을 Scheduled 화면에서 조회·수정하고, 로컬 파일 작업은 데스크톱 앱과 컴퓨터가 사용 가능해야 한다고 설명한다: [Set up scheduled tasks](https://developers.openai.com/training/walkthroughs/scheduled-tasks). 현재 사용 가능한 도구에는 Codex Desktop Scheduled 작업을 나열·수정하는 connector가 없으며, Computer-use 제한상 ChatGPT 데스크톱 UI를 자동 조작하지 않았다. 따라서 실제 15개 prompt의 변경 전후와 저장 상태는 **검증/반영하지 못함**으로 기록한다. 저장소의 P5-CODEX-038 카탈로그는 11개 제안 항목이며 라이브 15개 설정의 권위 있는 사본이 아니다.
- 변경 전후에 기존 일정, 모델, 주제, 대상 블로그 설정은 건드리지 않았다.
- 로컬 processed envelope 2개 및 운영 DB Import 2개가 확인됐다. 둘 다 진짜 envelope의 `generation_method=chatgpt_scheduled_export`로 저장됐으며 `awaiting_human_review`다:
  - 한국어 정치 원고 Import `7fcc5fca-a76c-47e1-b54a-7795b5b66287`, content ID `politics-kr-20261029-ko-a7e0b673-2cdb-4917-99fd-ba5bd3bd873a`.
  - 일본어 정치 원고 Import `9bd1706b-5e0a-4cb4-a7fd-d4949b9ecad7`, content ID `politics-jp-20261029-ja-ed65328b-28a5-4bfe-a1c4-391b598db11c`.
- 두 원고의 최신 예약 Auto evidence assessment는 모두 `held`: source reuse terms, live source retrieval/hash, claim-to-source spans, human claim review, human rights review가 미충족. 따라서 이 데이터에서 auto eligible 또는 새 발행 Job 성공 증거는 없다.
- 검사 시 `.local/gpt-scheduled-import/incoming/`에 기존 `.part` 파일 1개가 있어 진행 중 입력 보존을 위해 열거나 이동하지 않았다. `ready/` 파일은 0개였다.
- 현재 worker status: Dashboard 3100 및 API 8100 listening. Publication heartbeat PID `41992` 정상, `LiveQueued=0`, `LiveDue=0`, idle `no_queued_job_in_enabled_lane`; 운영 `AutoMode=manual`, `AutoPolicyActive=False`. Worker는 중지·재시작하지 않았다.
- 이 변경 이후에 시작된 실제 예약 task run은 없다. 새 ready 파일/Import/assessment/Job/게시 URL을 새 작업 성과로 계산하지 않는다. Blogger 쓰기도 호출하지 않았다.

## 변경 파일

- `scripts/scheduled_duplicate_check.py`
- `services/api/tests/test_scheduled_duplicate_cli.py`
- `AGENTS.md`
- `docs/operations/P5-CODEX-038-scheduled-task-catalog.md`
- `docs/operations/content-import.md`
- `docs/development/SCHEDULE-CODEX-003.md`

## 검증

- 관련 pytest: duplicate CLI, duplicate API, scheduled inbox, content import — 37 passed.
- Ruff 대상 검사 통과.
- Python compileall 통과.
- `git diff --check` 통과.
- 실제 예약 실행/15개 prompt 저장 반영/이번 변경 후 자동 Import/auto eligibility/발행 Job/Blogger 공개 URL: 검증되지 않음.

## 남은 작업

1. Codex Desktop Scheduled 화면에서 기존 15개 작업 각각의 공통 instructions에 저장소의 갱신된 공통 prompt를 적용한다. 일정·모델·주제·대상 블로그 값은 유지한다.
2. 저장 화면에서 각 작업을 열어 수정된 prompt가 실제 저장됐는지 확인한다.
3. 해당 작업 중 1개를 예약된 실제 실행으로 검증한다. 실행이 사용자 승인·권한 확인을 요구하면 승인되지 않은 상태로 ready 파일을 만들지 않는다.
4. 실제 실행에서 duplicate status, ready envelope, Worker receipt, DB import 및 평가 결과를 연결해 확인한다. 검증 실패 원고는 보류 유지한다.

커밋 및 원격 푸시: 후속 `git log`에 기록.
