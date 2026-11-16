# P5-CODEX-138 — Codex 예약 원고 자동 작성 안정화 및 전체 예약 검증

## 작업 기록

- 작업 시작: 2026-11-05 07:14:55 KST, PostgreSQL `agent.work.started` ID `365032`
- 작업 종료: 최종 커밋 및 완료 감사 이벤트 참조
- 브랜치: `develop`
- 시작 HEAD / 시작 `origin/develop`: `d6e19aa1b80e2efd34b887c27004dcebfce39162`
- 시작 worktree: tracked 변경 없음. 기존 stash `P5-CODEX-099-101 interrupted implementation before startup repair 2026-11-01` 및 기존 미추적 파일·폴더를 보존했다.
- 변경 사유: 기존 Codex Desktop 예약 실행이 Resolver 이후 실제 duplicate preflight, 최신 조사, snapshot, 원고 handoff, Import/Receipt까지 연결되는지 확인되지 않았다.
- 운영 DB: schema 92, 설정 revision 23. 이전 참고 schema 90보다 운영 DB가 앞서 있다.
- P137 런타임 기준 코드: `170f17ee24638a5092af45a9ddc9e7ca3e9952af`; 이번 작업 전 네 서비스가 해당 revision을 적용 중이었다.
- 공식 Desktop Scheduled 목록은 `computer-use` skill 제한으로 직접 UI 열람하지 않았다. 아래 자동화 수와 실행 내역은 사용자 계정의 로컬 TOML 및 Desktop session DB에서 확인한 결과이며 공식 UI의 동기화 상태를 증명하지 않는다.

## 사전 운영 상태

- 현재 로컬 정의 21개: `ACTIVE` 20개, `PAUSED` 1개. 일시중지된 작업은 `automation-10` (China/zh-CN)이다. Automation ID, RRULE, 주제, 상태, 모델, prompt는 변경하지 않았다.
- API PID 27168, Dashboard PID 30216, Research Worker PID 26460, Publication Worker PID 37292. 네 서비스가 실행 중이며 API/Dashboard/Worker 상태는 정상, 두 Worker heartbeat는 fresh였다. 서비스 재기동은 하지 않았다.
- Publication Worker는 `AutoMode=auto`, `AutoPolicyActive=true`, 적용 revision `170f17e`를 보고했다. DB revision 23, `auto_mode=publish`, master/scheduled auto 및 운영 승인 ON, 글로벌 최소 간격 15분, 일일 LIVE 상한 100이었다.
- 활성 Blogger는 기존 6개 EN, KO, JA, DE, pt-BR, VI이다. zh-CN은 비활성/허용 범위 밖으로 유지된다.
- 현재 대기 중인 Research/Publication Job은 없었다. Publication Worker heartbeat는 직전 작업을 `global_minimum_interval_not_elapsed` 사유로 보류한 기록을 표시했으며 queued/due 수는 0이었다.
- 기존 발행 우선순위는 코드 SQL에서 `scheduled_auto → manual → trends_auto`로 확인했다. OAuth 연결, 게시 이력, 예약·수동 작업은 변경하지 않았다.

## 자동화별 최근 로컬 실행 관찰

아래는 로컬 Desktop session에 기록된 각 ID의 최근 결과 요약이다. 이는 공식 Desktop의 현재 등록 상태나 다음 실행 시각을 대체하지 않는다.

