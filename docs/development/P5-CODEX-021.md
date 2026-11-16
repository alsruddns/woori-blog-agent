# P5-CODEX-021 — Fed 원고 Import 및 검증 연결

- 작업 ID: `P5-CODEX-021`
- 작업 일시: 2026-10-29 (Asia/Seoul)
- 브랜치: `develop`
- 변경 사유: 기존 Fed Research Package에서 실제 원고를 만들고 Import·품질·HTML 경로를 통과시킨다.
- 변경 전: schema 48, 기존 원고 버전 약 360개, Fed 패키지 1건(`evidence_collected_pending_human_review`), AI 무인 생성 Provider 없음, 한국어 원고 Import 없음. Import HTTP endpoint는 `woori_app`이 `schema_migrations`를 읽지 못해 503을 반환했다.
- 변경 목적: 수동 Codex 원고 1편을 기존 Import 계약으로 운영 DB에 연결하고, 권한을 늘리지 않고 앱 런타임의 schema 준비 검사를 보완한다.
- 변경 후: Fed 패키지 `c0b6f2b2-7a74-4b3f-a4f1-f4219c12321d`에 연결된 한국어 원고 1건을 Import했다. 불변 Import 원고 버전 및 기존 `content_versions` 연결 4건, 평가 5건이 생성되었다. 최신 원고 버전 4의 규칙 기반 품질 검사는 통과했으며 `publish_ready=false`와 사람 검토 대기를 유지한다.

## 근거 및 원고

