# P5-CODEX-103 — 자동화 운영 통합 제어센터

작업 일시: 2026-11-02 KST. 기준 develop `094eadc18d234166e6a25d93dc4b0ba933011202`.

## 기존 상태와 변경 목적

P102의 정상 API28992, Dashboard27044, Research1948, Publication17652를 먼저 확인했다. Windows PostgreSQL16 PID6880 Auto/Running, Crypto 클러스터 무변경. 예약 작업은 이미 Ready/LastTaskResult0이었다. P099/101 API는 P102에서 활성화됐고 Dashboard는 과거 빌드였다. 기존 stash `c879d3dfe08a87baae278944ba6c0caf9426847a`와 미추적 Playwright 폴더 두 개를 유지한다.

기존 `trend_collection_settings.enabled`와 `publication_mode_settings.emergency_stopped/blogger_api_restricted`를 재사용한다. 기존 P097 발행 차단을 무조건 해제하지 않고 새 설정 시점의 epoch/grant로 실제 실행 권한을 제한한다. 기존37개 Job은 데이터와 상태를 보존하고 새 권한을 부여하지 않는다. 운영 시작 감사281424. 사용자는 최종 Trends/자동 원고/수동 발행 ON, 자동 발행 OFF, 긴급 정지 OFF 및 계정 제한 해제 신고 적용을 명시적으로 승인했다. 실제 게시 테스트는 승인하지 않았으므로 실행하지 않는다.

## 구현

- Migration077: `automation_controls`(단일 행, revision, 독립 세 설정, 자동 Draft/LIVE·대상·epoch, 수동 epoch, 계정 신고/읽기 결과), immutable `automation_publication_grants`, runtime `automation_runtime_ack`. 기존 수집·긴급 정지 값을 중복 저장하지 않는다. `migrate.py`/격리 DB provision을77로 확장했다.
- `automation_controls.py`: 인증된 GET/PUT/읽기 검사 API. 엄격한 boolean, revision 경합, 변경자·사유·전후 값 감사, 대상 Blogger 확인, 자동 ON 확인, LIVE 별도 확인, 긴급 정지 해제 확인을 검사한다. 정책 캐시 없음. Worker의 실제 PID/revision/45초 freshness ACK를 설정 저장과 구분한다.
- `publication_operation.py`, `blogger_writes.py`, `external_policy.py`: 실제 HTTP 직전에 현재 설정·epoch·정확한 원고/승인·대상을 재검사한다. 제어 설정 변경과 wire admission은 동일한 PostgreSQL advisory lock으로 직렬화하며 HTTP가 끝나기 전에 OFF 저장 성공을 반환하지 않는다. DB 장애는 fail-closed. 기존 비용·권한·허용 경로·OAuth·간격/일일 제한을 우회하지 않는다. 403 제한은 기존처럼 제한+긴급 정지와 감사에 기록한다.
- `automation_auto.py`: 기존 예약/Trends legacy queue를 재개하지 않는 별도 새-epoch 경로. 활성화 이후 생성된 최신 원고 버전 중 기존 기계/출처/권리/사람 검토/게시 조건을 통과한 버전만 등록한다. 과거 원고의 publish_ready나 claim 상태를 변경하지 않는다. 중복 원격 확인 불가 시 쓰기/재시도 보류. Draft와 LIVE를 구분하고 실제 readback/receipt를 저장한다. Mock으로 두 모드 성공과 중복 불명확 시0쓰기를 확인했다. 자동 설정 OFF는 수동 경로에 영향을 주지 않는다.
- `publications.py`/`publication_worker.py`/`publication_read_state.py`/`operations_dashboard.py`: 새 관리자 exact-version 수동 요청에만 현재 epoch grant를 붙이고 Worker가 검사한다. 예전 Job은 긴급 정지 해제로 재개되지 않는다. 새 자동 dispatcher는 수동 설정 OFF와 독립이다. 기존 legacy 발행 진입은 계속 fail-closed다.
- Trends/주제/작성 경로: `trends.py`, `topics.py`, `trend_editorial.py`, `editorial_intelligence.py`, `keyword_jobs.py`에서 신규 수집/후보/자동 CLI 시작 전 정책을 읽는다. OFF 기간 backlog를 무조건 복구하지 않고 기존 최신-slot 규칙을 유지한다. 자동 작성 OFF 시 자동 대기 Job이 수동 키워드 Job을 막지 않도록 허용 lane으로 조회한다. 기존 원고 조회/편집/품질/Import는 계속 허용한다.
- Desktop: 고정 `automation-policy-check.py`가 인증된 API 또는 같은 repository 정책을 조회한다. UI 생존과 무관하며 인증 거절은 우회하지 않는다. `resolve-codex-automation-run.py`는 실제 scheduled trigger만 정책 검사하고 불가 시 `policy_waiting`을 로컬 보존한다. core resolver와 P102 기존 원고 복구는 별도이므로 OFF 중에도 저장된 원고 Import가 가능하다. 기존15개 prompt에 공통 정책 참조만 추가했고 prompt 외 모든 TOML 값/ID/RRULE/모델/target/cwd/Local 설정은 전후 동등 확인, 원본과 SHA manifest는 `.local/p103-automation-contract-backup`에 보존했다.
- Dashboard `/operations/automation`: 독립 스위치4개+긴급 정지, Draft/LIVE·대상 확인, 계정 제한 신고와 읽기 전용 확인, Worker 적용/저장 구분, 오류/변경 이력, PC2열/모바일1열. 동일 출처 authenticated proxy만 허용. 원고 상세 수동 버튼은 중앙 정책을 확인하며 backend도 강제한다. 고정 ON/OFF 안내 문구를 실제 조회 기반 안내로 바꿨다. 기존 다크/라이트 테마와 복사/편집/다운로드를 보존했다.

