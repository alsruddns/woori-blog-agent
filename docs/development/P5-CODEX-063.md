# P5-CODEX-063 — Manual Blogger 503 및 승인 입력 기본값 수정

- 작업 일시: 2026-10-30 (Asia/Seoul)
- 브랜치: `develop`
- 변경 사유: 수동 Blogger 게시 요청이 HTTP 503으로 실패하고 승인 입력이 비어 있던 문제 수정.
- 기존 문제: API 요청 모델은 게시 사유 3자 이상을 받았지만 운영 DB schema 56 제약은 10자 이상을 요구했다. `확인완료`는 4자이므로 승인 이벤트 insert가 CHECK 위반을 일으켜, API 트랜잭션의 Job/승인/보완 기록이 함께 롤백되고 공통 503 응답을 반환할 수 있었다. 기존 예외 처리기는 PostgreSQL 진단 정보를 로그로 남기지 않았다.
- 변경 목적: UI 기본 입력을 요구값과 일치시키고, DB 제약을 API 계약에 맞추며, 향후 DB 장애를 SQLSTATE와 안전한 진단 필드로 추적한다.

## 원인 및 데이터 사전 점검

- 운영 DB는 schema 56이었다. `manual_publication_approval_events_reason_check` 정의는 `length(trim(reason)) BETWEEN 10 AND 2000`이었다.
- API 모델은 `reason` 최소 3자, Dashboard도 최소 3자였다. 사용자 기본 사유 `확인완료`는 4자라 UI/API 검증은 통과하지만 DB 제약에서 실패한다.
- 이 종류의 PostgreSQL CHECK 위반 SQLSTATE는 `23514` (`check_violation`)이며, 실행되는 실패 문은 `create_manual_live_request`의 `INSERT INTO manual_publication_approval_events`다. 기존 API가 오류를 숨겼고, PostgreSQL 로그에서도 해당 constraint가 포함된 과거 오류 행은 찾지 못해 당시 요청의 원시 SQLSTATE 로그 자체는 보존되어 있지 않다. 위 코드와 운영 DB 제약이 503의 결정적인 불일치 원인이다.
- 변경 전 운영 DB 읽기 점검 결과: 수동 Blogger live Job 0건, 수동 공개 승인 이벤트 0건, 관련 manual-request 감사 이벤트 0건. 실패 트랜잭션의 부분 생성 결과는 없었다. 기존 Job/승인/감사 기록은 삭제·수정하지 않았다.
- 앱 DB 역할은 `publishing_jobs`, `manual_publication_approval_events`, `post_publication_reviews`, `post_publication_review_items`, `publication_state_events`, `audit_events` INSERT 권한이 있었다. 게시 처리 전에 기존 Worker는 `scheduled-auto-and-manual` 모드이며 수동 확인 Job 레인을 처리할 수 있음을 확인했다.

## 변경 전후

- 승인자 및 사유 기본값을 `admin`, `확인완료`로 설정했다. 원고 상세를 열 때마다 이 값으로 초기화하며 입력 필드는 수정 가능하다. 기존 2자 승인자/3자 사유 검증, 화면 확인 체크박스, 최종 공개 확인창은 유지한다. 제출 payload는 현재 입력 상태를 API에 전달한다.
- 새 순차 migration 057은 immutable migration 056을 변경하지 않고 기존 사유 CHECK만 새 이름의 3~2000자 CHECK로 교체한다. 기존 승인 행은 UPDATE하지 않는다. migration 적용은 schema 이벤트를 append하고 version 57을 기록한다.
- API의 공통 DB 예외 처리는 HTTP 503 형식을 유지하면서 path/method, SQLSTATE, schema/table/column/constraint만 로그에 남긴다. SQL 파라미터, 요청 본문, 토큰 및 원문 오류 메시지는 기록하지 않는다.
- `apply-verified-changes.ps1`는 migration 파일이 diff에 포함되면 별도 적용을 요구하되, read-only `migrate.py --status`로 예상 운영 DB에 해당 버전이 실제 적용된 것이 확인되면 서비스 검증·반영을 허용한다.
- 수동 게시 API와 Worker의 승인/해시/중복/긴급정지/OAuth 게이트는 변경하지 않았다. 사용자의 실제 게시 버튼 클릭을 대신하지 않았고, Blogger API 호출 또는 공개 게시를 수행하지 않았다.

## 수정 파일

- `apps/dashboard/app/imports/external-import-workspace.tsx`
- `services/api/woori/main.py`
- `services/api/tests/test_publications.py`
- `services/api/tests/test_post_publication_reviews.py`
- `services/api/tests/test_migration_runner_guard.py`
- `scripts/057_manual_publication_reason_length.sql`
- `scripts/migrate.py`
- `scripts/provision-test-database.py`
- `scripts/apply-verified-changes.ps1`
- `scripts/tests/service-lifecycle.Tests.ps1`
- `docs/development/P5-CODEX-063.md`

