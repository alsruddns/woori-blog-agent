# P5-CODEX-037 — 예약 Research Package 원고 전달 연결

## 작업 기록

- 작업 ID: `P5-CODEX-037`
- 작업 일시: 2026-10-29 15:51–16:00 KST
- 브랜치: `develop`
- 변경 사유: 로컬 프로젝트 예약 작업이 probe 메타데이터 파일을 쓸 수 있다는 결과가 확인되어, 기존 Research Package 입력과 예약 원고 Import 경로를 연결할 준비가 필요했다.
- 기존 상태: 예약 입력 폴더에는 원고 envelope가 없었다. 기존 예약 Import Worker는 `*.ready.json`을 원자적으로 선점하고 Import 후 결정론적 평가를 실행하지만, Research Worker heartbeat는 stale이고 Publication Worker는 stopped 상태였다.
- 변경 후: 기존 Fed Research Package를 해시 고정한 로컬 읽기 전용 snapshot으로 내보냈고, 해당 패키지 전용 Codex 예약 작업 지시문을 작성했다. 예약 task 자체는 이 실행 환경에서 조회·편집·실행할 수 없으므로 task 본문을 자동 변경하지 않았다. 기존 Import·평가 경로는 재사용한다.

## 확인한 운영 증거

- `.local/gpt-scheduled-import/probe/scheduled-test.json`: 268바이트, `2026-10-29T15:51:06.7973233+09:00` 실행 시각, task 이름 `woori-blog-agent scheduled import probe`. 파일 SHA-256은 `dbafc020c20ab8b97a22ca7a1d04bc6d17c2a197206a2943fcbd18a92a8651da`이다. 실행 결과 메타데이터일 뿐 원고 JSON은 아니다.
- 기존 Research Package `c0b6f2b2-7a74-4b3f-a4f1-f4219c12321d`: Fed statement URL에 연결된 fact span 11개, 공식 원천 출처 1개, `independent_source_count=0`, 상태 `evidence_collected_pending_human_review`, `generation_ready=false`, `human_review_required=true`, `publish_ready=false`.
- 이 패키지의 연결 원천은 `Federal Reserve Board press releases`로 기록되어 있고 source review는 원천의 공식성·출처 정보를 승인했지만, 그 검토 이벤트도 본문 주장의 의미 검토를 별도 사람 검토로 남긴다. 따라서 원고 작성 입력은 가능하되 자동 게시 근거로는 불충분하다.
- 읽기 전용 snapshot: `.local/gpt-scheduled-import/research/P5-CODEX-037-c0b6f2b2-7a74-4b3f-a4f1-f4219c12321d.research.json`, SHA-256 `0895eea3cca0832897652673fb016e03f2e54339931dc735f9e8ae89639b8595`. 원본 Research Package와 source metadata를 보존하며 발행 상태는 차단으로 표시한다. snapshot 생성 이벤트는 `scheduled_research_package.snapshot_exported`로 감사 기록에 추가했다.
- 기존 운영 DB 원고는 1건, 모두 `manual_codex_import`; 예약 생성 Import는 0건이다. 최신 FOMC 원고 버전은 7이며 마지막 기계 평가는 `machine_passed=true`지만 `independent_source_verification=false`, `generation_ready=false`, `publish_ready=false`, 사람 검토 상태 대기다. 기계 통과를 게시 승인으로 취급하지 않았다.
- 발행 후보 18건 중 `auto_eligible=0`, queue 0, 검토 필요 18, live 게시 0, 실제 live Publishing Job 0이다. 과거 mock job 한 건은 `quality_held`다.
- API 8100과 Dashboard 3100은 `scripts/status.ps1`에서 checkout 소유 listener로 확인했다. Research Worker heartbeat는 `running`이나 2026-10-29 15:18:45 KST 이후 갱신되지 않아 stale로 판정했다. Publication Worker heartbeat는 15:19:09 KST에 `stopped`이며 큐가 비어 있다. 프로세스는 재시작·종료하지 않았다.
- 실제 전역 모드는 `manual`, 일일 1건, 최소 간격 1440분, `operations_auto_approved=false`, `live_auto_enabled=false`, `real_writes_enabled=false`다. 변경하지 않았다.