## 장시간 Worker 작업의 안전한 반영

Research1948이 과거168시간 cross-geo grouping proposal을 단일 DB 트랜잭션에서 수십 분 계산하고 있어 기존의 cycle 종료 stop 요청만으로 신속한 정상 교체가 어렵다. 원본 수집은 다른 트랜잭션에서 이미 저장돼 있다. Codex 실행/Import 중인지, 해당 OS PID의 PostgreSQL client_port/backend_start/동일 app DB/역할/정확한 파생 INSERT인지 확인한 뒤, 원본이 아닌 **이 파생-only 트랜잭션의 현재 statement만** 취소해 rollback-safe 경계에서 기존 cooperative stop을 완료하는 방식을 사용한다. 다른 backend·DB·프로세스·Crypto는 대상으로 삼지 않는다. `pg_terminate_backend`/process force kill/Task Stop은 사용하지 않는다. 안전 조건이 불충족하면 그대로 두고 미반영을 보고한다.

새 worker에는 그룹화 stop/OFF 체크포인트를 추가했고 취소 시 파생 트랜잭션이 rollback된다. 기존 grouping 알고리즘·168시간 범위·이력은 바꾸지 않는다. Import polling은 같은 Worker의 독립 thread와 기존 advisory intake lock으로 분리했다. 장시간 grouping이 예약 원고 수신을 막지 않으며 Codex concurrency는 여전히1이다. 종료 시 진행 중 intake를 기다린다. 실제 poll의 ACK도 저장한다.

## DB 및 검증

최초 백업 `backups/20261101T162900Z.dump`(32,410,656 bytes), Migration 직전 백업 `backups/20261101T165832Z.dump`(33,012,827 bytes), pg_restore catalog 검증. 운영/격리 DB schema77 확인. 새 migration은 기존 원고/Job/게시/감사 기록과 정책을 삭제하지 않으며 자동 발행 기본 OFF, 수동 ON, 작성 ON을 seed한다. 실제 사용자 요청의 긴급 정지/제한 변경은 최종 검증 이후 별도 감사로 적용한다.

검증: 변경 범위 통합225건 통과 후 추가 수동 작성 starvation 회귀1건 통과. Worker/topic 추가27건 통과로 고유 성공253건(P103 신규17 포함). 별도의 gate 재검증65건은 중복으로 더하지 않는다. 1440/390 Chromium8건, TypeScript/ESLint, Python Ruff/mypy, 격리 Production Build `.next-p5-p103-final` 통과. Next가 자동 수정한 baseline `next-env.d.ts`/tsconfig만 원본 복원한다. 테스트용 임시13100 서버만 종료한다.

확장 검증에서 과거 P096/P097 정책과 충돌하는 legacy 발행 테스트8건이 실패했다. **수정 전094eadc 소스를 별도 읽기용 archive로 실행해 동일8건 실패를 재현**했다(기존 publications5 + P0963). 새 implicit publication을 허용하도록 정책을 약화하거나 이 실패를 통과로 표시하지 않는다. 새 explicit control/epoch 경로는 별도 Mock/DB 회귀로 검증했다. 전체 repository suite 통과를 주장하지 않는다.

초기 TypeScript 명령을 repo root에서 실행해 npx가 기존 로컬 compiler 대신 폐기된 tsc2.0.4를 npm cache에 받아 도움말만 출력한 실수가 있었다. 프로젝트 dependency/lockfile/서비스에는 변경이 없으며 이후 Dashboard의 설치된 `node_modules/typescript/bin/tsc`와 eslint만 직접 사용해 통과했다. 유료 API/AI fallback은 호출하지 않았다.

Google 접근: 기존 승인된 제한/비용 gate를 통해 활성 Blogger4개의 읽기 확인이 모두 성공했다(`.local/p103-google-read-check.json`, 2026-11-02 01:59 KST). 이는 GET/정상 OAuth 경로 확인일 뿐 실제 API 쓰기는 미검증이다. 테스트 게시물·Draft·LIVE·Update는 만들지 않았다.

## 최종 적용 체크포인트

코드 커밋, 실제 PID/설정 적용, Worker ACK, 자동 쓰기0, 기존37 Job 보존, 원격 push 및 남은 제한은 후속 기록에 추가한다. 자기 참조 커밋은 `git log --grep=P5-CODEX-103`로 연결한다. main 병합 없음.
