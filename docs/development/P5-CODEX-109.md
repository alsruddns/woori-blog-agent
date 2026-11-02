# P5-CODEX-109 — Trends 자동 LIVE 및 통합 발행 검증

## 작업 기록

- 작업 일시: 2026-11-03 (Asia/Seoul)
- 브랜치 / 시작 HEAD: `develop` / `6c4aea3a5ab632ff08ae4a97f7d38d0c46ebe473`
- 변경 사유: Trends 자동 발행이 계속 꺼져 있고, 적격 Trends Job이 Worker에 claim되지 않으며, 기존 게시물 자체가 원격 중복으로 오판될 수 있는 경로를 확인함.
- 변경 목적: 운영자 정책 설정과 실제 Blogger 쓰기 권한을 분리하고, 신규 Trends Job이 현재 설정 Revision에 결속되도록 하며, 자기 Job에 연결된 postId가 중복 검색 결과로 차단되지 않게 함.
- 관련 문서: `docs/operations/zero-cost-policy.md`, P5-CODEX-108

## 변경 전 / 후

### 변경 전

- 운영 설정 revision 13: Trends 수집 ON / 30분, Codex 작성 ON, 전체 자동 발행 ON, Trends 자동 발행 OFF, 예약 자동 발행 ON, 수동 발행 ON, LIVE 모드, 전역 발행 간격 30분, 긴급 정지 OFF, Blogger API 제한 OFF.
- Trends 정책 등록 API가 `blogger_writes_allowed()`를 요구했다. 이 검사는 정확한 실행 중 Blogger 쓰기 컨텍스트가 없으면 false이므로, Blogger API를 호출하지 않는 관리자 설정 이벤트도 거부될 수 있었다.
- Trends 자동 Job 생성기가 같은 실행 컨텍스트 검사를 먼저 수행해 정상 자동 큐 등록을 막았다.
- 해당 생성 경로는 `automation_publication_grants`를 기록하지 않았으나 Worker claim은 현재 `auto_epoch`와 `trends_auto_epoch`에 결속된 grant를 요구했다.
- manual/scheduled Worker 중복 검사는 Job 자신의 이미 연결된 `remote_post_id`를 제외하지 않아 자기 게시물이 `remote_duplicate_found`로 반환될 수 있었다.
- scheduled/Trends의 DRAFT 생성이 manual 전용 승인 Context를 사용했고, 자동 발행 원고에는 필요한 payload snapshot이 초기화되지 않는 경로가 있었다.

### 변경 후

- 관리자 Trends 정책 API는 인증된 설정/감사 기록만 저장한다. 실제 Blogger 요청은 하지 않으며, 기존 write-scope, zero-cost, Blogger 외부정책, 자동화 grant, 긴급 정지, 중복 검사 및 API 직전 검사는 유지된다.
- Trends 큐 생성은 자동화 설정·긴급 정지·Google 제한 상태·전체 자동 발행·Trends 경로 설정을 DB에서 잠금 조회한다. 전역 발행 모드와 블로그별 정책 모드가 다르면 보류한다.
- 신규 Trends Job에 `automation_publication_grants`를 추가하고, 현재 전체 자동화 epoch와 Trends source epoch, import/version lineage를 함께 기록한다. 생성 감사 이벤트도 추가한다. 활성화 전 collection slot과 기존 Job은 큐에 넣지 않는다.
- manual, scheduled, Trends 중복 검사 모두 해당 Job에 이미 연결된 postId만 제외하고 나머지 원격 후보는 그대로 판정한다.
- 자동 DRAFT 요청은 생성 경로에 맞는 scheduled/Trends Context를 사용한다. manual DRAFT는 기존 exact-version 승인 Context를 계속 요구한다.
- Blogger API 쓰기 동작은 운영 환경에서 실행하지 않았다.

## 조사한 운영 상태