## 연결 상태와 차단 사유

기존 `scheduled_import_inbox.process_inbox_once`는 `ready/*.ready.json`만 받고, envelope/schema 검증 → import API 멱등 제출 → scheduled-origin audit → 상태 조회 → 아직 평가가 없으면 자동 결정론적 assessment → `processed` 이동을 수행한다. import와 평가 결과는 항상 `publish_ready=false`이며 Blogger 쓰기를 호출하지 않는다. 새 예약 원고 파일은 아직 없어 이 운영 경로의 실제 처리 건수는 0이다.

기존 Publisher 후보 평가와 정책은 출처 접근·본문·사실·의미 일치·독립 검증·권리·언어·SEO·HTML·최신성·중복·블로그 매핑을 모두 요구한다. 현재 패키지와 최신 원고에는 사람의 의미·권리 검토와 독립 출처 확인이 남아 있어 `auto_eligible` 0건이다. Auto OFF 및 운영 승인 없는 Blogger 쓰기 차단을 유지했다.

예약 작업 설정을 관리하거나 수동 실행하는 도구 연결은 제공되지 않아, 현재 probe task의 지시문을 바꾸거나 다음 실행을 유발하지 않았다. 다음 예약 실행에서 패키지별 실제 JSON 파일이 `ready/`에 생성되고 Research Worker가 살아 있어야 실 Import·assessment 증거가 생긴다. 해당 예약 작업용 지시문은 `docs/operations/P5-CODEX-037-fed-package-task.md`에 작성했다.

## 변경 파일

- `docs/operations/P5-CODEX-037-fed-package-task.md`
- `docs/operations/P5-CODEX-024-gpt-work-prompts.md`
- `docs/operations/zero-cost-policy.md`
- `docs/development/P5-CODEX-037.md`
- 비추적 로컬 입력 snapshot: `.local/gpt-scheduled-import/research/P5-CODEX-037-c0b6f2b2-7a74-4b3f-a4f1-f4219c12321d.research.json`

## 검증

- `pytest services/api/tests/test_scheduled_import_inbox.py services/api/tests/test_content_imports.py services/api/tests/test_publication_modes.py services/api/tests/test_publications.py -q`: 47 passed. 격리 테스트 DB에서 기존 intake, assessment, auto eligibility, queue 안전 게이트를 검증했다.
- 운영 DB 원고·OAuth·발행 설정·job은 읽기 전용으로 조회했다. snapshot 내용은 DB에서 읽어 로컬 파일로 내보냈고, 이 작업의 시작/완료 및 snapshot 생성은 append-only 감사 이벤트로 기록했다. 원고·OAuth·발행 설정·job은 변경하지 않았다.
- `probe/` 파일은 보존했고 `ready/`는 비어 있다. 새 원고 Import 0건, `auto_eligible` 0건, 새 Publishing Job 0건, Blogger 실제 게시 0건.
- API/Dashboard/Worker 재시작, ChatGPT 예약 task 편집·수동 실행, Blogger API 쓰기는 수행하지 않았다.

## 커밋 및 남은 문제

- P5-CODEX-036 선행 커밋: `f384645b98bdf71004a686a05c3b7cfc0b642aa7` (`origin/develop` push 완료).
- P5-CODEX-037 커밋 SHA와 원격 push 상태는 이 기록의 후속 변경에서 연결한다.
- 남은 작업: 기존 ChatGPT/Codex 예약 task의 본문을 전용 지시문으로 업데이트하고 실제 예약 실행을 관측해야 한다. 예약 JSON Import 이후에도 의미·권리 검토와 독립 검증이 남으면 자동 게시하지 않는다. stale Research Worker를 소유 터미널에서 안전하게 재시작하고 heartbeat를 새로 확인해야 자동 Import가 운영 DB에 반영된다. Publication Worker와 Auto 정책은 현 상태 그대로 비활성이다.