| Automation ID | 로컬 상태 | 최근 기록 및 결과 |
|---|---|---|
| `ai` | ACTIVE | 10/30 16:33 KST: 주간 원고/ready handoff 완료를 보고했으나 현재 운영 receipt로 연결되었는지는 확인되지 않음 |
| `automation` | ACTIVE | 11/04 18:31: 예약 resolver 확인, duplicate 조사 후 최신 web source 접근 불가; snapshot/원고 없음 |
| `automation-10` | PAUSED | 10/31: zh-CN 원고 기록은 일시중지 전 과거 이력; 재실행하지 않음 |
| `automation-11` | ACTIVE | 11/04 10:00: 정책 확인; 최신 자료 조사와 snapshot/원고 미완료 |
| `automation-12` | ACTIVE | 11/04 16:38: Run now가 manual 계약으로 분류됨; preflight/원고 미완료 |
| `automation-13` | ACTIVE | 11/04 16:04: scheduled/중복 확인 후 turn 실행 예산 종료; snapshot/원고 미완료 |
| `automation-14` | ACTIVE | 11/04 16:23: 16:20 slot보다 늦게 시작되어 slot gate가 조사/저장을 건너뜀 |
| `automation-15` | ACTIVE | 11/04 19:56: 20:00 slot 대기/시도 후 turn이 완료되지 않음; handoff 없음 |
| `automation-16` | ACTIVE | 11/04 20:21: scheduled/중복 확인 후 최신 조사/snapshot/ready 미완료 |
| `automation-2` | ACTIVE | 11/04 17:28: 17:30 slot 진입 전 resolver 단계에서 turn 종료 |
| `automation-3` | ACTIVE | 11/04 10:33: 10:30 slot보다 늦게 시작, invocation/slot 모호성으로 차단 |
| `automation-4` | ACTIVE | 11/02 16:29:49: 16:30 slot 작업 중 evidence 시각이 실행 이후라 `source_as_of_cannot_follow_scheduled_execution`; ready 미생성 |
| `automation-5` | ACTIVE | 10/31 12:04: duplicate preflight 연결 실패(`connection_refused`); 조사/원고 없음 |
| `automation-6` | ACTIVE | 11/05 07:00: resolver와 authoring policy 통과; duplicate check/handoff 미완료, 파일/이력 변경 없음 |
| `automation-7` | ACTIVE | 11/04 09:56경: snapshot/초안은 생성됐으나 마지막 duplicate 상태가 `unknown`, ready handoff 차단 |
| `automation-8` | ACTIVE | 11/04 20:17: Run now/manual로 분류, duplicate clear; 조사/원고 미완료 |
| `automation-9` | ACTIVE | 11/04 15:55: 16:00 slot 전 실행으로 resolver 대기; preflight/조사 미완료 |
| `fed-sec` | ACTIVE | 11/04 15:28: Run now/manual, duplicate clear; 조사/snapshot/ready 미완료 |
| `it-ai` | ACTIVE | 11/04 12:02: scheduled 정책 통과; duplicate/조사/산출물 미완료 |
| `k-beauty` | ACTIVE | 11/03: 현재 실행 시작 이벤트가 없거나 모호해 fail-closed 차단 |
| `k-pop` | ACTIVE | 11/04 15:28: Run now/manual, duplicate clear; manual handoff 혼선으로 조사/snapshot/ready 미완료 |

## 계약과 운영 데이터 추적

- 코드 경로 확인: `automation_invocation.py`는 최신 미완료 Desktop turn, `CODEX_THREAD_ID`, Automation ID, project cwd, 실제 trigger를 일치시킨다. `automation_cron_scheduled`와 `automation_cron_run_now`만 허용한다. 임의 개발 세션/과거 transcript는 예약 실행으로 승격되지 않는다.
- `automation_authoring_contract.py`는 scheduled trigger를 `chatgpt_scheduled_export`/scheduled envelope에, 공식 Run now trigger를 `manual_codex_import`/manual envelope에 각각 연결한다. Run now는 scheduled LIVE 권한을 상속하지 않는다.
- 두 경로 모두 generation duplicate preflight와 P131 exclusive `incoming → ready` handoff를 사용한다. 로컬 duplicate가 명확히 `not_found` 또는 `failed_only`이고 `draft_import_allowed=true`인 경우만 신규 원고를 허용한다. 동일 블로그 중복은 막고 허용 언어별 현지화 정책은 유지한다.
- 운영 DB의 예약 Import는 24건 모두 `awaiting_human_review`; 최신 수신은 2026-11-04 07:09:33 KST였다. 이는 revision 23 자동 발행 활성화(11/04 23:22 KST)보다 앞선다. 임의 READY 전환·재등록을 하지 않았다.
- `scheduled_auto` Publication Job은 DB에서 1건 확인됐으며 2026-10-30에 성공한 과거 건이다. 현재 신규 예약 Import 및 대기 예약 Publication Job은 0건이다. 따라서 신규 예약의 자동 queue 진입과 LIVE는 운영에서 검증할 입력이 없다.
- `.local/gpt-scheduled-import/ready/`는 비어 있고 `import_receipts/`도 비어 있다. 기존 `processed/` 파일과 DB의 24건은 P133 Receipt 적용 전 이력으로 확인되어 누락 복구/재처리하지 않았다. P133 코드상 새 Import는 API Import·origin audit·assessment 성공 후 immutable Receipt를 만들고, 실패 시 processed 이동을 막는다.
- P137의 Trends 경로는 별도 `.local/keyword-import` 경로이며, P137 기록상 신규 회차 LIVE 성공을 확인했다. 예약 Import와 이를 혼동하거나 Trends를 비활성화하지 않았다.
- 예약 Publication Worker는 `scheduled_publication_context(blog_id)`를 각 Blogger write entry point에서 사용하고, DB에서 승인된 Scheduled Auto policy event/blog scope와 현행 grant/revision을 다시 확인한다. P137 Trends 전용 `job_context` 변경을 예약 경로에 억지 적용할 이유는 발견되지 않았다.
- 공통 발행 간격, KST 일일 상한, queue priority, duplicate/idempotency, Blogger wire gate는 그대로 유지된다. 기존 24개 Import와 실패/폐기 상태는 변경하지 않았다.

## 원인 및 수정 판단

