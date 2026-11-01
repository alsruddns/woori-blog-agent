# P5-CODEX-102 — 예약 원고 장애 분리 및 복구

작업 일시: 2026-11-02 KST. 기준 develop `ff738dafd295597997c3001ddc02097e4815096a`.

## 문제와 보호 범위

automation-5의 실제 2026-10-31 12:00 KST 실행은 Dashboard proxy 연결 거절 3회 후 조사/작성 전에 중단됐다. 원래 세션 `01a18fea-2ffa-7c73-8847-279b022f3e0c`, occurrence `codex-slot:automation-5:20261031T1200KST`와 설정 RRULE을 확인했다. 이 ID는 프로젝트 파생 키이며 scheduler 발급 ID가 아니다. 실패 이력은 수정하지 않는다.

시작 Git은 develop, 기존 미추적 Playwright 산출물 두 폴더만 있었다. P099/101 stash `c879d3dfe08a87baae278944ba6c0caf9426847a`는 그대로 보존한다. 기존 시작 스크립트/잠금/PID 보호를 수정하지 않는다. PostgreSQL16 Running/Auto PID6880 및 Crypto 클러스터는 건드리지 않는다. publication manual_only, API 제한, 긴급 정지, Auto disabled와 기존 Publishing Job은 유지한다.

## 구현 및 변경 목적

- `scripts/scheduled_duplicate_check.py`: 기존 프록시 우선, generation의 전송 장애/5xx에만 고정 broker fallback. 인증/권한/422 거절과 publication은 우회하지 않는다. 원래 실패 진단을 dashboard_failure로 보존한다.
- `scheduled_preflight.py`, `scripts/scheduled-preflight-broker.py`: 인증된 loopback API -> 기존과 동일한 repository 중복 함수 -> 보존 파일의 존재 확인. 모델 프롬프트에 인증정보를 전달하지 않는다. DB/index 불완전 상태에서 not_found를 만들지 않는다. index는 존재 증거만 제공한다. 모든 경로 실패 시 조사/로컬 보관만 허용하고 Import는 pending이다.
- `scheduled_pending.py`, `scripts/save-pending-manuscript.py`: 검증된 원고를 incoming에서 읽어 별도 pending에 hash/실행 모드/Automation/정확한 슬롯/파생 키/주제/대상/작성 시각과 함께 원자적 exclusive 저장. 동일 실행/blog/언어의 다른 payload는 충돌. 기존 파일과 byte-identical 원고를 보존한다. 모델 호출, DB 연결, Import는 이 저장 명령에서 실행하지 않는다.
- `content_imports.py`: 기존 중복 검사·Import writer·scheduled origin writer에 기존 트랜잭션 재사용을 추가했다. 보류 원고 복구는 인증된 API에서 occurrence/event 잠금, 기존 Import/사건/제목/ID 중복, 실제 저장 RRULE, 형식, 안전 HTML, 작성/자료 기준 시각을 재검사한다. 24시간은 보수적인 초기 자동 복구 한도이며 성능 최적값이 아니다. 오래된/미래 시각/위험 HTML은 review_required, 불명확한 중복은 import_pending. Import/native Content Version/provenance/복구 감사는 동일 트랜잭션에서 commit하며 실패하면 전체 rollback한다. 원래 unknown 사전 검사 메타데이터는 덮어쓰지 않고 복구 결과를 별도로 감사한다.
- `scheduled_import_inbox.py`, `main.py`: 기존 Research Worker의 60초 intake에서 보류 원고·progress outbox를 처리한다. API가 없으면 pending 유지. ready에 잘못 놓인 unknown 원고도 API Import 전에 pending으로 격리한다. 회차당 원고 처리 상한4를 유지한다. 기존 파일+별도 immutable receipt로 Import/Content Version을 연결한다. 새 auth recovery/progress 경로는 Blogger·발행 Job에 연결하지 않는다.
- `scripts/scheduled-progress.py`: 실제 Desktop 세션 resolver로 확인한 scheduled/manual 실행의 진행 상태를 로컬 append-only 기록하고 복구 후 DB 감사에 멱등 동기화. usage_limit_waiting을 별도 기록한다. 원고가 이미 저장된 이후 실패는 writing failed가 아닌 import_pending. 진행 상태는 self-reported이며 조사 완료·사실 확인·승인 증거가 아니다.
- `AGENTS.md`, `docs/operations/scheduled-outage-recovery.md`: 기존 장애 시 즉시 중단 지침을 위의 좁은 save-only 예외로 대체한다. Blogger 자동 Draft/Publish/Update와 Auto/긴급 정지 변경은 계속 금지한다.
- `scripts/update-scheduled-outage-contract.py`: 기본 dry-run. 기존 15개 실제 ACTIVE/cron 프로젝트 설정만 대상으로 원래 prompt를 보존하고 공통 계약 참조를 추가한다. 설정 원본과 전후 SHA는 `.local/p102-automation-contract-backup`에 보관했다. 15개 모두 prompt 외 전체 TOML 값(ID/RRULE/언어 지침/모델/대상/Local/project 등)이 그대로임을 확인했다. 새 작업 등록/예약 변경/실제 15회 실행 성공을 주장하지 않는다.

