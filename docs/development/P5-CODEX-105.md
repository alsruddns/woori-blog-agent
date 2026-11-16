# P5-CODEX-105 — Trends 수집 정체 및 연구 파이프라인 안정화

작업일: 2026-11-02 KST. develop 기준 `58b95fc`. 최종 커밋은 후속 기록 / `git log --grep=P5-CODEX-105`로 연결한다.

## 확인된 장애

- P104 관찰에서 마지막 성공은02:10이었다. 이번09:30 조회에서는07:20에11개 지역이 한 번 재개됐고 이후 다시 정체했다. 일시적 재개를 지속적인10분 정상 수집으로 해석하지 않는다.
- Research PID10232, PostgreSQL16 Running/Auto PID6880, Publication32104 모두 heartbeat가 갱신됐다. Task Scheduler WooriBlogAgent-Worker Ready/LastTaskResult0. Dashboard/API 정상, stash c879d3d 및 기존 정상 서비스 유지.
- Worker의 운영 루프가 `schedule_tick → reconcile → build_candidates(168h) → cross_geo_pairs → research triage → queue/dispatch → 기타 연구/Import/CLI admission`으로 직렬 실행됐다. 기존 독립 scheduled intake/heartbeat만 계속 동작했다.
- 실제 Research의 client port51738 → PostgreSQL backend24540, 09:30 기준 약2시간7분짜리 파생 비교 트랜잭션. `idle in transaction / ClientRead`, blocking_pids=[]로 DB lock 대기 증거는 없었다. 네이티브 Job이 없는 레거시 파생 단계라 Job UUID를 조작하지 않고 backend PID/회차로 식별했다. 첫02:10 트랜잭션은07:20 전에 끝난 것으로 관찰되며 정확한 완료 시각은 이번 조회만으로 확정하지 않는다.
- 168시간 관찰25,190개를 매 주기 관찰 단위 중첩 비교했다. 같은 쿼리 비교 결과를 캐시해도 모든 관찰 쌍 반복과 매칭별 INSERT는 반복됐다. 1,000쌍마다 설정 확인 DB 연결도 반복했다. 확인된 원인은 이 전체 비교를 수집 스케줄러와 같은 루프에서 실행한 구조 및 반복 비용이다. Codex 대기/사용량 제한/네트워크/스케줄러 중복/마이그레이션 자체가 당시 수집을 막았다는 증거는 없었다. 상세 비밀 없는 조회는 ignored `.local/p105-inspection.json`에 보존했다.

## 변경 구조

