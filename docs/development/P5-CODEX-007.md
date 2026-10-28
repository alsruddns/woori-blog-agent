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

- 커밋 및 원격 푸시 결과: 아래 최종 결과 JSON 및 최종 보고 참조