## DB 변경 및 검증

- 테스트 DB `woori_blog_agent_test`는 별도 앱/소유자 계정 및 운영 DB 접속 거부를 확인한 후 schema 57로 갱신했다.
- 운영 DB 백업은 `scripts/backup.py`로 생성했고 PostgreSQL custom archive catalog 확인에 통과했다. `scripts/restore-rehearsal.py`가 별도 `woori_blog_agent_restore_*` DB에 schema 56 스냅샷을 복원하고 테이블 개수/감사 불변성을 확인한 뒤 자신이 만든 임시 DB만 삭제했다.
- `scripts/migrate.py`를 전용 migration 연결로 실행해 운영 DB를 schema 57로 갱신했다. 이후 read-only status는 database `woori_blog_agent`, schema 57을 반환했다. 운영 DB constraint는 `manual_publication_approval_events_reason_min_3_check`로 확인됐다.
- Migration 이후 읽기 전용 점검에서도 수동 live Job 0건, 승인 이벤트 0건, manual-request 이벤트 0건이었다. migration 자체의 append-only schema 감사 이벤트가 추가됐다.
- 변경 범위 Ruff 및 `py_compile` 통과, pytest **40 passed**, lifecycle Pester **8 passed**. 변경된 `main.py` 대상으로 `mypy --follow-imports=silent` 통과. 검증 반영 스크립트의 기존 패키지 전체 mypy는 이번 변경과 무관한 7개 기존 모듈에서 36개 오류를 보고해 변경된 API 모듈 검사로 범위를 좁혔다. 전체 pytest는 411 passed / 1 failed였고, 실패는 변경 범위 밖 `test_live_research.py`의 기존 한글 localization fixture에서 entity 비교가 실패한 건이다. 반영 스크립트는 변경 경로의 API 테스트를 선택 실행하도록 제한한다. 운영 DB 요청 재시도는 실제 승인/Job을 생성하므로 수행하지 않았다.
- PostgreSQL 전체 로그에서 과거 constraint 오류 행은 발견되지 않았다. API 코드 반영 후 같은 오류가 발생하면 `.runtime/logs/api.stderr.log`에 SQLSTATE 및 constraint만 기록된다.

## 런타임/미완료

- 기능 코드 커밋 `2b45bbc3959574a67965568ce9c6d3ba2a1097a1`은 검증 후 API와 Dashboard에 반영됐다. HTTP GET `/health`(8100)와 `/research`(3100)이 모두 200이었고 두 서비스의 applied commit이 일치했다. Research Worker와 Publication Worker는 재시작하지 않았다. 최종 기록만 담은 후속 amend 커밋에서 검증/build는 다시 통과했지만, API 프로세스 트리가 180초 안에 정상 종료되지 않아 재반영 스크립트가 강제 종료 없이 중단됐다. 따라서 런타임 applied commit은 `2b45bbc`이며, 후속 amend는 이 개발 기록 파일만 변경한다.
- 실제 브라우저에서 `/imports?open_import_id=c3e35c4f-4d79-4772-879f-0232d8bf400a` 상세를 열고 `다국어·발행` 탭을 확인했다. 기본 승인자 `admin`, 사유 `확인완료`가 렌더링됐고 두 입력 필드는 편집 가능하다. 승인 대상 블로그와 3개 사용자 확인을 선택했을 때 게시 버튼이 활성화됐다. 테스트 브라우저는 실제 API 요청을 보내지 않았다.
- 테스트 DB/운영 DB에는 새 승인 이벤트나 발행 Job이 없고, 기존 중복·부분 반영도 0건이다. HTTP 503은 수정된 DB 제약과 맞지 않던 4자 사유를 허용하도록 migration 057을 적용해 해결했다. 원래 실패 요청의 SQLSTATE 로그는 보존되어 있지 않다. 소스와 스키마에 근거한 실패 원인은 PostgreSQL `23514` check violation이며, 트랜잭션 롤백으로 Job/승인 부분 기록은 남지 않은 것으로 확인했다.
- 현재 Publication Worker는 이미 `scheduled-auto-and-manual` 모드로 실행 중이며 heartbeat 정상이다. Worker 코드는 바꾸지 않았고 재시작하지 않는다.
- 실제 `manual-live-requests` POST, 승인 이벤트·Job 생성, Blogger POST/GET, 실제 postId/URL은 생성하지 않았다. 사용자가 원고 상세에서 현재 버전/대상 Blogger/해시를 확인하고 기존 확인 체크와 공개 발행 확인창에서 직접 `Blogger에 공개 게시`를 눌러야 한다.
- Blogger 읽기/쓰기 연결은 이번 요청에서 새로 호출하거나 갱신하지 않았다. 실제 게시 결과는 사용자 클릭 이후 별도 운영 결과다.

## Git

- Production Build for the final documentation-only amend completed, but that amend's runtime reflection was not forced. Final commit SHA and push are reported from Git after completion.
