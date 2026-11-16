# P5-CODEX-011 — 예약 원고 파일 수신과 자동 게시 준비 경계

## 목적 및 기준

- 작업일: 2026-10-29 (KST)
- 기준 브랜치: `develop`
- 기준 커밋: `c52f0c5`
- 사유: 운영 원고 생성 Provider가 없는 상태에서 GPT 예약 원고를 공식·안전하게 수신할 수 있는 실제 경로를 준비하고, 운영 Auto 기능과 구현 범위를 구분한다.
- 기존 현황: Google Trends는 수동 수집 API, 외부 원고 Import와 품질/SEO/HTML 검사·Mock Publisher는 구현되어 있다. AI 예약 생성·공식 자동 전달·실제 Blogger 쓰기·운영 Auto는 연결되어 있지 않다.

## 공식 일정 작업 지원 검토

OpenAI 공식 문서상 ChatGPT Project에 생성한 예약 작업은 프로젝트에 업로드된 파일을 읽지 못한다. ChatGPT 데스크톱 Work는 계정·권한이 허용되면 로컬 폴더를 사용할 수 있고, 로컬 파일이나 로컬 skill이 필요한 실행은 PC와 앱이 켜져 있어야 한다. 공식 문서는 이 앱으로 직접 전달하는 generic webhook/API, 예약 실행의 안정적인 파일 생성, 예약 task ID를 이 서비스가 조회하는 인터페이스를 약속하지 않는다.