- 동일 Research 프로세스 안에 독립 non-daemon 실행 단위를 둔다: Trends collector, 최신 회차 topic evaluator, Codex admission, Codex Import. 기존 scheduled inbox polling도 독립 유지한다. 각 단계는 별도 연결·잠금·실패 경계로 실행되며 다른 단계 종료를 기다려 수집을 시작하지 않는다. 기존 Worker 프로세스 중복 방지와 Codex single-run 잠금은 유지한다.
- 수집은 기존11지역/10분/무료 RSS/allowlist/1MiB/백오프를 그대로 사용한다. 원본 저장과 회차 결과 완료는 평가·작성보다 먼저 끝난다. 지역별 진행 체크포인트를 별도 트랜잭션에 저장한다. 실패한 일시적 네트워크/5xx 지역만60초 후1회 재시도한다. 성공 지역 및 동일 회차는 반복하지 않는다. 403/429/정책·유료 신호는 재시도하지 않는다. 누락 회차는 감사에 기록하고 과거를 일괄 재수집하지 않는다.
- 기존15초 read timeout에30초 지역별 wall budget을 더했다. 64KiB를 채울 때까지 기다리지 않고 수신 chunk마다 시간을 확인하므로 천천히 들어오는 응답이 read timeout을 반복 갱신하는 상황도 제한한다. HTTP 연결은 정상 close하고 프로세스를 강제 종료하지 않는다. 지역 사이 정상 종료 체크포인트를 제공한다.
- 운영 평가 경로는 기존 P101 `reconcile → assess_current → queue_selected → expire/dispatch`를 재사용한다. 현재 회차 최대 `len(ALLOWED_GEOS)*MAX_ITEMS` (=220개)만 정규화·분류한다. 과거 전체 비교는 운영 스케줄러에서 제거하고 진단/기존 API는 보존한다. 최신 회차가 바뀌면 이전 미완료 평가는 superseded로 남고 과거 미시작 작성 Job을 되살리지 않는다.
- 같은 후보·블로그·엔진·immutable 평가 설정 ID의 점수는 재사용한다. 회차에 성공 지역이 추가되면 수집 fingerprint가 달라져 새 평가 작업이 생기지만 이미 평가한 후보는 캐시를 사용한다. cache bulk lookup과 bounded pure normalization LRU로 반복 조회/정규화를 줄였다. 기존 평가 점수·중복·권리·검증 정책은 바꾸지 않는다.
- 레거시 과거 비교 자체도 normalized query group 단위로 비교하고, 관찰 쌍은1,024개씩 executemany로 저장한다. 원래 관찰 쌍·유사도 문턱·same-event 미확인 의미는 그대로 보존한다. 이 무거운 역사 materialization은 더 이상 live10분 루프의 선행 조건이 아니다.
- Migration079 `research_stage_runs`: 실제 UUID, scope, stage, engine, settings_id, owner PID, attempt, 시작/진전/완료, 체크포인트, 처리/남음, 실측 ms, 오류, 결과. 단계/회차별 session advisory lock이 살아 있으면 오래됐어도 빼앗지 않는다. lock이 해제된 이전 running만 같은 UUID로 복구한다. 완료 단계는 캐시, 평가 체크포인트의 분류/점수 완료 부분은 재실행하지 않는다. 실패 재시도는60초 간격, 최대3회/작업이며 다음 정상 회차와 분리한다. 모든 시작/완료/복구·누락은 감사에 남긴다.
- 단계별 DB 연결 timeout5초/lock wait2초/statement15초는 context-local이다. 전역 PostgreSQL 설정이나 Codex 모델 실행 timeout을 바꾸지 않는다. 정상 소유자 SQL을 취소하지 않고 대기 중인 자기 쿼리만 실패 처리한다. 지역 수집/평가/Import별 진전 지연은 의심 신호이며 자동 강제 종료 사유가 아니다. Codex는 기존 Job/CLI timeout/사용량 로컬 백오프로 구분한다.
- 기존 P102 Backend 직접/지원 repository 중복 확인, pending 파일·멱등 Import·원본 보존·실제 occurrence 검증, P099 정적/심층 분리·캐시·사용자 승인 Version 수정, P104 발행 제어는 그대로 재사용한다. Deep 평가 또는 Import 지연은 수집 실행 단위를 막지 않는다. 예약15개 설정/시간/RRULE/프롬프트를 수정하지 않는다.

## Dashboard

기존 `/operations/research`에 단계별 모니터를 추가한다. 같은 출처 proxy의 authenticated GET `/admin/research/editorial-intelligence/pipeline`을 사용한다. 수집 최신 시도/성공·지연·회차별 성공 수, 평가 진행/완료/실측 평균, Codex 상태/로컬 사용량 대기, Import/품질 상태 및 Job 체크포인트를 분리한다. 최근100개 단계 이력의 단계/상태/회차·UUID 검색을 제공한다. 모르는 남은 수와 수행하지 않은 평가 시간은 만들지 않는다. heartbeat 정상만으로 데이터 최신성을 정상 처리하지 않는다. 다크 테마와1440/390 반응형 유지.

## DB·운영 보호