- API `/admin/automation-controls`: HTTP 200, revision 13.
- Research Worker PID 8848, Publication Worker PID 20104: 두 Worker 모두 revision 13을 적용 중이며 heartbeat가 신선함.
- Google Trends 수집 기록: 2026-11-03 05:00, 05:30, 06:00, 06:30 KST 4회 모두 각 11개 지역 성공(11/11). 수집 간격은 30분이며 Blogger 전역 발행 간격 30분과 별도 설정이다.
- 최근 DB 상태: scheduled_auto LIVE 성공 1건, 수동 LIVE 성공 19건, Trends Draft 성공 3건, Trends Draft 실패 15건, 오래된 Trends queued 1건. 과거 queued Job은 현재 활성화 epoch/grant를 갖지 않아 재실행하지 않았다.
- Blogger OAuth 연결 4개 블로그 식별 읽기 확인은 완료됐지만, 읽기 확인은 쓰기 권한이나 계정 결제 상태를 증명하지 않는다.
- EN/KO/JA에는 Trends 지리 매핑이 있다. ZH에는 현재 소스 지리 매핑이 없어 자동 Trends 발행 대상에 넣지 않는다.
- 운영 설정 변경 전 DB 백업: `backups/20261102T215831Z.dump` (custom archive catalog 검증 완료). Migration 081은 기존 적용 상태였고 P109는 Migration을 추가하지 않았다.

## 결함 분석

### Trends 자동 발행 OFF

설정은 Trends 경로가 OFF였고, EN/KO/JA 블로그별 정책도 `draft`였으며 LIVE 승인 이벤트가 없었다. 정책 상태는 `authenticated_public_publish_approval_required`를 반환했다. 여기에 설정/큐 생성 코드가 실행 중 writer context를 요구해 운영자 승인·큐 생성 단계를 차단하는 코드 결함도 있었다. 코드 결함은 수정했지만 운영 LIVE 승인은 적용하지 않았다.

### `remote_duplicate_found`

확인된 Job `b8bf35ad-ef2d-4091-9c71-7c293b9ac808`은 `remote_post_id=633275275358355889`를 이미 보유했고, 그 동일 Blogger postId가 실제 Trend KO LIVE 게시물로 확인됐다. 기존 중복 검사가 자기 소유 postId를 제외하지 않아 자기 Job의 게시물을 다시 중복으로 보고 차단한 경우다. 이 원고는 이미 remote LIVE이고 Job은 과거 `blocked` 상태이므로 재시도·재게시·기존 Job 상태 변경을 하지 않았다. 새 로직은 자기 소유 postId만 검사에서 제외한다.

### 예약 원고 자동 발행

Worker의 새 revision-bound claim은 Automation grant가 필요하다. 기존 Trends 생성 경로의 grant 누락과 DRAFT Context 결함은 확인·수정했다. 현재 운영 DB에는 성공한 scheduled_auto LIVE Job 1건이 있고 queued/running scheduled_auto Job은 없다. P109 중 신규 예약 원고 생성·Import 또는 LIVE 게시를 수행하지 않았으므로 새 예약 원고 종단 간 성공은 미검증이다.

### 수동 LIVE

공통 Publishing Worker는 LIVE와 DRAFT를 별도로 처리하며 `create_live` 및 remote readback 경로를 갖는다. 테스트는 Mock Publisher로 실제 `LIVE` 결과를 검증했다. 기존 사용자가 요청한 운영 원고를 이번 작업에서 새로 queue하거나 게시하지 않았다. 현재 저장된 remote LIVE 증거가 있는 과거 수동 Job의 정합성은 위 중복 분석에 기록했다.

## 운영 발행 승인 및 미적용 사유

현재 Blogger cost attestation은 `blogger_read`, `private_draft_create`, `user_approved_post_update` 범위이고, public-write cost/billing basis는 확인되지 않았다. 로컬 상태는 Blogger write access와 account billing을 증명하지 않는다. Google 공식 Blogger API 문서는 게시물 생성/수정 기능을 설명하지만 가격 또는 0원 할당량을 보증하지 않으며, Google Cloud 문서도 일부 API는 사용량 과금을 받을 수 있다고 설명한다. 프로젝트의 0원 외부 서비스 정책에 따라 Trends public LIVE 승인 이벤트, 자동 발행 설정 ON, production API POST를 이번 변경으로 적용하지 않았다.

