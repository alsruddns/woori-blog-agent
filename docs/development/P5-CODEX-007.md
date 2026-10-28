# P5-CODEX-007 — 국가별 대상 추천 및 수동 다국어 발행 요청

## 작업 목적

기존 전문가 칼럼·Research Package·품질 검사·게시 모드를 재사용해 원고 상세와 발행 후보에서 추가 언어/블로그 요청을 기록할 수 있게 한다. 국가 코드를 독자 관련성의 증거로 오인하지 않고, 생성 Provider 부재 시 실제 원고 생성 또는 게시 성공으로 표시하지 않는다.

## 최초 상태

- 기준 브랜치: `develop`
- 기준 커밋: `2c69f5f` (P5-CODEX-006 이후)
- 기존 실행 정책: Qwen3/llama.cpp 제거 완료, 운영 원고 생성 Provider 연결 없음, Blogger live writes 차단
- 기존 미추적 `.playwright-mcp/`는 보존
- 운영 DB migration은 실행하지 않음

## 구현

- 국가 기반 참고 제안은 KR→ko, US→en, JP→ja, 중국 본토 CN→zh-CN으로 제한했다. TW/HK/SG 및 미지 지역은 자동 언어 지정을 하지 않고 편집자 판단을 요구한다.
- 원고 상세의 **다른 언어로 발행** 영역에서 활성 언어·블로그 연결, 기존 현지화, 기존 게시글, 게시 모드를 보여주고 사용자가 선택한 언어만 요청하도록 했다. 발행 후보/게시 작업 목록에서도 동일한 원고 상세로 이동할 수 있다.
- 요청에는 원본 평가/버전/본문 해시, 요청자, 지역, 대상 블로그, 시점의 Manual/Auto 모드, 요청별 자동 게시 의사, 차단 사유를 보존한다. 대상별 중복 요청은 DB 고유 제약과 트랜잭션 잠금으로 방지한다.
- 요청자는 대기 작업을 취소할 수 있으며 취소 사유와 요청자는 불변 이벤트로 저장된다. 취소된 기록은 삭제하지 않고 새 요청 키로 재요청할 수 있다.
- 선택 언어마다 독자 가치/대상 이유 입력을 요구한다. 선택·비선택·기존 현지화·이미 게시됨·활성 블로그 매핑 부재의 결정 근거를 append-only 요청/감사 기록에 남긴다.
- migration 043은 요청 및 불변 이벤트 테이블을 추가한다. migration 044는 이력 불변성은 유지하면서 취소된 요청의 재요청을 허용하고 원본 content version/localization 연결을 DB에서도 확인한다. 두 마이그레이션을 격리 테스트 DB `woori_blog_agent_test`에만 적용해 schema 44를 확인했다. 운영 DB에는 적용하지 않았다.
- 평가 전용 자료, 미검증 출처 계보, 실패 품질, 기존 번역/원고는 차단하거나 수동 검토로 남긴다. 사람이 요청별 Auto 의사를 선택하더라도 전역/블로그 모드, `publish_ready`, Blogger live-write 잠금은 변경하지 않는다.
- 현재 생성 Provider가 연결되어 있지 않아 적격 요청도 `awaiting_provider`이며, 이 작업은 AI 생성·현지화·실제 Blogger API 호출을 하지 않는다.

## 수정 파일

- `scripts/043_localized_publication_requests.sql`
- `scripts/migrate.py`, `scripts/provision-test-database.py`
- `services/api/woori/localized_publications.py`, `main.py`, `publications.py`
- `services/api/tests/test_localized_publications.py`
- Dashboard API proxy, manuscript workspace, publication manager, responsive styles
- `docs/operations/multilingual-publication.md`
- `docs/development/P5-CODEX-007-results.json`

## 검증

- Test DB provisioner: schema 44 적용, test app/owner 계정 검증, 운영 DB에 대한 test app CONNECT 거부 확인
- API 회귀 테스트: 9 passed
- Ruff: 통과
- mypy 변경 모듈: 통과
- Dashboard ESLint: 통과
- Dashboard TypeScript: 통과
- 전체 `scripts/verify.ps1`: 257 Python tests, Ruff, 36개 API 모듈 mypy, wheel, ESLint, production build, TypeScript 통과
- 실제 UI 브라우저 검증: 이번 단계에서는 수행하지 않음
- Blogger API 쓰기 / AI Provider 호출 / Auto 운영 활성화: 0건

## 미완료 및 운영 제약

- 생성 Provider가 없어 새 언어 원고 생성은 대기 상태이며, 모형 생성 성공을 주장하지 않는다.
- 운영 DB migration 043은 적용 전이다.
- Blogger 자동 발행 잠금과 `publish_ready=false` 정책은 유지했다.
- 화면의 선택 기록은 요청 감사 기록이며, 작성자 본인 계정 신원을 검증했다는 뜻은 아니다.
- 기존에 생성·게시된 다른 언어 원고는 자동 수정/덮어쓰기 하지 않는다.