- 백업: `backups/20261102T003008Z.dump`, archive catalog 검증. checksum과 기존37 Publishing Job/15 automation.toml checksum/원장/7설정 snapshot은 ignored `.local/p105-before.json`에 보존. 시작 감사283041.
- additive079: stage run 테이블/회차 인덱스 및 점수 캐시 UNIQUE에 settings_id 추가. 기존 row/Version/Job/audit 삭제 없음. 기존 Migration076~078 수정 없음. 테스트 DB schema79 provision 및 운영 DB CONNECT 차단 확인.
- 최종 정책 유지: collection=true, auto_manuscript=true, global_auto=false, trends_auto=false, scheduled_auto=false, manual=true, emergency=false. Google API 제한 상태 및 P104 revision을 바꾸지 않는다. 실제 Blogger 쓰기/테스트 게시물 금지.
- 정상 프로세스는 불필요하게 중단하지 않는다. 정체 Research는 소유자/PID/실행 관계 및 실제 Codex 작업 없음을 재검사한 후 기존 stop-file 정상 종료를 요청한다. 파생 비교 체크포인트의 트랜잭션 rollback은 원본 수집·기존 커밋 이력을 지우지 않는다. 종료 확인 전 새 Worker를 시작하지 않는다. 강제 kill/DB backend termination/스케줄러 stop/PG16·Crypto 재시작 금지.

## 검증 체크포인트

- 첫 관련 통합189 passed. 추가 lock deadline/느린 stream 회귀를 포함한 stage12개 통과. 최종 고유 합계는 아래 후속 결과에 기록한다.
- 격리 실제 DB: 단계 캐시/복구·active lock 비탈취·부분 지역1회 재시도·평가 블로킹 동안2회 수집·동일 회차 중복 금지·설정 OFF·동일 엔진/다른 설정 캐시·DB timeout local 범위·2초 Lock 대기 제한·30초 wall budget 가상 stream 중단·원본 관찰 미저장 검증.
- Mock Playwright8 passed:1440/390 다크 테마, 지연·quota·Import/품질 구분, stage/status/search, 빈 상태,503 오류, 가로 넘침/pageerror0. 초기 label locator를 실제 combobox accessible name으로 수정했고 제품 상태를 조작하지 않았다.
- 합성2,200관찰 벤치마크(실제 DB/네트워크0): 기존0.8020초/DB 메서드110,000회 → 개선0.0644초/108개 배치. 관찰 쌍110,000개 동일. 이는 운영 DB 속도 또는 전체 처리 향상 배율의 실측이 아니며, 실제 stage ms는 운영 관찰 후 기록한다.1,024 batch는 이 fixture에서108호출/동일 결과로 검증한 범위다.
- 변경 Ruff/mypy2개 정책·DB 모듈, Dashboard TS/ESLint 통과. 최종 production build/운영 회차2개/평가·Codex·Import·품질/실제 UI/커밋·push는 아래에 후속 기록한다. 실제 하지 않은 검증은 성공으로 보고하지 않는다.

## 변경 파일

`scripts/079_research_stage_isolation.sql`, `migrate.py`, `provision-test-database.py`; `woori/research_stages.py`, `db.py`, `worker.py`, `trends.py`, `topics.py`, `trend_editorial.py`, `editorial_intelligence.py`, `editorial_scoring.py`, `keyword_jobs.py`; 단계/Trends 주제 테스트; Dashboard 기존 research page/proxy 및 pipeline-monitor 컴포넌트·CSS·E2E·screenshots; 본 기록과 AGENTS.md 최신 실행 계약. 관련 문서: P099-101, P102, P103, P104.

## 남은 검증

운영 DB 적용과 안전한 프로세스 교체 후 실제 회차 증가·평가 시간·허용 범위의 실제 Codex/Import/품질 평가·쓰기0·설정/기존 기록 보존 결과를 다음 체크포인트에 기록한다. Codex 한도 또는 검증된 출처 부족은 모의 성공과 구분한다.

## 운영 복구 1차 — 09:49~09:53 KST