## DB 및 감사

운영 변경 전 `backups/20261101T154054Z.dump` 31,543,310 bytes 백업, pg_restore catalog 검증. 신규 migration은 필요 없다. 기존 append-only audit와 Import/Version 구조를 재사용한다. 시작 감사278498, 실제 대체 조회 및 15개 계약 변경 확인 감사278872. 원고/Version/과거 실패 이력 삭제·수정 없음.

## 운영 조사와 재현

원래 실패 세션의 정확한 event key `weekly-global-finance-2026-10-31`, EN/US, Blogger `5240203250707821039`, 원래 주제로 조회했다. 해당 사건 Import와 해당 occurrence 원고 파일은 없었다. 정상 프록시 결과와 **프록시 connection_refused만 주입하고 실제 API에 연결한 결과**, **API503만 주입하고 실제 repository에 연결한 결과** 모두 local_status=not_found/draft_import_allowed=true로 일치했다. overall unknown/remote not_checked는 그대로이며 Blogger는 조회하지 않았다. 정상 서비스를 실제로 꺼서 장애를 만들지 않았다.

이는 조회 장애 수정의 운영 증거이며 과거 슬롯의 재실행 성공이 아니다. 현재 개발 세션을 Desktop cron/Run now로 위장하지 않았다. 과거 실패 슬롯에 새 원고·scheduled envelope·Import ID를 만들지 않았다. 재실행은 실제 지원되는 invocation의 출처와 시점 구분이 필요하다. 실제 재실행 원고/Import가 없음을 최종 보고에 명시한다.

## 검증 체크포인트

격리 test DB, 강제 rollback 공유 트랜잭션으로 검증. 기존 예약/Import/occurrence/수동 실행/Trends/키워드/P099 품질/자동 발행 차단을 포함한 통합 suite **151 passed**. 이후 추가한 ready-unknown/사건 중복 회귀 테스트는 최종 체크포인트에 기록한다. 변경 모듈 mypy 통과, 변경 범위 Ruff 확인. Dashboard 코드를 변경하지 않아 기존 Dashboard build를 재실행하지 않는다. 운영 프록시/API HTTP와 Worker heartbeat는 최종 반영 후 확인한다.

커밋/푸시, 관련 서비스의 안전 반영 여부, 마지막 테스트 수와 남은 항목은 다음 체크포인트와 `git log --grep=P5-CODEX-102`로 연결한다. main 병합 없음.

### 코드 검증 완료 체크포인트

