# P5-CODEX-018 — 공급·OAuth·Publisher 통합 상태

- 작업 ID: P5-CODEX-018
- 작업 일시: 2026-10-29 (Asia/Seoul)
- 작업 브랜치: `develop`, 시작 커밋 `71dabfa`
- 변경 사유: P5-CODEX-017의 Auto 설정 요청, 쓰기 OAuth 연결, Publisher queue 연동 및 생성 공급 미완료를 재검토하고 안전하게 진행 가능한 부분을 처리.
- 작업 상태: 부분 완료. 실제 Publisher queue 연결, 운영 Import, AI 무인 생성 및 실제 게시 E2E는 미완료.

## 기존 문제와 목적

Auto 설정 API가 실제 Publisher와 운영 승인이 없는 상태에서도 `configured_mode=auto`를 저장할 수 있었고 Dashboard도 이를 설정 요청으로 표현했다. 실제 queue Worker는 fake simulation만 소비한다. 실 Publisher adapter와 초안 read-back 검증 코드는 존재하지만 queue/Worker에는 연결되지 않았다. 운영 article-generation Provider는 없고 운영 Research Package 수도 0이었다.

P5-CODEX-015~017 문서, schema 48 운영 DB, API/Worker 경로, OAuth scope 및 blog mapping을 확인했다. 기존 콘텐츠 360개, 기존 게시물, OAuth 매핑을 변경하거나 제거하지 않았다.

## 변경 전 / 변경 후

- 변경 전: 미준비 Publisher 상태에서도 Auto 설정을 DB에 저장할 수 있었음. 운영 화면은 Auto가 실행 차단임을 표시했으나 설정 요청은 가능했음.
- 변경 후: Auto 선택지를 Dashboard에서 비활성화하고 API는 Auto 설정 요청을 HTTP 409로 거절한다. 차단 코드는 `auto_publication_unavailable`이며 `live_blogger_publisher_not_enabled`, `operations_auto_approval_required` 사유를 반환한다. 설정 DB 쓰기 전 차단됨.
- 실제 Publisher queue 연결 및 공개 Auto 활성화: 변경 없음. live Blogger write는 계속 disabled.
- OAuth blog mapping: 변경 없음.

## 운영 상태 확인

읽기 전용 DB 확인 시 `woori_blog_agent`, schema 48, content versions 360, audit events 1,545, Research Package 0, publishing records 0이었다. 기존 Blogger live-test 원장은 4건이지만 모두 `live_test_draft` preview 상태이고 Blogger post ID가 없는 항목이므로 실제 초안 생성으로 집계하지 않는다.

운영 정책상 허용된 Blogger 읽기 검증으로 연결된 `blogger` write scope OAuth 두 건을 각각 조회했다. 두 연결 모두 API가 반환한 접근 가능한 블로그 목록에서 등록된 4개 블로그(en, ja, ko, zh-CN)를 확인했다. Google 계정 신원은 API 응답에서 검증되지 않았다. 따라서 어느 연결도 선택하거나 blog mapping을 바꾸지 않았다. 이 요청에서 실제 Blogger POST/게시물 생성은 0건이다. 읽기 검증 결과는 감사 이벤트로 추가되었다.

Trends 최근 24시간 DB 관측량은 HK 30, JP 30, KR 30, SG 30, TW 20, US 20으로 총 160건이었다. Research Package 생성은 0건. 마지막 DB 관측 시각상 Research Worker heartbeat는 45초 freshness 기준에 들지 않아 정상 실행 상태로 보고하지 않는다.

## 자동 원고·원고 검증

- AI 무인 원고 자동 생성: 0건. 프로젝트 production generation Provider는 연결되어 있지 않다.
- P5-CODEX-017의 수동 Codex 대화 원고: 1건 기록. 이번 작업에서 운영 Import, Research Package 연결, 새 quality assessment, HTML preview는 수행하지 않았다.
- 원고 Import: 0건. Research Package가 없고 P5-CODEX-017의 출처 권리/독립 편집 검토가 미완료다. 당시 보류했던 BEA September 자료 발표 시각도 경과했으므로 원고 수치와 최신성을 재검토해야 한다.
- 예약 작업: 기존 `.local/gpt-scheduled-import` 수신 Worker와 P5-CODEX-012 지시문/JSON 규칙을 재사용할 수 있다. ChatGPT Work의 로컬 폴더 실행은 앱 rollout 및 계정 권한에 달려 있어 현재 계정의 task scheduling, 실제 파일 전달을 이 작업에서 확인하지 못했다. 일반 ChatGPT Scheduled task는 프로젝트 파일을 읽는다고 가정하지 않는다.

