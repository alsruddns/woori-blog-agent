# P5-CODEX-031 — 한국어 Blogger 첫 공개 게시 차단 점검

- 작업 일시: 2026-10-29 (Asia/Seoul)
- 작업 ID: P5-CODEX-031
- 브랜치: `develop`
- 실행 범위: 게시 경로 읽기 점검, SQL 결함 수정, 격리 DB 회귀 검사
- 게시 요청: 수행하지 않음

## 결과 요약

상태: **BLOCKED** (정확한 원고·해시의 사람 검토/공개 승인 및 별도 Blogger 공개 쓰기 운영 승인이 없음)

실제 Blogger 공개 게시와 비공개 초안 생성은 모두 0건이다. 사용자 승인 없이 외부 쓰기를 실행하지 않았다. Auto는 OFF이며 운영 모드는 manual로 유지했다.

## 사전 상태

- Dashboard `127.0.0.1:3100`: HTTP 200
- FastAPI `127.0.0.1:8100` health 및 인증된 관리자 읽기 API: HTTP 200
- 작업 중 Dashboard, API, Worker 프로세스는 종료하거나 재시작하지 않았다.
- Research Worker heartbeat는 점검 시 fresh/running이었다. Publishing Worker heartbeat는 없었다.
- API 상태에서 Blogger OAuth A는 연결됨, Blogger 전체 scope 및 기존 4개 블로그 매핑 검증 기록이 확인됐다. 비밀 토큰 값은 조회·기록하지 않았다.
- `writes_enabled=false`, `publishing_enabled=false`; 공개 게시 operation 승인 이벤트 없음.
- FOMC 대상은 Import v7, content version `65133867-88d3-427a-bc24-b6994625eb38`, machine pass지만 `publish_ready=false`였다. Research Package는 사람 검토 대기 상태이고 권리·사람 편집·정확한 버전 공개 승인은 확인되지 않았다.
- 기존 publication approval 0건, live publication record 0건. 기존 Blogger 초안은 건드리지 않았다.

## 변경 전 문제와 변경 내용

게시 적격성 후보 조회 `_candidate()`의 SQL에 두 결함이 있었다. Rights review의 `JOIN LATERAL`에 `ON true`가 없었고, 같은 조회에서 참조하는 `source_ids` 및 `fact_ids`를 품질평가 lateral select가 반환하지 않았다. 이 때문에 실제 후보 조회가 SQL 오류로 중단될 수 있었다.

Rights review 조인을 유효한 `JOIN LATERAL ... ON true`로 수정하고 별칭을 명확히 했다. 품질평가 조회에 `source_ids`와 `fact_ids`를 추가했다. 알 수 없는 콘텐츠/블로그 ID로 후보 SQL의 구문과 스키마 호환성을 검사하는 격리 DB 회귀 테스트를 추가했다.

## 승인 및 게시 차단

현재 article 버전은 공개 게시 승인을 받을 수 있는 준비가 끝난 상태로 확인되지 않았다. 검토해야 할 구체적 대상은 위의 content version ID 및 P5-030에서 확인한 본문/메타데이터 digest `b084fe97c6777c854600e6255816869b39a017eaad36158e3a4dac78a46a90d5`다. 이 digest는 저장 버전 digest이며 publication approval이 요구하는 editorial body hash와 동일하다고 간주하지 않았다.

관리자는 원고 상세 화면에서 최신 원고와 HTML을 검토하고, 출처·근거 탭의 미확인 사항 및 권리 상태를 직접 확인한 뒤 편집 검토를 기록해야 한다. 게시 승인은 해당 최신 immutable editorial version과 실제 body hash에 결속되어야 한다. 공개 게시 operation의 별도 운영 승인 또한 필요하다. 이 사람 검토/승인을 에이전트가 대신 기록하지 않았다.

기존 규칙상 publication approval은 공개 쓰기를 활성화하지 않으며, 현재 공개 Blogger write gate도 닫혀 있다. 따라서 승인 전용 API를 임의로 호출하거나 job을 생성하지 않았다. 승인 완료 후에도 OAuth 재사용·원격 읽기·일일 제한을 다시 확인한 뒤 별도 승인 범위에서 게시해야 한다.

## 테스트 결과

- `services/api/tests/test_publications.py` 선택 검사: **3 passed** (candidate query parse, fail-closed eligibility, exact-version approval requirement)
- 첫 테스트 시도는 test-only `ADMIN_TOKEN` 미설정으로 실패했으며, 격리 DB만 사용하는 길이 제한 통과 테스트 값으로 재실행했다. 값은 개발 기록에 저장하지 않았다.
- 운영 DB 직접 연결 진단은 별도 실행환경에 DB 암호 설정이 없어 실패했다. 인증된 운영 API 읽기 상태를 대체 성공으로 과장하지 않았다.
- 실제 Blogger GET/POST, 초안 생성, 공개 발행: 수행 안 함
- Dashboard 기록 및 KST 게시 건수: 실제 게시가 없어 0건 변동
- 전체 테스트, lint, typecheck: 미실행

## 수정 파일

- `services/api/woori/publications.py`
- `services/api/tests/test_publications.py`
- `docs/development/P5-CODEX-031.md`

## 데이터 및 남은 문제

운영 DB에는 쓰기하지 않았다. 콘텐츠 원고·OAuth 연결·감사 기록·기존 Blogger 게시물/초안은 보존됐다. 테스트는 `.env.test`의 `woori_blog_agent_test`와 outer forced-rollback fixture를 사용했다.

미완료 항목:

1. 대상 본문에 대한 사람 편집·사실·권리 검토 및 정확한 버전/hash 결속 publication approval.
2. 별도 Blogger 공개 게시 operation 운영 승인.
3. 수정된 코드가 실행 중인 API/Worker에 적용됐는지 확인. 사용자 프로세스 재시작이 필요하나 이번 작업에서는 하지 않았다.
4. 공개 Worker heartbeat 부재 및 실제 Blogger 공개 게시 end-to-end 검증.

커밋 SHA: 후속 `git log`로 확인. 원격 push: 후속 기록.