최종 변경 범위 통합 **153 passed (10.85초)**. 신규 P102 회귀16건 포함. Ruff 전부 통과, API/main/Import/보류 복구/broker mypy 확인. 서비스 중지 없이 실제 원래 식별자의 프록시/직접 API/repository 결과 일치를 확인했다. 정상 API의 graceful stop dry-run이 일반 established 소켓 하나를 감지했다. 추가 조사에서 8100 클라이언트 연결은 없고 API PID3596 내부 asyncio 자기 소켓쌍(64575↔64576)만 확인했다. force나 작업 취소는 하지 않는다. 반영 시 해당 listener의 정확한 checkout/PID/Windows owner/instance identity와 활성8100 연결을 재검증하고 기존 identity-bound stop-file 채널만 사용한다. Research Worker도 기존 cooperative stop으로 현재 동기 작업을 마친 후에만 교체한다. Dashboard/Publication Worker/DB/Crypto는 교체하지 않는다.

### 실제 실행 출처 재검사 보강

설정된 RRULE 슬롯만으로 실제 예약 실행을 입증할 수 없으므로, 저장 CLI가 현재 Desktop 세션 resolver 결과를 함께 보존하도록 추가했다. 복구 API는 그 session_id의 실제 세션 파일을 다시 읽고 scheduled/manual trigger·occurrence/manual_run_id 일치를 검사한다. 기존 실패 슬롯의 세션을 현재 작성한 scheduled 원고에 붙이는 재라벨링도 막는다(실제 시작 후 6시간 이내의 실행 시각만 수용). 출처가 없는 레거시 pending은 삭제하지 않고 actual_invocation_unverified 검토 보류다. 개발 세션은 예약/Run now를 사칭할 수 없다. 관련 회귀2건 추가 후 신규 P10218건 통과. 이 보강으로 API와 Research Worker는 검증된 최종 코드에 대해 동일한 cooperative 교체를 한 번 더 수행하며 강제 종료하지 않는다.

### 순차 반영 및 호환성 체크포인트

- 핵심 코드 `28d8eff`, 실행 출처 재검사 `8a8e638`. 통합 **155 passed (10.71초)**. 이후 순차 업그레이드 호환성 회귀1건을 추가해 P102 **19 passed** 및 Ruff/mypy 통과했다. 신규 고유 회귀는 모두19건이며 앞서 검증한 기존 테스트137건과 합쳐156건이다.
- 최초 정상 교체: API3596→5680(launcher8612), Research19264→1948. HTTP200/heartbeat 정상. 기존 startup coordinator2912는 API의 정상 종료 후 자연 완료되어 예약 작업은 Ready/LastTaskResult0이 됐다. 작업 취소/force/Task Stop은 실행하지 않았다. Dashboard27044/Publication17652/PostgreSQL6880 유지.
- 출처 재검사 보강 후 Worker1948의 추가 cooperative 종료를 요청했으나45초 안에 완료되지 않았다. 실제 Codex 작업은 없었고 기존 `topics.build_candidates`의168시간 cross-geo proposal 동기 일괄 처리 중임을 읽기 전용으로 확인했다. heartbeat는 계속 fresh다. 원고/수집 처리를 끊거나 DB backend를 취소하지 않는다. 이 실행이 나중에 예고 없이 종료되지 않도록 **이번 작업이 만든 정확한 stop request만 회수**하고 Worker를 유지한다.
- 그래서 API가 구 intake 요청에도 대응하도록 보강했다. request에 session evidence가 없으면 임의 경로 대신 정확한 key/hash/raw bytes가 일치하는 프로젝트 pending 파일에서 evidence를 읽고 실제 Desktop trigger를 똑같이 재검사한다. 이 호환 경로는 격리 DB에서 실제 Import/native Version까지 회귀 검증했다. API만 추가 cooperative 교체하면 이미 반영된 Worker28d8eff도 새 pending 파일을 안전하게 복구할 수 있다. Worker 최종 source marker 반영은 다음 정상 시작으로 남긴다.
- 관찰된 별도 한계: 기존 주제 일괄 처리 중에는 동일 Worker의 intake tick이 지연될 수 있다. 60초는 poll 설정이지 모든 부하에서60초 이내 처리를 보장하는 SLA가 아니다. 이번 작업에서 이 과거 전체 그룹화 알고리즘이나 수집 정책은 변경하지 않았다.