- 구현 `3afdbe0`, 운영 schema79. 종료 전 실제 active Codex0/실제 running publication0/pending write0 확인. Research10232는 기존 stop-file로 파생 비교 체크포인트에서 정상 종료했다. 새 Research12096은 heartbeat 정상. 원본 수집/기존 커밋 자료는 보존됐으며 DB backend cancel/termination, OS force kill, Task Scheduler stop은0건이다.
- 변경 서비스만 정상 교체: API21936(launcher15628), Dashboard31448(launcher20648), Research12096. Publication32104와 PG16 PID6880/Crypto는 유지. HTTP200, P1047설정/revision9/기존37 Jobs/15 TOML/쓰기 원장 동일.
- 실제 회차 `09:40`: 새 Worker 시작 시 현재 회차,11/11 성공,09:50:00.812 완료/16.579초. `09:50`:11/11 성공,09:50:33.249 완료/17.115초. 완료 시각은 새 stage의 `clock_timestamp()`를 사용한다(기존 slot.updated_at은 트랜잭션 시작 시각이므로 완료 시각으로 사용하지 않는다). 과거07:20 이후 누락 회차는 재수집하지 않았고 `research.stage.missed_slots` 감사1개로 남겼다.
- 실제 평가 UUID `156d9c35-7cdf-4ea0-8bce-132f69b57cca`,09:50 회차,90개 Blogger·국가 후보,**2.920초**. selected15/high_risk2/review_candidate37/insufficient_context36. 실제 scores·원본 쿼리·설정 ID 보존. 레거시 168시간 전체 비교는 실행하지 않았다. 완료 직후 같은 평가를 반복하지 않음을 확인했다.
- 실제 Codex Job `eab9f9e4-bc08-48c2-a010-4d506a157a42`:09:50:44 시작 →09:52:01 imported_review, error 없음. Import **`84bce453-6778-4112-b5d1-a28ba5085dd6`**, native Content Version **`b73911d6-77b8-4427-a27c-e5dfc85f0616`**. 정적 품질 `trendjournal-quality/3.1` completed. 심층 평가를 추가 호출하지 않았다. Import/정적 완료를 사실 검증·공개 승인으로 승격하지 않았다. 게시 Job을 만들지 않았다.
- 실제3100 브라우저4 passed: P105 monitor1440/390 + P1047설정 회귀1440/390. 비GET 차단, pageerror/가로 넘침0, 실제 평가·Import poll 진행 표시. P105 live screenshot 보존. P104의 기존 역사 screenshot은 회귀 실행이 생성한 덮어쓰기본을 원래 커밋 bytes로 복원한다.
- 최종 넓힌 통합에서222 passed/기존 inbox mock1 failed가 있었다. P103이 추가한 ACK read/INSERT를 fake DB가 반영하지 않은 원인이며 제품 ACK를 우회하지 않고 fake revision/ACK assertion을 보강한 후 해당19개 전부 통과했다. 이어 단계/작성/Import45개 통과(새 admission 회귀 포함). 현재 고유 관련 테스트224개가 통과한 범위이며, 전체 저장소 suite 통과를 주장하지 않는다. Ruff,4모듈 strict mypy, Dashboard TS/ESLint/production build 통과.
- 관찰 중 cached evaluation 완료 뒤 남은 현재 회차 handoff를 계속 admission해야 함을 확인해 admission lane에 기존 expire/dispatch를 연결했다. 점수는 재계산하지 않고, 기존 current-slot·한도·single CLI 잠금을 그대로 사용한다. 첫 실제 Codex가 정상 Import까지 완료됐고 active Codex0임을 확인한 뒤 이 작은 보강만 Research에 정상 반영한다. API/Dashboard/Publication을 다시 재시작할 필요가 없다.

10:00 정상 회차와 이후 실제 결과는 후속 최종 체크포인트에 기록한다.

## 최종 운영 검증 — 10:02 KST

### 회차 및 평가