- 관찰된 중단은 대체로 실제 trigger/slot 불일치 또는 만료, duplicate preflight 연결 실패/`unknown`, source 접근 불가 및 snapshot/파일 미완료, Desktop turn의 제한된 실행 시간 종료였다. 완료되지 않은 단계를 완료 상태로 기록하지 않았다.
- Run now는 resolver와 Import contract에서 manual 경로로 지원되지만, 최근 Run now 기록은 Resolver/duplicate 이후 최신 조사 및 envelope 저장까지 끝나지 않았다. 실제 Desktop Run now를 눌러 재실행하지 않았다.
- 현재 재현 가능한 코드 결함은 확인하지 못했다. 기존 code path는 P122/P123/P131/P133의 보수적 identity/preflight/handoff/receipt 규칙과 일치한다. 테스트를 통과시키기 위해 gate를 약화하거나 historical turn을 복구하는 변경은 하지 않았다.
- 실제 실행 성공으로 오인될 수 있는 대시보드/로그/운영 상태 표시는 이번 범위에서 수정하지 않았다. 신규 artifact/receipt를 만들어내지 않았다.

## 테스트

- 예약/invocation/handoff/import/receipt/publication gate 집중 테스트: **177 passed** (`--basetemp .local/p5-codex-138-pytest-tmp`). 최초 동일 테스트의 assertions는 100% 통과했으나 pytest 종료 시 기존 Windows 임시 디렉터리 권한 오류가 있어 별도 격리 basetemp로 정상 재검증했다.
- 전체 API pytest: **921 passed** (`--basetemp .local/p5-codex-138-full-pytest-tmp`).
- Ruff 전체: 통과.
- `compileall` (`services/api/woori`, `scripts`): 통과.
- mypy 전체: 기존 오류 3개로 실패 — `grounding.py:169` lambda type inference, `topics.py:160` batch annotation, `worker.py:361` object→int overload. 이 파일은 수정하지 않았다.
- Dashboard ESLint: 통과. TypeScript typecheck: 통과. Next.js production build: 통과, `.next-p5-p138` 격리 output을 사용해 실행 중 Dashboard 산출물은 건드리지 않았다.
- 격리 pytest의 Blogger 실제 쓰기/테스트 초안: 0. 유료 AI/API 호출: 0. 운영 import/job/setting 변경: 0.

## 운영 반영 및 최종 상태

- 코드 변경 및 DB migration 없음. 운영 설정 revision 23 유지. 네 서비스 재기동 없음. OAuth, 게시 이력, 기존 예약 작업, 24개 Import, Trends 설정 유지.
- 실제 Codex Desktop 예약 또는 Run now를 통해 최신 web research → Snapshot → 원고 envelope → 운영 Import → Receipt → eligible publication queue까지 완료된 신규 사례는 아직 없다. 공식 Desktop UI 목록/next-run timezone도 확인하지 못했다.
- 운영 복구 완료 판정: **미완료 / 부분 검증**. 다음 실제 신규 Desktop slot에서 full handoff/receipt/queue를 관찰해야 하며, 현재 확인한 예약 실행은 상당수가 artifact 생성 전에 멈췄다. 과거 회차는 재실행하지 않았다.
- 수정 파일: `docs/development/P5-CODEX-138.md`만.
- 최종 Git 커밋/원격 push: 후속 Git 이력 및 completion audit event 참조.
- 남은 문제: 공식 Desktop automation registry 확인 불가, 다음 신규 reservation/Run now의 실제 E2E 미검증, 전체 mypy의 기존 3개 오류.

## 운영 관찰 후속 정정 (2026-11-05 07:18 KST)

- 작업 종료 상태 확인 직전 Publication Worker가 기존 `trends_auto` Job `7f0698a0-d882-455c-af25-03391e88f8dd`를 `succeeded/published`로 완료했다. EN Blogger (`b9dc1202-8071-484a-a4f4-15d04e34a76c`), LIVE `2026-11-05 07:18:13 KST`, remote post ID `5930199176225314875`; `remote_verified_at`은 07:18:12 KST다.
- 이는 이번 작업에서 만든 fixture, 테스트 Job 또는 테스트 게시가 아니며, 이미 활성화된 운영 Trends queue에서 처리된 실제 원고다. P138의 직접 Blogger 테스트 게시/초안 생성은 계속 0건이다. 따라서 최초 `agent.work.completed` payload의 `blogger_writes=0`은 P138이 시작한 테스트/변경으로 인한 쓰기만 가리키며, 전체 운영 시간대의 Blogger 쓰기 0건을 뜻하지 않는다. 이 구분은 후속 append-only 감사 이벤트에 기록했다.
- 이 운영 LIVE는 Trends 경로의 기존 동작을 추가 확인하지만 Codex 예약 원고 E2E를 검증하지는 않는다. 예약 queue/import 상태는 변경하지 않았다.
