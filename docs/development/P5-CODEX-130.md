# P5-CODEX-130 — Publication Worker PostgreSQL 권한 오류 긴급 복구

- 작업 ID: `P5-CODEX-130`
- 작업 일시: 2026-11-04 (Asia/Seoul)
- 브랜치: `develop`
- 시작 HEAD: `57d6cb9b701f18ae1cd9d331f18af51690a4b5f8`
- 완료 코드 HEAD(개발 기록 추가 전): `5826b59bbb1944ed4a954745ffe4e6270c256217`
- 운영 DB: `woori_blog_agent`, schema version `89`
- 관련 기록: `docs/development/P5-CODEX-129.md`
- 감사: 시작 이벤트 `342409`; 완료 이벤트는 이 기록과 같은 작업 ID로 추가됨.

## 변경 사유와 기존 상태

P129 코드 운영 반영 이후 Publication Worker가 `InsufficientPrivilege` / SQLSTATE `42501`로 degraded 상태가 됐다. 운영 PostgreSQL 로그에서 실제 실패 SQL과 객체를 확인하고, Worker가 immutable Import 행에 잠금을 걸 때 요구 권한을 잘못 사용하지 않도록 고쳤다. 운영 데이터, OAuth, 큐 및 발행 설정은 보존했다.

작업 시작 시 API와 Publication Worker는 이전 반영본 `67e9218c1fecafffab079da4e960fbd979642dbb`을 사용했다. Dashboard는 `6e7541524c421c23d2fcdd1011a32660474cb83b`, Research Worker도 `67e9218c1fecafffab079da4e960fbd979642dbb`였다. Publication Worker heartbeat는 SQL 권한 오류로 degraded였다. 실행 중인 Blogger 요청이나 running Publishing Job은 없었다.

작업 트리의 추적 파일은 깨끗했고, 기존 stash `stash@{0}`와 미추적 테스트·화면 캡처 파일은 모두 보존했다.

## 원인

- PostgreSQL 로그의 실패 객체: `public.external_content_imports`
- 실패 SQL: `SELECT id FROM external_content_imports WHERE id=$1 FOR UPDATE`
- 연결 role: `woori_app`
- 테이블 owner: `woori_owner`
- schema `USAGE` 및 테이블 `SELECT`: 허용
- 테이블 `UPDATE`: 거부
- Migration 045는 이 immutable 테이블에 `SELECT, INSERT`만 부여한다. 이후 Migration 089까지 권한 변경은 없었다.
- PostgreSQL은 행을 수정하지 않는 `SELECT ... FOR UPDATE`에도 `UPDATE` 권한을 요구한다. 따라서 이 오류는 누락된 운영 GRANT가 아니라 immutable 테이블에서 UPDATE 권한을 요구한 잠금 방식의 결함이다.
- P129의 `prepare_trends_publishable_version` 경로가 버전 체인을 만들 때 `_create_import_version`을 호출했고, 해당 조회가 불필요한 `FOR UPDATE`를 사용했다.

Worker role에 UPDATE를 추가하면 불변성 경계를 약화시키므로 권한을 확대하지 않았다.

## 수정 내용

`_create_import_version`은 새 `_lock_import_version_chain` helper로 Import ID별 transaction-scoped PostgreSQL advisory lock을 획득한 뒤 일반 SELECT를 수행한다. 동시 버전 생성은 직렬화하면서 immutable 테이블에 대한 UPDATE 권한을 요구하지 않는다. 트랜잭션 종료 시 잠금은 자동 해제된다.

검증된 반영 스크립트는 `content_imports.py` 변경 시 API, Research Worker, Publication Worker를 반영 대상으로 식별한다. 프런트엔드 코드는 바뀌지 않아 Dashboard 재빌드는 필요하지 않았다. P128부터 이어진 기존 테스트 fixture의 `general-news` 카테고리와 JSON Schema enum 불일치도 같은 검증 실행에서 확인되어, schema enum과 테스트 기대값을 기존 카테고리 계약에 맞췄다.

## 변경 파일

- `services/api/woori/content_imports.py`: immutable Import 행의 `FOR UPDATE`를 advisory transaction lock과 일반 SELECT로 변경.
- `services/api/tests/test_content_imports.py`: UPDATE 권한 없이 잠금·조회되는 동작 및 SQL 형태 검증; 기존 fixture/schema 카테고리 정합성 수정.
- `docs/schemas/woori-content-import-1.0.schema.json`: 기존 `general-news` 카테고리를 허용 enum에 추가.
- `scripts/apply-verified-changes.ps1`: 이 모듈 변경의 반영 서비스 대상을 명시.
- `docs/development/P5-CODEX-130.md`: 원인, 수정, 테스트 및 운영 반영 기록.

## DB 권한 및 데이터 보호

권한 변경 전후 모두 `woori_app`은 schema `USAGE=true`, `external_content_imports SELECT=true`, `UPDATE=false`였다. **GRANT/REVOKE는 실행하지 않았다.** Superuser/DB 전역 권한을 부여하지 않았고 운영 DB 스키마 변경도 없었다.