OpenAI 공식 안내: [ChatGPT Work and Codex](https://help.openai.com/en/articles/20001275-chatgpt-work-and-codex), [Scheduled tasks](https://help.openai.com/en/articles/10291617-scheduled-tasks-in-chatgpt), [Agent Security and local work sync](https://help.openai.com/en/articles/20001548-agent-security-and-local-work-sync).

## Blogger Publisher 및 남은 사람 조치

- 실제 queue Worker 연결: 미완료. `publication_worker.tick()`은 `simulation_only AND adapter_type='fake'`만 가져온다.
- Blogger write OAuth: scope 존재와 네 블로그 접근은 확인했으나 두 연결이 같은 권한/접근을 보이고 API 식별 신원은 확인되지 않는다. 운영자는 OAuth 연결 관리에서 본인 의도 계정을 확인한 뒤 어느 연결을 공통 매핑할지 명시적으로 승인해야 한다.
- 실제 비공개 초안: 0건. blog mapping 변경 전이며 draft endpoint에는 기존 단일 테스트 사본 제한도 있다. 원고용 초안은 exact content와 권리/사실 검토가 끝난 뒤 별도 승인 및 재검증이 필요하다.
- 실제 공개 게시/URL/게시 후 검사: 0건.
- Auto: 운영 DB global mode는 `manual`; live Auto/write disabled. 이번 변경으로 새 Auto mode 저장도 차단.
- 비용: 추가 유료 AI 호출 0. Blogger 외부 호출은 두 OAuth 연결의 읽기 전용 blog-access 확인이며 POST/PUT/PATCH/DELETE 호출 0. Cloud project의 현재 Blogger quota/Billing 값은 확인하지 않았다.

## 수정 파일 및 검증

- `services/api/woori/publications.py`: Publisher 및 운영 승인 미충족 시 Auto 설정 API를 fail-closed 처리.
- `services/api/tests/test_publications.py`: Auto 거절 응답과 DB 미쓰기 회귀 테스트 추가.
- `apps/dashboard/app/publishing/publication-manager.tsx`: Publisher/승인 전 Auto 선택 비활성화.
- `docs/development/P5-CODEX-018.md`: 본 기록.
- `python -m pytest services/api/tests/test_publications.py services/api/tests/test_publication_modes.py services/api/tests/test_blogger_live_policy.py -q`: 39 passed.
- `python -m ruff check services/api/woori/publications.py services/api/tests/test_publications.py`: 통과.
- `npm --prefix apps/dashboard run lint`: 통과.
- `npm --prefix apps/dashboard run typecheck`: 통과.
- `git diff --check`: 통과.
- 전체 통합 E2E 및 전체 `scripts/verify.ps1`: 미실행.

## 남은 문제

1. 운영자가 두 write OAuth 연결 중 사용할 계정을 확인하고 공통 매핑을 명시적으로 승인해야 한다. 현재 접근 검증 기록은 5분 만료이므로 매핑 직전에 재검증해야 한다.
2. Google Cloud Blogger quota/Billing 상태 및 게시 호출 범위 확인이 필요하다.
3. 공식 Research Package/권리 검토를 만든 뒤 기존 한국어 원고를 최신 공식 자료로 수정·재검토해야 한다.
4. 공식 AI 자동 생성이 없으면 로컬 inbox에 JSON을 사람이 전달하는 방식만 가능하다. Work local scheduled task 사용 가능 여부는 사용자 앱/계정 설정 검증이 필요하다.
5. Publisher queue/Worker의 실제 API 통합, 초안 persistence/reconciliation, exact approval, public publish, Auto gating/heartbeat/recovery 및 end-to-end 증거는 남아 있다.

자기 참조 커밋 해시: 본 파일을 포함한 커밋은 `git log -- docs/development/P5-CODEX-018.md`로 확인한다. P5-CODEX-015~017 문서와 `docs/operations/google-oauth.md`, `docs/operations/P5-CODEX-012-scheduled-work-recipes.md`, `docs/operations/zero-cost-policy.md`가 관련 기록이다.
