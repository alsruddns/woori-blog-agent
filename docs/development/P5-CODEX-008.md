# P5-CODEX-008 — Import·검토·Mock 게시 연결

## 목적과 범위

`woori-content-import/1.0` 외부 원고를 기존 편집 흐름과 이어, Import → 불변 버전 → 결정론적 품질/SEO/HTML 검사 → 사람의 근거·권리 검토 → Fake Publisher까지 로컬 테스트 DB에서 검증했다. 새 AI Provider는 추가하지 않았다. 원고를 받았다는 이유로 사실 검증이나 발행 허가가 완료되지는 않는다.

## 구현

- Import 목록을 `/manuscripts`에 대기 큐로 노출하고 `/imports`에서 원고 전체, 출처와 연결 주장, SEO 메타데이터를 확인한다. JSON 텍스트 붙여넣기와 150KB 제한의 `.json` 파일 불러오기를 지원한다.
- Migration 048은 Import의 각 불변 버전을 기존 `content_versions`에 연결하고, 같은 event group의 현지화 버전을 같은 `content_group`에 연결한다. 일반 manuscript 목록과 publisher가 같은 버전 ID를 참조할 수 있지만, Import 평가가 기존 fact registry/품질 평가를 대신하지 않으므로 정상 발행 후보는 계속 차단된다.
- 기존 Import 행을 덮어쓰지 않고 최초 버전과 변경 버전을 append-only 저장한다. 오래된 base version으로 저장하면 409 충돌로 막는다.
- 평가 실행은 기존 문장 품질 검사, SEO 검사, Markdown→Blogger HTML 변환 및 sanitizer를 재사용한다. 검사 결과·HTML·hash를 버전과 연결한다. 외부 출처 원문은 가져오거나 독립 검증하지 않으며, 결과는 문법/휴리스틱 평가로 표시된다.
- 편집 검토는 별도 감사 이벤트이며, 근거 문서 직접 확인·주장 대조·저작권 검토 확인 없이는 통과 기록을 허용하지 않는다. 이 기록으로 `generation_ready`/`publish_ready`가 바뀌지 않는다.
- 다국어 요청은 요청·취소 이벤트를 보존하며 provider 없음 상태에서 `awaiting_external_provider`로 남는다. 현지화 Import는 기존 부모 ID/event group을 확인하고 다른 언어를 요구한다. 같은 언어 중복 요청을 차단한다.
- Fake Publisher는 최신 기계 통과 평가와 편집 검토 통과를 요구하고, 멱등성 충돌을 막는다. 결과 제약과 감사 이력에 `simulation_only=true`, 외부 네트워크 0, 실제 블로그 변경 false, `publish_ready=false`를 고정한다.
- Next API proxy의 명시적 allowlist에 Import 작업을 추가했다. Import 및 Mock 요청을 실제 Blogger 경로로 라우팅하지 않는다.

## DB와 마이그레이션

Migration 047은 Import 평가, 편집 검토, 현지화 요청/취소, Mock 시뮬레이션을 별도 append-only 테이블로 저장한다. Migration 048은 외부 Import의 event group과 기존 manuscript content versions 간 불변 매핑을 만들고 기존 테스트 Import도 순차 backfill한다. 기존 Migration 045 Import 원본은 변경하지 않는다. 테스트 DB `woori_blog_agent_test`에만 001–048 순서가 적용되었으며 schema 48 및 테스트 앱 역할의 운영 DB CONNECT 거부를 확인했다.

작업 직후 운영 DB에 read-only 트랜잭션으로 조회한 결과는 schema 34, 043–046 미적용이었다. 운영 DB Migration 043–048은 적용하지 않았고 운영 콘텐츠/감사 기록 변경도 하지 않았다. 적용 전 백업, 격리 복원 리허설과 승인 절차는 [운영 Import 파이프라인 절차](../operations/P5-CODEX-008-import-pipeline.md)에 기록했다.

## 실제 브라우저 E2E

Next Dashboard `127.0.0.1:13100`과 FastAPI `127.0.0.1:18100`을 테스트 DB 연결로 실행했다. Playwright Chromium desktop/mobile 흐름은 잘못된 JSON 거부, 정상 Import, 중복 Import, 편집·새 버전, stale 충돌(API 회귀), 품질 검사, HTML 미리보기, 사람 검토, Fake Publisher, 현지화 요청·취소를 확인했다. 320, 390, 768, 1280px에서 문서 가로 overflow가 없었고, 외부 요청은 0건이었다.

브라우저 개발 환경에서는 잘못된 JSON의 예상 HTTP 422와 iframe sandbox가 Next 개발 스크립트를 차단한 예상 콘솔 메시지가 관측됐다. 예상 오류로 분류했고 그 외 콘솔 오류는 없었다. 스크린샷은 `docs/development/assets/P5-CODEX-008-import-{desktop,mobile}-{320,390,768,1280}.png`에 저장한다. 스크린샷은 개발 서버에서의 UI 검증이며 Blogger 테마의 실게시 결과를 증명하지 않는다.

## 미완료·경계

- 기존 소스가 제시한 주장과 본문 사실의 의미적 entailment, 공식 원문 내용, 권리, 자연스러움은 자동 판정하지 않는다. 사람 확인 전에는 독립 검증 완료로 간주하지 않는다.
- 새 AI provider가 없어 현지화 원고 생성은 미완료 대기다. Import는 제공한다.
- ChatGPT Scheduled Tasks의 로컬 전달은 구현하지 않았다. 수동 JSON/file Import가 대체 경로다.
- 실제 Blogger 초안/게시/수정/삭제 및 Auto 활성화는 0건이다.
- 운영 migration은 별도 승인과 호환성 검토 전까지 수행하지 않는다. 현재 schema 34에서는 Import API가 migration 의존성으로 fail-closed다.

## 검증

`scripts/verify.ps1` 통과: Ruff, mypy(38개 Python 모듈), pytest(266개), 격리 wheel build, ESLint, Next production build, TypeScript 및 `git diff --check`. Import 관련 독립 pytest는 9개 통과했다. JSON Schema 예시 2개도 API Pydantic 계약으로 검사했다. `scripts/verify-secrets.py`의 테스트 모드 HTTP 검사도 통과했다.

브라우저 검증은 Playwright desktop/mobile 2개 프로젝트에서 각각 통과했다. 잘못된 JSON 거부, 파일 Import, 중복 방지, 새 버전 편집, 평가·미리보기, 사람 검토 기록, Fake Publisher, 현지화 요청/취소를 실행했고 320/390/768/1280px에서 overflow가 없었다. 전체 검증 결과와 Git 식별자는 별도 [P5-CODEX-008 결과 JSON](P5-CODEX-008-results.json)에 기록한다.