| 실제 회차 KST | stage 시작 | stage 완료 | 성공 지역 | 실측 처리 시간 |
|---|---|---|---|---|
|09:40(복구 시 현재 회차)|09:49:44.169|09:50:00.812|11/11|16.579초|
|09:50|09:50:16.066|09:50:33.249|11/11|17.115초|
|10:00|10:00:08.175|10:00:24.475|11/11|16.228초|

- 실제 slot ID가10분 간격으로 증가했다.09:50/10:00의 정상 주기를 관찰했고, collector가 이전 평가·작성·Import 완료를 선행 조건으로 기다리지 않음을 격리 slow-stage 테스트와 실제 단계 이력으로 검증했다.09:40 회차는 정상 재시작 시점의 현재 회차만 처리했으며 지난 모든 누락 회차를 재생한 것이 아니다.
-10:00 평가 UUID `13e57d81-8f0f-414f-880d-20513a606f98`:90개 후보,**2.090초**, selected10/duplicate3/review_candidate37/insufficient_context40. 실제 두 평가 평균2.505초. 같은 원고 이력을 다시 발견한 후보3개가 중복으로 분류됐고, 처리 결과를 덮어쓰지 않았다.10:00의 신규 작성 요청0건은 기존 시간당4개 한도에 따른 정상 결과다. 실패한 작성도 소모 한도를 되돌리지 않았다.
- 수집 UUID:09:40 `d946cd65-33c6-4ead-9345-acc98d3c0519`,09:50 `be50a85a-55ea-46a6-9688-9abfa89e4607`,10:00 `c1015245-be6f-41e6-a537-22771c6748ed`. 복구 전 수시간 트랜잭션과 달리 최종 운영 조회에서5분 초과 트랜잭션0건이었다.

### 실제 Codex·Import·품질 결과

운영의 정상 P101 선정·시간당4개 범위에서 실제 official Codex 실행4건, **Import/새 native Version/정적 평가 완료3건**, 생성 JSON 검증 실패1건이다. 별도 테스트용 키워드나 가짜 원고는 생성하지 않았다.

|Job|언어|Import|Content Version|결과|
|---|---|---|---|---|
|`eab9f9e4-bc08-48c2-a010-4d506a157a42`|ja|`84bce453-6778-4112-b5d1-a28ba5085dd6`|`b73911d6-77b8-4427-a27c-e5dfc85f0616`|imported_review|
|`607ea7df-1d3e-42f1-8b62-de9fc5496d09`|en|`1cbe16e9-aae4-4d61-8b9d-62a98f1ebd2f`|`ba3e44e6-6fb9-4042-abb0-2a507b0f74e2`|imported_review|
|`363a5b0f-5e64-41e4-b769-b26adac885d8`|en|`4648465f-2fc9-40ab-889d-35535fea29e8`|`d0aa11a4-7ec9-4794-a2dc-779d38ddfd83`|imported_review|
|`3d2996a5-1d92-4171-b770-286d7b0672d9`|en|없음|없음|failed / json_schema_invalid|

-3건 모두 `trendjournal-quality/3.1` static completed, fact_verified=false/publish_ready=false를 유지한다.1건에 수정 제안1개가 저장됐고 사용자 확인 없이 적용하지 않았다. 심층 평가 추가 호출0건. 원본/기존 Version 보존. 원고 품질 보조 점수를 검증 완료로 해석하지 않는다.
- JSON 실패1건은 성공으로 수정하거나 필드를 지어내지 않았다. 이번 작업에서 재시도·재가져오기를 강행하지 않았다.09:56의 실패 후에도10:00 수집·평가·Import poll은 정상 진행했다. 별도 사용량 제한 신호는 관찰되지 않았으며, 제공자 토큰 잔량·reset 시각·절약 토큰량은 추정하지 않았다. 서비스 CLI single-run과 기존4개/시간 설정을 유지했다.

### 예약·안전·UI