## Git

- 구현 커밋 `9b2053d`; `origin/develop` 푸시 성공
- 이 최종 Git 결과를 개발 기록에 반영한 후속 기록 커밋은 최종 보고에 명시

## P5-CODEX-007 통합 확장 추가 기록 (2026-10-28)

### 상태와 목적

원래 007의 다국어 발행 요청 기능을 재사용하고, Scheduled Tasks/Codex 산출물을 전달할 공식 자동 경로가 검증되지 않은 상황의 수동 Import를 추가했다. 공식 문서상 ChatGPT 예약 작업은 지원 앱/이벤트를 사용하며 프로젝트 안에 생성한 작업은 업로드된 프로젝트 파일에 접근하지 못한다. 해당 문서에 이 애플리케이션으로의 범용 webhook 또는 로컬 API 전달 경로는 명시되지 않아 자동 전달을 구현하지 않았다. 수동 JSON Import만 지원 가능한 연결로 표시한다.

### 구현

- 버전 고정 `woori-content-import/1.0` 스키마와 엄격한 API Pydantic 검증, `/imports` 대시보드 및 중복 제출 방지 Import API를 추가했다.
- 카테고리 8종(economy, finance, stocks, crypto, technology, semiconductors, artificial-intelligence, policy)과 중복 검토 그룹을 데이터형 registry로 정리했다. Migration 045는 기존 카테고리를 삭제·수정하지 않고 누락된 표준 slug만 추가한다.
- Migration 046에 사람 검토형 트렌드-분야 분류 이력과 감사 이벤트를 추가하고 `/sources` 목록·상세에서 기록할 수 있게 했다. 분류는 append-only이며 주제 그룹 병합, 원고 생성 또는 발행을 자동 승인하지 않는다.
- Import는 HTTPS 원문 URL, 권리 표시, 출처 매니페스트, claim-source 관계, 타임존 포함 확인 시각, SEO 필드, 언어별 독자 관련성 및 Trends 라벨을 검증한다. 원문 URL은 fetch하지 않는다. 원시 HTML 및 내부 Workflow 표식은 거부한다.
- 기록은 append-only `external_content_imports`/`external_content_import_events`에 저장하며 같은 외부 ID·동일 본문 재전송은 기존 레코드를 돌려준다. 변경 내용 재전송은 409이다.
- 모든 Import 상태는 DB 제약으로 `awaiting_human_review`, `generation_ready=false`, `publish_ready=false`에 고정했다. 사용자 본문은 검토 목록에만 저장되며 기존 Manuscript/quality/evidence/publisher 경로에 자동 승격되지 않는다.
- Migration 045/046은 개발/운영 migration runner에 등록했고 테스트 DB provisioner에도 추가했지만, 실행한 것은 테스트 전용 DB로만 한정한다. 운영 DB에 migration을 적용하지 않았다.

### 미완료 경계

생산 AI Provider 및 공식 GPT/Codex 자동 전달이 없어 AI 생성·자동 현지화는 계속 불가능하다. Import 레코드를 기존 `content_versions` 및 별도 평가 DB 품질 레코드로 승격하는 검토·검증 브리지는 구현되지 않았다. 이를 현재 발행 가능 파이프라인과 연결했다고 주장하지 않는다. 따라서 007 전체 end-to-end(수집→검증→원고 생성→4개 언어 현지화→게시)는 부분 완료다. Auto 요청/모드는 기존 설정만 표시하며 실제 Auto 활성화나 실제 Blogger 쓰기는 없다.

### 최종 통합 검증 (2026-10-28)

- `scripts/verify.ps1` 최종 실행: pytest 263건, Ruff, mypy(38개 API 소스 파일), wheel, Dashboard ESLint·TypeScript·production build, `git diff --check` 모두 통과했다.
- 전체 테스트에서 트렌드 상세 조회 mock이 새 선택 분류 테이블의 존재 확인 쿼리를 응답하지 않는 문제가 드러나 fixture를 보완했다. 재실행한 전체 검증은 통과했다.
- 테스트 전용 DB는 schema 46까지 준비했고 테스트 앱 계정의 운영 DB CONNECT 거부를 확인했다. Migration 045/046은 운영 DB에 적용하지 않았다.
- 브라우저 E2E는 이번 변경에서 실행하지 않았다. Dashboard production build와 타입/린트 검사만 완료했다.
- 운영 DB, 기존 원고, 감사 이력, Blogger, 외부 예약 작업 및 유료 AI API는 변경·호출하지 않았다.
- 구현 커밋 `76b03f5`를 `origin/develop`에 푸시했다. main은 변경하지 않았고 `.playwright-mcp/`는 미추적 상태 그대로 보존했다.