운영 DB 백업 및 Migration은 수행하지 않았다. 이유는 테이블/데이터 권한 및 스키마를 변경하지 않고, 코드의 읽기 잠금 방식을 수정했기 때문이다. 시작·완료 실행 이벤트 외에 원고, Publishing Job, Blogger 게시 행은 수정하지 않았다. 운영 schema는 계속 89다.

## 검증

- 권한 최소화 테스트: 1 passed, 17 deselected. UPDATE privilege 없이 advisory lock과 일반 SELECT가 사용되고 `FOR UPDATE`가 없는지 확인.
- 관련 Import/Publication/Trends 테스트: 82 passed, 0 failed.
- 변경 파일 reflection 검증: API pytest 143 passed, Ruff 통과, mypy 통과, wheel build 통과, Dashboard production build 통과, Pester 31 passed.
- `ruff check` 변경 Python 파일: 통과.
- `mypy services/api/woori/content_imports.py`: 통과.
- `git diff --check`: 통과.
- `scripts/migrate.py --status`: DB `woori_blog_agent`, schema 89.
- 운영 role 읽기 전용 검증: advisory lock + plain SELECT 성공. 권한은 `SELECT=true`, `UPDATE=false`로 유지.

Pytest 캐시 경로에 대한 권한 경고가 있었지만 테스트 결과에는 영향이 없었다.

## 운영 반영

`apply-verified-changes.ps1 -Apply -Confirm:$false`가 검증·빌드 후 정상 종료를 요청했다. API는 graceful하게 정지했으나 Publication Worker가 300초 backoff 사이클에 있어 스크립트의 180초 대기 안에 종료 확인이 되지 않아 스크립트는 재기동 단계 전에 중단됐다. 강제 종료는 하지 않았다. Worker는 다음 사이클에서 `Graceful stop requested between publication cycles`를 기록하고 정상 종료했다.

이후 저장소의 `scripts/start.ps1`로 API와 Publication Worker를 각각 재기동했다. 최종 확인 시:

- API PID `27216`, 반영 revision `5826b59bbb1944ed4a954745ffe4e6270c256217`, `/health` HTTP 200.
- Publication Worker PID `18252`, 동일 revision, fresh heartbeat `running`, `last_error_category=null`.
- Research Worker PID `32948`, fresh heartbeat `running`, revision `67e9218c1fecafffab079da4e960fbd979642dbb`. Research 전용 모듈은 수정되지 않았으므로 불필요한 중단·재시작을 하지 않았다.
- Dashboard PID `7656`, HTTP 200, revision `6e7541524c421c23d2fcdd1011a32660474cb83b`. Dashboard 파일은 수정하지 않아 그대로 유지했다.
- 최종 DB 조회에서 Publishing Job `running=0`, `queued/retry_wait=0`; Worker는 작업 없는 정상 idle 상태였다.
- 새 Worker 시작 이후 확인에서 42501 오류가 재발하지 않았고 heartbeat 오류는 null이었다.

재기동 시 Blogger 게시 작업은 진행 중이지 않았다. 실제 Blogger API POST/PATCH/DELETE 및 테스트 초안 생성은 0건이다. 기존 게시물·Job·OAuth·운영 설정은 변경하지 않았다.

## 기존 및 변경 후 동작

- 이전: immutable 행에 `SELECT ... FOR UPDATE` → `woori_app`의 UPDATE 권한 부족으로 42501 → Publication Worker degraded.
- 변경: Import ID별 transaction advisory lock + plain SELECT → immutable 테이블 권한을 늘리지 않고 버전 체인 접근.
- 운영 확인: Worker heartbeat running, last error 없음; 대기/실행 중 Job 없음. 실제 게시 요청은 수행하지 않았다.

## 미완료 사항

- 실제 게시 큐가 새 Worker에서 처리되는 운영 사례는 게시 대상이 없어서 확인하지 않았다. Blogger 쓰기는 의도적으로 검증하지 않았다.
- `apply-verified-changes.ps1` 자체는 Worker의 장시간 backoff 종료를 180초 안에 확인하지 못해 비정상 종료 코드를 반환했다. 서비스는 강제 종료 없이 개별 start 스크립트로 복구했고 API/Worker 적용 revision을 확인했다.
- Dashboard와 Research Worker는 이번 변경 대상 파일이 없어 이전 revision을 유지한다.
- 작업 후 미추적 기존 산출물과 stash는 삭제·정리하지 않았다.

## Git

- 코드 수정: `818fcb20481ab72d3966eed953ae0c994f23fb6c` — `Fix : [Publication] Lock immutable import revisions without update grant`
- 기존 계약 검증 보완: `5826b59bbb1944ed4a954745ffe4e6270c256217` — `Fix : [Research] Align import schema with general news category`
- 개발 기록 커밋은 후속 Git 기록으로 연결한다.
