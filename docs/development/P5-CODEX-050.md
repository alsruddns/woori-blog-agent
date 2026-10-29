# P5-CODEX-050 — 검증 가능한 신규 원고로 Blogger 자동 게시 완성

- 작업 일시: 2026-10-29 (KST)
- 작업 브랜치: `develop`
- 변경 사유: 사실에 기반해 작성한 한국어 원고의 금액·단위 표기가 영어 원문과 달라 기계 검증에서 오탐으로 차단되었고, ONS 출처 도메인·발표일이 품질 평가기로 전달되지 않았다.
- 기존 상태: 신규 ONS 원고는 운영 DB에 Import됐지만 `awaiting_human_review`; 기존 평가의 `machine_passed=false`, `publish_ready=false`. 예약 Auto는 활성 상태이나 첫 공개 게시 승인은 0건이고 실제 게시/작업은 0건이다.
- 변경 목적: 확인된 사실의 의미를 바꾸지 않고 GBP 금액 단위만 정규화해 비교하며, 접근 가능한 ONS 공식 출처의 발표일과 공식 출처 식별을 평가에 연결한다. 권리 검증과 사실 검증은 별도 상태로 유지한다.

## 신규 원고 및 출처

- 주제: 영국 공공재정 2026년 9월 통계
- 공식 자료: [ONS Public sector finances, UK: September 2026](https://www.ons.gov.uk/economy/governmentpublicsectorandtaxes/publicsectorfinance/bulletins/publicsectorfinances/september2026)
- 발행일: 2026-10-21
- 사용조건: ONS 페이지의 OGL v3.0 고지 및 ONS 이용 약관을 확인했다. 글은 독립적으로 바꾸어 썼고 ONS 표·이미지·장문 문구를 복제하지 않았다. [ONS terms](https://www.ons.gov.uk/help/terms-conditions)
- 원문/약관 수집: allowlist를 거친 6회 요청으로 제한을 지켰다. 본문 해시 `c54ecfb394bb31b77225a0a52740d25c439d787a295c6bd7735c68517b2194f6`; 재호출은 provider quota 때문에 하지 않았다.
- 중복 조회: 한국어 Blogger 및 운영 Import 이력 확인 결과 `not_found`; 원격 Blogger 읽기 완료. 게시된 동일 사건은 확인되지 않았다.
- 운영 Import ID: `c3e35c4f-4d79-4772-879f-0232d8bf400a`
- Import version ID: `9ea000f5-104c-4422-a58f-77acaf698b36` (version 1)
- Content version ID: `7dc970ee-880d-49da-967a-5813f71dbbea`
- 버전 SHA-256: `9202d726dbc0b065eebf520ec777af244f71456c65e0e35afe17a57ca84dad20`
- 본문 SHA-256: `15cad1bfe41f390e20862fdaa5c3eeafb31bdb2c5a55ce62ac71cf55797d9034`
- 기존 일본어 Import `9bd1706b-5e0a-4cb4-a7fd-d4949b9ecad7`은 재평가하거나 변경하지 않았다.

## 구현 변경

- ONS 원문·약관을 고정 경로와 공통 외부 요청 정책으로만 읽고, 페이지/약관 근거가 함께 확인될 때만 텍스트 OGL 재사용을 기록한다.
- 공개 통계에서 핵심 수치·기간을 source-linked claims로 남기고, 영어/한국어 숫자 단위의 의미 동등성을 수치 검사에서 비교한다. 이 검사는 의미적 주장 검토를 대체하지 않는다.
- `www.ons.gov.uk`를 정확한 공식 출처 도메인 registry에 추가하고, 실제 캡처 감사 이벤트의 발표일을 Content Import 평가 근거에 전달한다.
- 글의 권리 상태와 핵심 사실 검토를 독립적으로 유지한다. 사람 검토/출판 승인 생성, `publish_ready` 변경, Blogger 쓰기는 하지 않았다.

## 수정 파일

- `services/api/woori/external_policy.py`
- `services/api/woori/scheduled_source_evidence.py`
- `services/api/woori/scheduled_auto_verification.py`
- `services/api/woori/grounding.py`
- `services/api/woori/content_imports.py`
- `services/api/woori/topics.py`
- `services/api/tests/test_scheduled_source_evidence.py`
- `services/api/tests/test_scheduled_auto_verification.py`
- `services/api/tests/test_grounding_gbp.py`
- `docs/operations/zero-cost-policy.md`
- `docs/development/P5-CODEX-050.md`

## 검증 및 운영 결과

- Ruff: 변경된 API 코드와 관련 테스트 통과.
- 집중 pytest: `test_grounding_gbp.py`, `test_scheduled_auto_verification.py`, `test_scheduled_source_evidence.py`, `test_content_imports.py` — 35 passed.
- 관련 grounding 선택 테스트: 8 passed, 56 deselected.
- `test_live_research.py`의 더 넓은 실행에서는 86 passed, 1 failed. 실패는 이 작업에서 수정한 코드가 아닌 `test_fact_ledger_and_localization_separate_source_language_and_expression`의 glossary/entity localization assertion이었다. 전체 테스트가 통과했다고 주장하지 않는다.
- 운영 API read-only 조회: ONS 원문 HTTP 200, 권리 증거 `allowed`; Import 1건 확인.
- 운영 Import의 마지막 평가(개발 변경이 실행 API에 적용되기 전 생성): machine pass 실패, 사람 검토 필요. 누락된 출처 marker 및 OBR 영문 정식 명칭 항목을 확인했다. 변경 후 재평가를 운영 API에서 실행하지 않았다.
- 자동 적격 원고: 0건. 예약 Publishing Job: 0건. Blogger 공개 게시: 0건. postId/URL 없음.
- 최신 API 프로세스는 사용자 소유 실행 프로세스이므로 이 변경을 적용하려고 종료/재시작하지 않았다. 다음 정상 API 재시작 이후 새 공식 출처·발행일·수치 정규화 코드가 실행된다.
- 예약 Auto 첫 공개 승인 이벤트가 존재하지 않는다. 따라서 실제 게시 호출은 하지 않았다.
- 기존 평가를 반복 생성하지 않았으며, 첫/수정 일본어 실패 파일은 보존했다.

## 미완료 및 다음 조치

1. API를 프로젝트의 안전한 정상 재시작 절차로 최신 develop 코드에 반영한다.
2. 저장된 Import 내용을 검토해 인용 marker와 OBR 정식 영문 기관명을 보완할 새 immutable version을 만든 뒤 새 버전만 평가한다.
3. 사람의 사실·편집·권리 검토와 첫 공개 게시 승인을 실제 승인 경로에서 기록한다. 자동화 코드가 이를 대체하지 않는다.
4. 승인이 기록되어도 실제 Blogger 쓰기는 별도 승인 정책과 게시 한도 확인 후 실행한다.

커밋 해시: 후속 `git log`에 기록 (작업 중)
원격 푸시: 작업 중
