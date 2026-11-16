# P5-CODEX-017 — Publisher read-back, intake capability audit, and operating blockers

- 작업 ID: P5-CODEX-017
- 작업 일시: 2026-10-29 (Asia/Seoul)
- 브랜치: `develop`
- 변경 사유: 실제 원고 Import·검증과 Publisher 연결/초안 검증을 요청받음.

## 문제 및 목표

P5-CODEX-016은 `BloggerLivePublisher` 초안·공개 adapter, idempotency 원장, Trends schedule tick을 추가했지만, 발행 queue는 계속 `FakeBloggerPublisher`만 처리하며 라이브 Blogger post 생성 직후 원격 read-back이 없었다. 원고 자동 생성 Provider는 여전히 구성되지 않았고, 예약 작업 파일 수신의 현재 계정 지원 여부도 증거가 필요했다.

목표는 기존 구현을 재사용해 실제 가능한 상태를 확인하고, 안전 조건 안에서 빠진 read-back 검증을 추가하며, 실제 계정·운영 DB·외부 게시 결과와 코드/Mock 결과를 분리해 기록하는 것이다.

## 변경 전 / 변경 후

- 변경 전: 라이브 초안 insert 성공 응답만으로 adapter 성공을 기록할 수 있었고, 생성한 게시 ID의 Blogger 재조회는 하지 않았다.
- 변경 후: 초안 insert 뒤 같은 OAuth 연결로 게시물 GET을 수행하고, ID·blog ID·`DRAFT` 상태가 일치해야만 `post_verified=true`로 원장에 성공 저장한다. 재조회 불일치/실패는 성공으로 기록되지 않는다.
- 운영 Import: 이번 실행은 운영 DB에 새 원고를 Import하지 않았다. Research Package 0개라 원고 연결을 만들 수 없었고, 없는 패키지 ID를 만들어 넣는 것은 피했다.
- 라이브 Publisher: adapter 코드는 존재하나 기존 publishing queue/Worker에 연결되지 않았다. 이번 변경도 공개 게시/Auto 게이트를 해제하지 않았다.
- AI 자동 작성: production generator 미구성. 자동 생성 실적 0건.

## 현재 운영 근거

인증된 loopback read-only API (`http://127.0.0.1:8100/admin/operations/dashboard`, `/admin/research/state`, `/admin/blogger/status`)로 확인했다. 프로세스 소유 경로는 이 checkout의 `.venv` Python과 Node였고, 서버는 종료하거나 재시작하지 않았다.

- schema version: 48
- 기존 콘텐츠 버전: 360 (작업 중 새 버전 추가 없음)
- 감사 이벤트: 1,526 (read-only observation time; finalization audit is appended separately)
- Trends: 최근 24시간 160 observations, 성공 run 16, 실패 0
- 지역별 최근 24시간: HK 30, JP 30, KR 30, SG 30, TW 20, US 20
- research package: 0; topic: 0
- research worker heartbeat: `inactive` (현재 45초 freshness window 내 running 증거 없음)
- 글로벌 publication mode: `manual`; live auto/write disabled; 게시 hourly cap 미설정
- 연결된 Blogger 4개 모두 기존 `blogger.readonly` 연결에 매핑됨
- 별도 write-scope OAuth 연결 존재만으로 특정 계정·블로그 연결이 확인되지는 않음
- Blogger 게시 API 호출 0, 기존 게시물 수정/삭제 0
- 운영 원고 Import 0, 자동 AI 원고 0

실제 Blogger 쓰기는 호출하지 않았다. 현재 환경에서 draft 승인 기록은 비용 게이트를 허용하지만, 한국어 블로그가 readonly 연결에 매핑되어 있고 선택 가능한 계정/연결의 소유자가 특정되지 않았다. 사용자가 특정 OAuth 연결 및 매핑을 승인하기 전에는 draft POST를 안전하게 실행할 수 없다. 공개 게시/Auto 범위는 별도이며 계속 차단 상태다.

## 공식 자동화 경로 확인

OpenAI Help Center의 현재 문서는 ChatGPT Work와 Codex를 별도 제품 흐름으로 설명한다. Work scheduled tasks는 반복 실행을 지원하며, Work 데스크톱은 권한을 부여한 로컬 폴더를 쓸 수 있다. 공식 문서는 cloud Work와 로컬 Work가 구별되고 local-work 권한/rollout 및 컴퓨터 online 상태에 달렸다고 설명한다. 따라서 계정에 Work local-folder 기능이 보인다는 것만으로 해당 반복 task가 로컬 실행이라는 결론은 낼 수 없다. 이 Windows 앱은 최소화되어 있어 task details, 로컬 폴더 권한, 실제 결과 파일을 UI에서 확인하지 못했다. 현재 ChatGPT task의 자동 수신은 **검증되지 않음**이다.

Codex scheduled automations의 공식 개발자 문서는 API의 hosted agent session/automation 경로를 기술한다. 이는 Plus 사용량 내 로컬 PC 파일 전달을 보장하지 않으며 프로젝트의 zero-additional-cost 정책에 따라 연결하지 않았다. 비공식 API, 쿠키/세션 추출, unattended Codex CLI는 사용하지 않았다.