- P102는 이미 구현된 상태다. 실제 저장 원고의 정확한 scope로 trusted helper의 Backend 결과와 Backend503를 주입한 repository fallback을 재검증했고 둘 다 local_status=already_imported였다. remote_status=not_checked/blogger_read_complete=false를 그대로 유지하고 새 원고를 중복 Import하지 않았다. 실제 정상 서비스를 중지해 장애를 만들지 않았다.
- 기존15 automation.toml은 checksum 동일/ACTIVE15, 예약 시간/RRULE/프롬프트 변경0. 기존 automation-5의2026-10-31 12:00 KST 프로젝트 파생 occurrence에 새 Import origin event0, pending manuscript file0. 이번 개발 세션을 그 과거 예약 실행으로 위장하지 않았고 실패 슬롯을 성공으로 덮어쓰거나 재실행하지 않았다. 이번 관찰 구간에서15개 각각의 신규 Desktop 예약 전달 성공은 확인하지 않았으며 다음 실제 예약 실행은 별도 관찰 대상이다.
- 최종 Research **18928 / db8bcfe**, API21936·Dashboard31448 /3afdbe0. Publication **32104** 기존 프로세스 유지. Research12096의 첫 실제 Codex가 정상 종료·Import 완료된 뒤 active Codex0임을 확인하고, admission만 정상 종료/재시작으로 보강했다. Research/Publication 모두 revision9/automation-controls2/fresh PID heartbeat ACK. API health/research monitor/automation center/sources/manuscripts 모두 HTTP200. 새 Worker의 독립 scheduled intake ACK 지속 갱신.
- 최종 정책은 원래7개 값 및revision9 그대로다. 운영 감사 **283919**에 실제 회차3·평가2·Codex4·Import3·실패1·품질3·쓰기0·보존 결과 기록. Blogger write operation0/live attempt0/외부 비GET Blogger audit0/publication grant0. 기존37 Publishing Jobs와 쓰기 원장,15개 예약 파일 동일. 수동 게시도 직접 요청하지 않았다. PG16 Running/Auto PID6880, Task Scheduler Ready/LastTaskResult0, Crypto 변경0.
- 최종 Chromium: Mock8 + 실제 P1052 + P104 회귀2 = **고유12 passed**. 실제 P105를 새 Worker/10:00 회차 이후 다시 확인했다.1440/390 다크 테마, 검색/필터, 빈/장애/정체/사용량 대기, import/품질/실측 평가·단계 분리, pageerror/가로 넘침0. 마지막 실제 화면은 `assets/P5-CODEX-105-live-{desktop,mobile}.png`.

### 최종 테스트 및 남은 항목

- 변경 범위 최종 통합 **224 passed (22.63초)**, 실패0. 앞선 통합에서 과거 assessment를 ORDER 없이 가져오던 테스트가 역사 row의 예전 이유 코드를 선택한 경우가 있었다. immutable 이력을 삭제하지 않고 최신 created_at/id를 명시해 현재 평가를 검사하도록 고친 뒤14개 관련 테스트 및 최종224개가 통과했다. 제품 검증 기준을 낮추지 않았다.
- Ruff 변경 범위 통과, strict mypy4모듈(research stages/DB/P101 scoring/API) 통과, Dashboard TypeScript/ESLint/독립 production build 통과. Next가 검증 중 바꾼 next-env/tsconfig는 원래 bytes로 복원했다. 전체 저장소 suite green으로 확대 해석하지 않는다.
- 잔여: 위 실제 생성 실패1건의 모델 출력 형식은 별도 검토 대상이다. 심층 의미/사실/권리/편집 검토와 수동 게시 쓰기 성공은 수행하지 않았다. 다음15개 실제 예약 실행 및 장기간 가동 관찰은 이번 짧은 복구 검증과 구분한다. 파이프라인 정체 해결과 운영 반영은 완료했고, 이 제한을 성공으로 덮지 않는다.

최종 test/docs 커밋·origin/develop SHA는 Git 후속 기록에 연결한다. main 병합 없음, 기존 stash 유지, 기존 두 `.playwright-mcp/` 미추적 디렉터리는 그대로 둔다.
