# P5-CODEX-034 — Trends-to-Blogger 운영 파이프라인 단절 진단

- 작업 일시: 2026-10-29 (Asia/Seoul)
- 작업 브랜치: `develop`
- 변경 사유: 최근 Trends 520건 이상이 쌓였지만 무인 원고 및 공개 게시가 0건이라는 운영 문제의 최초 차단 단계를 실제 DB·Worker·코드로 확인
- 목적: 성공 단계를 다시 만들지 않고 첫 0건과 후속 차단을 증거에 따라 구분

## 변경 전 상태

- 사용자가 관측한 최근 24시간 Trends: 520건
- 자동 생성 원고 및 공개 게시: 0건
- Publication Worker 실행 옵션: `--operations-mock-only --continuous`
- Auto/운영 쓰기 상태: `manual`, Auto OFF, 실제 쓰기 차단

## 실제 확인 결과

운영 DB(`woori_blog_agent`)는 트랜잭션 read-only로 조회했다. 최신 표본 시각은 2026-10-29 14:39 KST 전후다.

| 파이프라인 단계 | 최근/전체 실제 수치 | 상태 및 증거 |
|---|---:|---|
| Trends 수집 | 최근 24시간 540건, 성공 run 54, 실패 0 | 11개 지역 관측 존재, Research Worker heartbeat 갱신 중 |
| 중복 제거 이슈 | 446개 | `trend_topics`와 관측 membership 기준 |
| 기사 후보 | 0개 | 최신 이슈 평가에서 446개 전부 `held` |
| 조사 후보 선별 | 최근 기록 4개 | 7개 적격 후보 중 시간당 4개 선택. 기록에 `official_research_executed=false` |
| 공식 조사 성공 | Worker 자동 조사 실행 0건 | `collect_trends_and_build_topics()`는 후보 선별까지만 호출하며 조사/출처 수집 작업을 실행하지 않음 |
| Research Package | 최근 24시간 1건 | `c0b6f2b2-7a74-4b3f-a4f1-f4219c12321d`, SG `fed meeting` 이슈. Fed 공식 보도자료 RSS 원천 1개가 연결되고 출처 검토는 승인됐지만 패키지는 `evidence_collected_pending_human_review`; 게시 승인 아님. 이번 시간에 선정된 4개 주제에는 연결된 공식 출처가 0건 |
| 원고 생성 | 실제 운영 Provider 생성 0건 | Provider `not_configured`; 결과 4건은 `mock_draft`, 11건은 `quality_held` |
| GPT 예약 실행/파일 수신 | 0건 / 0건 | scheduled claims 0, verified runs 0, scheduled import 0, 수신 폴더 파일 0 |
| 기존 Import | 1건 | `manual_codex_import`, `awaiting_human_review`; 예약 자동 수신 아님 |
| 자동 품질 통과 / 게시 적격 | 예약 Import 기준 machine pass 0/0; auto dispatchable 0건 | 유일한 기존 Import의 최신 평가 machine pass=true지만 독립 출처 검증=false, generation-ready=false, publish-ready=false |
| Publishing Job | 1건 | `fake`, `simulation_only=true`, `blocked/quality_held`; live job 0건 |
| Publication Worker | PID 20652, heartbeat fresh | mock-only lane, due job 0; `no_queued_job_in_enabled_lane` |
| Blogger 쓰기/공개 게시 | 공개 게시 0건 | live publication attempt 0, 검증된 공개 record 0. 과거 draft operation 성공 기록 4건은 공개 게시로 집계하지 않음 |

### 최초 0건과 원인

첫 0건은 **기사 후보 평가**다. 최신 24시간 이슈 446개 전부가 다음 사유로 보류됐다.

- 설정 점수 미달: 446
- 독자 가치/분석 적합성 사람 검토 필요: 446
- 두 독립 출처 사람 검증 미완료: 446
- 공식 조사 대기: 445
- 지역 간 사건 그룹핑 사람 검토 필요: 68
- 광범위 검색어 구체화 필요: 2

후보 선별 Worker는 시간당 최대 4건을 기록할 뿐 실제 조사 Worker를 연결하지 않았다. 별도의 Research Package 1건은 검토 대기 상태다.

후속 독립 차단은 **운영 원고 Provider 미연결**, **예약 JSON 실행 및 전달 미검증**, **공개 발행 설정 차단**이다. 현재 Publication Worker는 큐에 쓸 원고가 없을 뿐 아니라 mock-only 모드다. 운영 DB의 mode는 `manual`, 일일 auto limit 1, 최소 간격 1440분, `operations_auto_approved=false`, Auto policy inactive이며 live Blogger dispatch/write가 꺼져 있다. 이를 이번 진단에서 변경하지 않았다.