OpenAI sources: [ChatGPT Work and Codex](https://help.openai.com/en/articles/20001275-chatgpt-work-and-codex), [Scheduled tasks in ChatGPT](https://help.openai.com/en/articles/10291617-scheduled-tasks-in-chatgpt), [Agent Security and local work sync](https://help.openai.com/en/articles/20001548-agent-security-and-local-work-sync), [Scheduled automations](https://developers.openai.com/api/docs/guides/agents-api/sessions/automations).

## 수동 작성 원고

한 차례 대화형 Codex가 공식 Census, BEA, BLS 자료를 확인해 한국어 칼럼 초안을 작성했다. 이는 예약 자동 생성이 아니다. article artifact: [P5-CODEX-017-article-ko.md](P5-CODEX-017-article-ko.md).

- 원고 Import: 0 (운영 DB에는 기록되지 않음)
- 품질 assessment / HTML preview: 0 (운영 API 실행하지 않음)
- Research Package 연결: 미완료 (DB에 package 없음)
- 권리 상태: 미검토, source records에 입력한다면 `unknown` 유지
- 독립적 사실 확인/편집자 승인: 미완료
- 게시 및 공개 URL: 없음

2026-10-29 09:20 KST 기준 BEA의 September PIO release는 같은 날 21:30 KST 예정이어서 기사에서 사용하지 않았다. 8월 PCE는 9월 30일 발표된 값이다. [BEA August PIO](https://www.bea.gov/news/2026/personal-income-and-outlays-august-2026), [Census September retail sales](https://www.census.gov/retail/sales.html), [BLS September CPI](https://www.bls.gov/news.release/archives/cpi_10142026.htm).

## 수신 경로 조사

새 importer를 만들지 않았다. 기존 `services/api/woori/scheduled_import_inbox.py`는 `.local/gpt-scheduled-import/{ready,processing,processed,failed,quarantine}`를 사용하며 bounded JSON read, Pydantic schema check, hash/name-derived claim, API idempotency, completed/error movement, processing recovery 및 scheduled-origin audit를 구현한다. Windows runbook에서 운영 DB import는 명시적으로 `--operations --confirm-operations-import`를 요구한다. 규격은 `woori-scheduled-content-import/1.0` scheduled export로 제한되고, 사용자 수동 Codex import는 기존 API `woori-content-import/1.0` 경로와 별개다.

## 코드 변경

- `services/api/woori/blogger_writes.py`: 실초안 생성 후 same-connection read-back 검증 추가; 성공 결과는 `post_verified` 및 GET status 저장.
- `services/api/tests/test_blogger_live_policy.py`: MockTransport GET(blog) → POST(draft) → GET(post) 순서와 잘못된 read-back 상태의 실패 기록을 검사.
- `docs/development/P5-CODEX-017-article-ko.md`: 공식자료 기반의 단회 수동 작성 원고와 review metadata.
- `docs/development/P5-CODEX-017.md`: 본 작업/환경 근거 및 차단조건.

## 검증

- `python -m pytest services/api/tests/test_blogger_live_policy.py services/api/tests/test_scheduled_import_inbox.py -q`: 29 passed.
- 테스트는 격리 `.env.test`에서 수행했고 신규 테스트는 DB 호출을 mock 처리했다.
- 실제 API live external request: 0. Blogger POST: 0. 유료 AI API call: 0.
- 운영 API read-only state calls: dashboard/research/blogger status; data row writes 0.
- 전체 `scripts/verify.ps1`: 실행하지 않음.
- ChatGPT 예약 파일 생성 end-to-end: Not Covered (UI task details/permissions/result unavailable).
- 운영 Import/quality/HTML/queue E2E: Not Covered (package 없음; 수동 원고 운영 DB에 적재하지 않음).
- Blogger draft read-back live E2E, public publish, Auto Worker: Not Covered.

## 남은 문제

1. 운영자가 사용할 write OAuth 연결을 식별하고 Korean blog mapping을 승인해야 한다. 연결 label/scope만으로 Google account identity를 추정할 수 없다.
2. Google Cloud Blogger API cost/billing/quota 상태는 이번에도 별도 검증하지 않았다. 이전 기록상 public publish와 unattended Auto는 승인 범위 밖이다.
3. 운영 Research Package 0개. official source capture, source-span evidence, rights review, package 생성이 원고 Import 전에 필요하다.
4. 공식 ChatGPT Work task에서 local Work mode와 이 inbox 폴더의 write 권한을 실제 계정 UI에서 검증해야 한다. 기존 API manual JSON import는 유지한다.
5. `BloggerLivePublisher`는 publishing queue/Worker에 연결되지 않았고 Auto 설정은 계속 disabled다.
6. BEA September PIO release 이후 해당 원고의 최신성/수치를 다시 확인해야 한다.

커밋 해시: adapter `379c7c5a68bbbfd18a5210a614f971eee3a97285`; mismatch regression test `46b756a`. 이 문서의 포함 커밋은 `git log -- docs/development/P5-CODEX-017.md`로 확인한다.
관련 선행 기록: P5-CODEX-011~016, `docs/operations/P5-CODEX-013-publisher-readiness.md`, `docs/operations/zero-cost-policy.md`.