### 최종 운영 확인 — 2026-11-02 01:06 KST

- 최종 코드 `30d91a2`가 API28992(launcher17768)에 반영됐다. Research1948은 최초 P102 반영 코드28d8eff로 정상 실행 중이며, 새로운 API의 정확한 pending 파일 기반 호환 경로로 실제 실행 출처 검사를 받는다. 이번 작업의 stop-request는 identity/timestamp를 확인하고 회수했으며 남아 있지 않다. 다음 정상 시작용 validated source는30d91a2/build `.next-p5-p099-final`, 이전 marker 사본 보존. 현재 API/Worker applied_commit은 각각의 실제 반영 버전을 그대로 기록했다.
- API `/health`, Dashboard `/sources`와 `/manuscripts` 모두 HTTP200. 새 recovery API는 미인증401/잘못된 입력422로 인증·요청 차단을 확인했다. 기존 P099 API도200이다. Dashboard 코드는 변경·재시작하지 않았으며 신규 UI 배포를 주장하지 않는다.
- 최종 감사279408: Research/Publication heartbeat fresh, 오류 없음. Trends ON/10분/11지역. manual_only/API 제한/긴급 정지 유지. 시작 감사278498 이후 Blogger provider 호출0, publication event0, publication dispatch attempt0. 새 자동 발행/기존 대기 Job 재개 증거 없음. API/수집·원고 설정과 15개 예약은 활성 상태로 유지했다.
- 감사279076의 `publishing_jobs_created=0`은 일부 명명된 queue audit event 개수였으며 전체 job 생성 수의 직접 측정으로 해석하면 안 된다. 이 metric의 한계를279408 정정 이벤트에 남겼고, 실제 dispatch ledger와 전체 publication event inventory로 검증했다. 초기 최종 확인용 SELECT의 없는 created_at 컬럼 오류는 읽기 전용 트랜잭션이 rollback됐고 서비스/데이터를 수정하지 않았다.
- Task Scheduler WooriBlogAgent-Worker Ready / LastTaskResult0. coordinator가 자연 종료한 결과다. Task 취소·비활성화 없음. PostgreSQL16 Auto/Running PID6880, Crypto 변경 없음. Dashboard27044/Publication17652 유지.
- 정상 운영 원고를 테스트 목적으로 만들지 않았다. 해당 과거 occurrence의 원고·Import는 없으며, 이 개발 실행은 유효한 Desktop 예약 재실행/Run now가 아니므로 새 scheduled 원고나 Import ID를 보고하지 않는다. pending 원고도 현재0건이다. 이번 작업 중 관찰한 새 일반 Import는0건으로, 실제 15개 예약의 다음 실행 및 복구 후 Import 실적은 아직 관찰되지 않았다.
- 검증 합계: 기존 통합155건 통과 후 호환성 회귀1건 추가 검증, 고유156건(P10219 + 기존137). 실패를 성공 처리하지 않았다. 마지막 P102 suite19/19, Ruff/mypy 통과. 기존 startup 스크립트/동시 실행 잠금/종료 코드/PID 보호 무변경. 배포용 migration 없음.
- 남은 관찰: 다음 실제15개 예약 실행/Import receipt, 이전 failed occurrence의 별도 유효한 수동 복구, 장시간 Trends 일괄 처리 중 intake 지연. Worker 최종 source 자체의 재시작 반영은 다음 정상 시작에 수행하며 현재 정상 처리 작업을 중단하지 않는다. publication 권한과 유료 API는 활성화하지 않았다.

최종 Git 커밋은 이 문서 전용 후속 기록 및 원격 HEAD로 연결한다. develop push 이후 원격 SHA 일치를 확인한다. P099/101 stash 및 원래 미추적 Playwright 산출물 두 폴더는 보존한다.
