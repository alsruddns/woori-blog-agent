# P5-CODEX-008 외부 원고 Import 운영 절차

## 작업 범위와 상태

`woori-content-import/1.0` 입력은 외부에서 온 미검증 자료로 저장된다. Import는 사실 승인, generation 승인, Blogger 발행 승인을 대신하지 않는다. 현재 파이프라인은 원고 버전, 결정론적 검사 결과, 안전한 HTML 미리보기, 사람 검토 기록, 외부 생성 대기, Fake Publisher 시뮬레이션을 제공한다. 실제 Blogger API 호출은 이 경로에서 수행하지 않는다.

시험에 사용한 DB는 `woori_blog_agent_test`이며 Migration 048까지 적용했다. Import version은 기존 `content_versions` 모델에 불변 매핑되고, event group과 locale를 공유한다. 이 매핑은 콘텐츠를 검증하거나 발행 가능 상태로 만들지 않는다. 운영 DB `woori_blog_agent`는 읽기 전용으로 확인한 시점에 schema 34였고 Migration 043–046이 기록되어 있지 않았다. 047–048도 적용하지 않았다. 운영 DB 변경은 0건이다. Import API는 운영에 필요한 schema 48 적용 전까지 fail-closed다.

## 운영 DB 변경 전 순서

1. 운영 변경 승인과 유지보수 시간대를 확인한다. 이번 개발 승인만으로 운영 DB 적용 권한이 생기지 않는다.
2. 운영 API 및 Worker가 사용하는 실제 DB 대상, 서버, 역할을 확인한다. 어떤 비밀 값도 기록하지 않는다.
3. `.env.migration`의 전용 마이그레이션 역할로 `scripts/backup.py`를 실행해 암호화된 보관 위치에 백업을 만든다. 생성 파일의 존재·크기·체크섬을 검증하고 `scripts/restore-rehearsal.py`를 별도의 임시 DB에서 실행한다. 백업 암호화 키의 복구 가능성도 별도로 확인한다.
4. 로컬 테스트 DB에서 Migration 043–048 전체 순서를 재현한다. 047은 045의 Import 테이블과 append-only 감사 함수를, 048은 기존 `content_groups`, `content_localizations`, `content_versions` 및 Import 047의 버전 테이블을 전제로 한다. 기존 운영 DB가 34이므로 043–047을 건너뛰고 048만 적용하지 않는다.
5. 043–047의 DDL, 역할 권한, 데이터 backfill, 테이블 잠금과 예상 시간을 검토한다. 테스트 전후 기존 원고·감사 행 수와 불변성 검사를 비교한다.
6. 변경 계획·백업 복원 증거·중단/복구 절차를 승인자에게 제시한다. 승인이 있고 실제 운영 절차가 허용될 때에만 기존 관리 마이그레이션 절차로 순서대로 적용한다. 이 작업에서는 실행하지 않는다.
7. 적용 후 schema_migrations, 권한, 기존 원고·감사 수, append-only 트리거를 읽기 전용으로 확인한다. Import 쓰기 활성화는 별도 검증 및 정책 승인이 필요하다.

운영 DB의 실제 현재 버전은 적용 직전에 다시 조회해야 한다. 2026-10-28의 읽기 전용 점검은 schema 34, 043–046 미적용을 반환했다. 이후 변경되었을 수 있다.

## Import 사용 절차

1. `docs/schemas/woori-content-import-1.0.schema.json`을 기준으로 JSON을 검증한다. 원고는 Markdown만 포함하고 HTML/스크립트, 비밀 값, 실행 가능한 메타데이터를 넣지 않는다.
2. `docs/schemas/examples/content-import-en.example.json` 또는 `content-import-ko.example.json`을 형식 참고용으로 사용한다. `example.gov` fixture는 실제 출처가 아니므로 운영 원고로 가져오지 않는다.
3. 관리자 `/imports`에서 파일 또는 JSON 텍스트를 가져온다. 같은 콘텐츠 ID와 내용의 재요청은 중복으로 처리되고, 같은 ID에 다른 내용이 있으면 충돌로 거부된다.
4. `/manuscripts`의 Import 대기열 또는 `/imports`에서 원고를 연다. 원문 출처·주장·권리 정보는 작성자가 제공한 값일 뿐, Import 과정에서 원문을 재수집하거나 독립 검증하지 않는다.
5. 원고 수정은 새 불변 버전을 만든다. 기준 버전이 오래되었거나 동일한 수정이 중복되면 충돌·중복 응답을 확인하고 최신 버전을 다시 연다.
6. 결정론적 검사 후 사람이 원문, 주장과 근거, 권리·인용 조건을 확인한다. 기계 통과는 사실 검증 완료가 아니다. 사람 검토 기록도 `generation_ready` 또는 `publish_ready`를 바꾸지 않는다.
7. 다국어 요청은 provider가 연결되지 않은 상태에서 `awaiting_external_provider`로 기록된다. 외부 현지화 원고가 준비되면 원본과 같은 event group 및 부모 ID를 지정해 별도 Import하고, 언어별로 독립 검토한다.
8. Fake Publisher는 테스트용 시뮬레이션 기록만 남긴다. Fake Post ID는 Blogger ID가 아니며, 실제 공개·초안·예약·수정·삭제가 발생하지 않는다.

## 감사 및 복구

원본 Import, 원고 버전, 평가, 검토, 현지화 요청/취소, Mock 발행 시도는 append-only로 저장한다. 기존 행을 고치거나 삭제해 재시도하지 않는다. 같은 멱등성 키를 다시 보낼 때 기존 결과를 확인하고, 불확실하면 새 키로 발행하지 말고 운영 상태를 조사한다. 현재 Import Mock 기능은 외부 쓰기를 호출하지 않아 Blogger의 타임아웃 복구 절차와는 구분된다.

## 안전 한계

- 이 기능은 외부 원고 수신 경로이며 ChatGPT Scheduled Tasks의 공식 로컬 전달을 구현하지 않는다.
- 사실, 저작권, 인용 권리, 번역 품질은 사람 검토가 필요하다.
- 운영 DB migration 043–047, 실제 Blogger 쓰기, Auto 게시 모드는 이 개발에서 승인·수행하지 않았다.
- 운영 API에 적용하기 전에 schema 47과 호환되는 별도 운영 승인·백업·복원 리허설을 갖춰야 한다.