- 자료: Federal Reserve Board, [Federal Reserve issues FOMC statement](https://www.federalreserve.gov/newsevents/pressreleases/monetary20261028a.htm), DB source `daf7a936-3b05-41d6-a5d2-d2f24511ac37`.
- 패키지에는 출처 1개, 저장된 사실 11개, 독립 출처 0개가 있다. 수집 본문이 1,000자에서 잘려 표결자 설명이 불완전하다. 잘린 내용과 표결자 이름은 사용하지 않았다.
- 사용 사실 범위: 연방기금금리 목표 범위 유지, 10대 2 표결, 경기·고용·물가 평가, 추가 정보가 향후 정책 판단에 필요하다는 성명. 분석·시사점은 사실과 구분하고 다음 금리 경로나 한국 시장 영향을 단정하지 않았다.
- 권리 상태는 `quotation_review_required`; 공식 성명 재사용 권리를 승인하지 않았다. 독립 확인, 의미상 사실 검토, 이용 권리, 편집 검토는 미완료다.
- 작성 경로: Codex 대화의 수동 작성 1건. `manual_codex_import`; underlying model identity is not exposed to the application. GPT 무인 예약 원고 0건.
- JSON 산출물: [P5-CODEX-021-article-ko.json](P5-CODEX-021-article-ko.json). 등록 한국어 블로그는 `https://trend-ko.blogspot.com` (Blog ID `3321654108096579717`); 이 메타데이터는 실제 게시 권한 확인을 뜻하지 않는다.

## Import 및 평가 증거

- 운영 Import ID: `b4c45d23-0c74-4b12-92fd-382633093afa`.
- 최신 Import 버전: `34eb61bb-6362-4e44-b59d-71ccbd863418` (버전 4), 콘텐츠 버전 링크: `38ac3a4b-2ce3-4920-86f0-e0706ff76c1d`.
- 최신 규칙 평가: `075c86d2-d073-4d3e-a52d-e7fe6a2a4b05`, machine checks 통과. source token은 HTML에서 제거됐다. `publish_ready=false`, 독립 출처 검증 false, generation ready false.
- SEO: 검색 설명과 제목 구조는 준비 상태. 제목/핵심 검색어·출처 연결·출처 공식성·최신성·Blogger 테마 메타데이터·사람 편집 검토는 review 대기다.
- Playwright 모바일 렌더: 390×844 viewport, `documentWidth=390`, article element 존재, H2 4개, 내부 source 표식 없음. 렌더 전용 safe HTML만 브라우저에 넣었다.
- 운영 DB Import API는 수정 전 프로세스 PID 25780에서 schema-migration 접근 권한 부족으로 503을 반환했다. 런타임 `woori_app` 권한을 확대하지 않고, 실제 브리지 테이블 존재 검사로 전환했다. 수정된 Python 경로를 운영 DB에 직접 호출해 Import와 평가를 저장했으며, HTTP 프로세스는 아직 재시작하지 않았다. 새 코드가 적용된 HTTP Worker 검증은 서비스 소유 터미널에서 안전한 정상 재시작 뒤에 수행해야 한다.
- 격리 테스트 DB `woori_blog_agent_test`에서 JSON 파일 검증 → Import API → content version → assessment → sanitized HTML 전체를 외부 호출 없이 실행하고 강제 롤백했다.

## OpenAI 예약 작업 및 파일 handoff

- OpenAI 공식 [Scheduled tasks 문서](https://learn.chatgpt.com/docs/automations)는 ChatGPT desktop에서 로컬 프로젝트/디렉터리 작업을 예약하고, 해당 파일이 필요한 동안 PC와 앱을 켜 두도록 안내한다. ChatGPT 웹의 예약 작업은 로컬 PC 폴더를 직접 쓸 수 없다. Codex CLI 및 IDE 확장은 Scheduled 관리 화면이 아니다.
- 현재 환경에서 새 예약 작업을 만들거나 실제 예약 실행·파일 생성을 검증하지 않았다. 이번 작업에서 ChatGPT UI를 통한 계정 변경은 수행하지 않았다. 무인 원고 생성 실적은 0건이다.
- 복사 가능한 작업 요청: “ChatGPT desktop Scheduled에서 이 저장소를 **local project**로 선택해 실행하세요. 매 회차 `.local/gpt-scheduled-import/research/`에 제공된 최신 Research Package JSON을 확인하고, 상태가 사람 검토 완료로 명시된 경우에만 해당 대상 언어로 처음부터 독립적으로 원고를 작성하세요. 출처 원문 span과 claim 연결, 권리·발표일·기준기간, 제목/검색 설명을 포함한 기존 `woori-scheduled-content-import/1.0` envelope를 출력하세요. 검증할 수 없는 사실·권리나 패키지 상태가 남아 있으면 파일을 만들지 말고 보류 사유를 보고하세요. 내보낼 때 `*.part`를 먼저 완성하고 같은 폴더에서 `*.ready.json`으로 원자적 이름 변경을 하세요. 경로는 `.local/gpt-scheduled-import/ready/`입니다. 생성 후 기존 로컬 importer를 `scripts/import-scheduled-content.py --operations --confirm-operations-import`로 실행해 Import와 기계 평가만 수행하세요. 사람 검토/권리 승인이나 Blogger 공개 게시를 표시하거나 실행하지 마세요. task 실행 ID를 확인할 수 없으면 실제 ID처럼 만들어 보고하지 마세요.”
- 수신 상태 디렉터리와 envelope 규격은 기존 [scheduled import runbook](../operations/P5-CODEX-011-scheduled-task-templates.md), [import schema](../schemas/woori-scheduled-content-import-1.0.schema.json), `services/api/woori/scheduled_import_inbox.py`를 재사용한다. CLI는 한 번 실행 시 최대 4개 파일을 처리하며 `awaiting_human_review`, `publish_ready=false`로 유지한다.

## Worker, Blogger 및 게시 상태

- Research Worker PID 46704는 시작 시각 기준 최신 heartbeat와 `running` 상태였고 진행 중 job은 0건이었다. 프로세스는 VS Code의 대화형 사용자 터미널이 소유하므로 코드 적용을 위해 종료하지 않았다. 따라서 실행 중 Worker에 on-disk 변경이 반영됐다고 주장하지 않는다.
- Blogger OAuth A `4839f8b9-69c8-4ce4-b1c1-5b71e96d5896`과 B는 DB에서 연결됨 및 `https://www.googleapis.com/auth/blogger` scope로 표시된다. Blogger API 접근/초안 생성/공개 게시 호출은 하지 않았으며 A 접근권한을 원격 검증하지 않았다. B는 보존했다.
- 전역 publication mode는 `manual`, `operations_auto_approved=false`, 긴급 중지는 false다. 공개 Blogger 게시 0건, 초안 생성 0건, Auto 활성화 0건. 승인 없는 원고를 실제 큐/게시 API로 보내지 않았다.
- 기존 Mock/fake Publisher 회귀 시나리오 테스트는 격리 DB에서 통과했다. 이것은 실제 Blogger publisher/queue 연결 또는 발행 성공 증거가 아니다. 현재 공개 게시 Worker가 실제 Blogger write 경로에 연결됐다고 확인할 근거는 없다.

## 변경 파일 및 검증

- 변경 파일: `services/api/woori/content_imports.py`, `services/api/woori/grounding.py`, `services/api/tests/test_content_imports.py`, `services/api/tests/test_live_research.py`, `docs/development/P5-CODEX-021-article-ko.json`, 이 기록.
- `test_content_imports.py`: 11 passed (운영 DB가 아닌 격리 DB; 강제 롤백).
- grounding 회귀 테스트: 2 passed. 내부 source ID를 수치/날짜 claim으로 오인하는 문제와 겹치는 영문 proper-name span 감지를 추가 검증했다.
- Mock Publisher fail-closed 회귀 테스트: 1 passed (격리 DB).
- Ruff 변경 파일 검사: passed. `git diff --check`: passed.
- 운영 감사: run `05d67548-0135-4b77-b21b-5cc0a7b709ae`; 작업 시작·완료와 Import 평가 이벤트 저장. 감사 요약의 잘못된 콘텐츠 버전 참조는 immutable 감사 이벤트를 수정하지 않고 후속 correction 이벤트로 바로잡았다.
- 구현 커밋: `b664fdd` (`fix : [P5-CODEX-021] connect Fed manuscript import checks`), `origin/develop` push 완료. 이 개발 기록의 최종 보고 항목은 후속 git history에서 확인한다.

## 남은 문제

- 원고 의미, 독립 출처, 권리, 최신성, 사람 편집 검토가 남아 있어 공개 게시 및 Auto가 차단된다.
- AI 무인 생성·예약 실행은 구성/검증되지 않았다. ChatGPT desktop에서 local project 예약 task를 운영자가 생성하고, 처음 몇 실행과 로컬 inbox 처리를 검증해야 한다.
- API PID 25780 및 연구 Worker PID 46704는 이전 코드로 계속 실행 중이다. API/Worker를 소유한 대화형 터미널에서 진행 작업이 없을 때 정상 재시작해야 변경된 schema readiness와 Worker 코드가 실제 실행된다.
- 실제 Blogger 접근권한, API 비용/quota 상태, 초안/공개 publish adapter 및 public queue 연계는 미검증/미완료다. OAuth write scope만으로 Blogger API 호출이 허가됐다고 간주하지 않았다.
- 커밋 해시 및 `origin/develop` push 상태는 후속 git 작업 결과를 기록한다.