따라서 외부 계정에 작업을 생성하지 않았다. 사용자가 Work 로컬 폴더 권한을 직접 허용한 후 일회성 산출물 쓰기를 시험해야 한다. 실패하면 기존 `/imports`의 파일/텍스트 수동 Import를 사용한다. 근거: [Scheduled tasks in ChatGPT](https://help.openai.com/en/articles/10291617-scheduled-tasks-in-chatgpt), [ChatGPT Work and Codex](https://help.openai.com/en/articles/20001275-chatgpt-work-and-codex), [OpenAI scheduled-task walkthrough](https://developers.openai.com/training/walkthroughs/scheduled-tasks).

## 구현

- `woori-scheduled-content-import/1.0` 로컬 파일 wrapper를 추가했다. 본문 `item`은 기존 strict `woori-content-import/1.0`으로 그대로 검증한다. wrapper는 task type, self-reported task/occurrence IDs, 실행/시장일, 대상 언어와 Blog ID/URL, 자료 기준 시각을 포함한다. reservation identity는 확인하지 않은 주장으로 감사된다.
- 관리자 API가 scheduled origin을 별도 append-only `audit_events` 이벤트로 저장한다. 이벤트는 등록된 활성 Blogger ID·URL·언어와 일치해야 한다. 같은 task/occurrence의 중복 또는 바뀐 메타데이터를 409로 차단한다.
- `scripts/import-scheduled-content.py`를 추가했다. 고정된 `.local/gpt-scheduled-import/ready`에서 원자적으로 완료된 `*.ready.json`만 최대 4개 처리하고, `processing/processed/failed/quarantine` 상태 디렉터리와 중단 파일 복구를 쓴다. HTTP는 loopback만 허용하며 8100 운영 API는 `--operations --confirm-operations-import` 두 옵션을 모두 요구한다. 응답·오류 로그는 본문/토큰을 출력하지 않는다.
- Inbox는 기존 API로 검토 대기 Import → 예약 출처 감사 → 해당 버전에 대한 기존 기계 품질·SEO·HTML 평가 순서를 수행한다. 재시작 시 Import·provenance는 멱등 처리되고, 기존 평가가 있으면 재평가하지 않는다. 사실 원문·claim entailment·저작권·언어 자연스러움은 독립 검증되지 않아 사람 검토를 요구한다.
- `docs/operations/P5-CODEX-011-scheduled-task-templates.md`에 한국/일본/중국/미국 장마감 및 주간 금융 작업 초안과 휴장·조기 폐장 확인 지침을 기록했다. 제시된 시간은 운영 제안이며 공식 거래소 캘린더와 실제 Work 반복 스케줄 UI에서 검증된 시각이 아니다.

## 상태 판정

| 구성 | 실제 상태 |
|---|---|
| Trends 지역 | KR·US·JP·TW·HK·SG RSS 수집 코드는 유지. 현재 `collect_geo`는 호출형이며 worker의 매시간 스케줄은 구현되어 있지 않음. 이번 작업에서 RSS를 호출하지 않음. |
| GPT 예약 원고 생성 | 외부 계정 task 0개 생성. 로컬 Work의 예약 파일 생성도 실계정에서 검증하지 않음. 생성 Provider는 여전히 없음. |
| 로컬 scheduled Import | Mock HTTP로 검증한 단발 CLI 수신 경로 구현. 운영 원고는 실제 Import하지 않음. |
| 전문가 원고 생성·현지화 | 자동 생성 미연결. 현지화 대기는 기존대로 보존. |
| 품질·SEO·HTML | Import API에서 기존 결정론적 평가 호출. 결과는 독립 사실/권리 검증이 아님. 자동 승인 아님. |
| Blogger Auto | Fake-only. 실쓰기 adapter, Auto 활성화, publish_ready 전이는 없음. 실제 게시 URL 없음. |
| Dashboard | P5-UI-003 화면을 수정하지 않음. 예약 task의 실계정 상태 표시는 미구현. |

Auto 선호 설정은 라이브 게시 허가와 다르다. 운영 migration, 실제 Blogger 첫 게시, 자동 게시 시작은 수행하지 않았다. 운영 DB는 연결하지 않았고 migration도 적용하지 않았다. Blogger·AI API 호출 및 유료 API 호출은 0건이다. 실제 예약 작업 생성도 0건이다.

## 검증

- `scripts/verify.ps1`: Ruff 통과, mypy 통과 (39개 Python 소스), pytest **274 passed**, wheel build 검증, Dashboard ESLint·Next.js production build·TypeScript 통과, `git diff --check` 통과.
- 신규 scheduled import 및 content import 범위: 17 passed. TestClient는 테스트 DB 외부 강제 롤백을 사용했다. Inbox API는 `httpx.MockTransport`만 사용했다.
- 실제 ChatGPT Work task 실행/로컬 파일 작성: 미검증, task 미생성.
- 신규 브라우저 E2E: 미실행 (Dashboard UI 변경 없음). P5-CODEX-008의 이전 브라우저 검증은 이번 로컬 파일 수신 테스트를 대체하지 않는다.
- 운영 DB/Blogger/유료 AI/예약 계정 변경: 없음.

## 미완료 및 다음 운영 단계

1. 사용자가 ChatGPT Work 로컬 접근을 켜고 일회성으로 `.local/gpt-scheduled-import/ready`에 규격 파일 생성이 가능한지 확인한다. 이 파일 생성 방법을 실제 예약 반복으로 일반화할 수 있는지는 별도 확인한다.
2. 다섯 개 예약 작업은 위 문서 초안을 사용자가 검토·등록해야 한다. task 활성 상태와 실제 실행 데이터는 등록 후 UI에서 확인해야 한다.
3. Google Trends 6개 지역 매시간 스케줄, 8개 분야 자동 분류/우선도·시간당 후보 4건 제한을 별도 구현·검증해야 한다.
4. 무인 AI article generator가 없으므로 GPT 예약 작업 산출물 Import를 제외한 자동 원고 생성은 아직 불가능하다.
5. 운영 DB migration/백업·복원 승인, 실제 OAuth/write access 검증, Auto 제한·긴급 정지, 공개 HTML 검증 및 별도 운영 전환 승인 전까지 Blogger 실게시를 차단한다.

## 변경 파일

- `services/api/woori/content_imports.py`
- `services/api/woori/scheduled_import_inbox.py`
- `services/api/tests/test_content_imports.py`
- `services/api/tests/test_scheduled_import_inbox.py`
- `scripts/import-scheduled-content.py`
- `docs/schemas/woori-scheduled-content-import-1.0.schema.json`
- `docs/operations/P5-CODEX-011-scheduled-task-templates.md`
- `docs/development/P5-CODEX-011-results.json`

## Git

- 브랜치: `develop`
- 구현 커밋: `ffcf7c1`
- 결과 기록 커밋: `b18ac24` (후속 푸시 상태 기록은 git log 참조)
- 원격 푸시: `origin/develop` 성공 (`b18ac24`까지 확인)
- `main` 변경 금지, 기존 미추적 `.playwright-mcp/` 보존