따라서 DB의 Trends 자동 발행은 계속 OFF이고 per-blog EN/KO/JA 정책은 기존 Draft 상태 그대로다. 자동 발행 설정을 켜거나 fake approval을 생성해 차단을 우회하지 않았다. 현재 Blogger API write call은 0건이며, 실제 신규 LIVE 공개 성공은 0건이다. 계정 제한 신호는 로컬 DB에서 OFF지만 이것은 계정 billing/정책 승인이 아니다.

## 테스트 및 검증

- 변경 범위 API 테스트: `test_publications.py`, `test_trends_post_edit.py`, `test_trends_publication.py` — 70 passed.
- 추가 통합 테스트: `test_publication_interval.py`, `test_blogger_live_policy.py`, `test_automation_controls.py`, `test_publication_origin_controls.py`를 포함한 전체 변경 범위 — 168 passed.
- Ruff: 변경 Python 및 테스트 파일 6개 통과.
- Python compile: 변경 런타임 모듈 2개 통과.
- 서비스 반영 사전 검증에서 mypy가 optional snapshot narrowing 문제를 처음 발견했다. manual lane의 snapshot 비어있지 않음을 명시적으로 검사하도록 보강했고, Ruff·mypy·py_compile 재실행은 통과했다. 첫 사전 검증은 서비스 정지 전에 종료되어 운영 PID에는 영향이 없었다.
- Mock 통합 테스트: Trends 정책 이벤트 저장을 writer context 없이 허용하되, 자동 Job에는 현재 epoch grant를 생성하고, LIVE/DRAFT 상태를 분리 확인.
- Mock 중복 테스트: manual/scheduled/Trends 모두 자신의 원격 postId만 제외하는 매개변수 검사.
- 브라우저 1440px/390px: P109 Dashboard UI 변경 없음. 실브라우저 UI 작업/검증은 해당 없음.
- Blogger API POST/PUT/PATCH/DELETE: 0건. 실제 운영 LIVE 생성: 0건.
- Worker/API 재시작: 아직 수행하지 않음. 서비스 상태를 보호했고, Trends auto 설정이 OFF인 가운데 코드 반영 재시작은 생략함.

## 변경 파일

- `services/api/woori/trends_publication.py`
- `services/api/woori/publication_worker.py`
- `services/api/tests/test_publications.py`
- `services/api/tests/test_trends_post_edit.py`
- `services/api/tests/test_trends_publication.py`
- `services/api/tests/test_automation_controls.py`
- `docs/operations/zero-cost-policy.md`
- `docs/development/P5-CODEX-109.md`

## 남은 항목

1. Blogger API public write의 실결제/무료 사용 근거 및 Cloud Billing 상태가 승인된 절차로 확인되어야 한다.
2. 해당 근거가 확인된 뒤 인증된 관리자 UI/API에서 Trends public LIVE 승인을 EN/KO/JA 개별 범위로 기록하고, auto controls를 활성화해야 한다. ZH는 실제 source mapping 확인 전 제외한다.
3. 안전하게 반영된 후 신규 Trends 원고와 신규 예약 원고의 LIVE를 실제 운영에서 관찰해야 한다. 테스트 게시물은 만들지 않는다.
4. 예약 신규 실행의 LIVE 성공, 수동 사용자의 명시적 LIVE 요청, 30분 Trends 수집 연속 회차는 각 실제 사건 발생 시 별도 검증한다. 이 시점에는 4개 연속 수집 회차(11/11)를 확인했다.

## Git / 감사

- 작업 시작/완료 및 주요 변경은 개발 기록에 남겼다. 운영 DB 설정은 변경하지 않아 설정 변경 감사 이벤트는 만들지 않았다.
- Commit hash: 이 기록을 포함한 커밋은 `git log -- docs/development/P5-CODEX-109.md`에서 확인한다.
- origin/develop push 상태는 최종 보고에서 별도로 확인한다.