`publications.py`의 auto eligibility 판정은 증거가 read model에 없을 때 출처 본문·핵심 사실·의미 일치·권리·독립 검증·언어·SEO·HTML·중복·최신성·블로그 매핑을 확인되지 않음으로 처리한다. 임의로 `true`를 공급해 통과시키면 안 된다.

## 공식 예약 작업 경로 판정

OpenAI 공식 문서는 ChatGPT 데스크톱의 예약 작업이 로컬 프로젝트 또는 격리 worktree에서 실행될 수 있다고 설명한다. 로컬 파일이 필요한 작업은 컴퓨터와 데스크톱 앱이 켜져 있어야 한다. 웹 예약 작업은 로컬 폴더에 직접 접근할 수 없다. 이 저장소/계정의 예약 작업 등록, 실행 권한, 사용량/추가 크레딧, 실제 JSON 전달은 확인되지 않았다. 그러므로 공식 제품상 가능한 기능과 이 프로젝트에서 동작이 입증된 자동 공급은 별개이며, 실제 성공 수는 0이다.

초기 수동 연결 단계: ChatGPT 데스크톱 앱에서 이 로컬 프로젝트를 선택해 예약 작업을 생성하고, 기본 샌드박스 권한 내에서 `.local/gpt-scheduled-import/incoming/`에 JSON을 원자 저장 후 `ready/`로 이름 변경하도록 구성한다. PC와 앱을 켜 둔 첫 실행에서 실행 ID, 파일 hash, 실제 경로 및 Import 감사 결과를 확인해야 한다. 예약 작업 사용량이 현재 구독에 포함되는지/추가 크레딧을 쓸 수 있는지 운영자가 확인하기 전에는 실행하지 않는다. 수동 JSON이나 Codex 대화 원고는 이 실험의 성공으로 대체할 수 없다.

## 변경 후 상태 및 판단

- 코드, 운영 설정, 게시 큐, OAuth, 원고, Research Package는 변경하지 않았다.
- 수정 파일: 이 개발 기록 1개.
- DB 진단: 운영 DB read-only. 실행 중 프로세스 종료/재시작 없음.
- 운영 감사 기록: `agent.execution.completed`, event ID `176294` (비밀값 및 원고 본문 미기록).
- 실제 Blogger 공개 게시: 0건, URL 없음. 외부 쓰기/Auto OFF 유지.
- 테스트: 코드 변경 없음으로 전체/기능 테스트를 실행하지 않음. 운영 Dashboard projection과 Worker `--status` read-only 확인, SQL 단계별 집계만 수행.
- 최종 판정: **BLOCKED** — 기사 후보 0, 조사 실행 미연결, 생산 원고 Provider 미설치, 공식 예약 파일 자동 수신 미검증, Blogger 쓰기/공개 dispatch 금지 상태.

## 남은 조치

1. 우선 기사 후보 평가/독자 가치 기준을 실제 조사 후보와 분리하고, 조사 shortlist의 공식 자료 조사 작업을 기존 allowlist/provider 경로에 연결한다. 미확인 사실이나 권리 게이트는 보류 상태로 둔다.
2. ChatGPT 데스크톱에서 사용 가능한 예약 작업/프로젝트 권한 및 추가 과금 가능성을 확인하고, 실제 예약 실행 파일 전달을 검증한다.
3. 기계 검증으로 입증할 수 없는 의미·권리 항목을 자동 통과시키지 않는다. 신뢰할 수 있는 승인 검증 수단이 연결되기 전에는 자동 공개를 허용하지 않는다.
4. Blogger 실제 쓰기 비용/쿼터 상태와 운영 게시 정책을 별도 확인하고 명시적으로 Auto/공개 쓰기를 활성화하기 전에는 외부 POST를 실행하지 않는다.

## Git / 추적

- 테스트/정적 검사: 문서 전용 변경으로 미실행. read-only 운영 확인에서 API `/health`와 Dashboard `/` HTTP 200, Publication Worker `--status` heartbeat fresh를 확인.
- 커밋 해시: 이 파일을 포함하는 커밋으로 `git log`에서 확인한다(자기 참조 해시).
- 관련 코드: `services/api/woori/operations_dashboard.py`, `topics.py`, `worker.py`, `collection.py`, `publications.py`, `publication_modes.py`, `publication_worker.py`.
