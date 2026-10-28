# P5-CODEX-015 — 운영 전환 결과 및 차단 사항

기록 시각: 2026-10-29 (Asia/Seoul)

브랜치: `develop`

목표 범위: 운영 DB 백업·복원 검증 및 안전한 Migration 035–048 적용, 실제 Blogger 준비 확인, 첫 공개 게시 및 Auto 전환 가능성 판정

## 결과 요약

운영 DB는 백업과 격리 복원 절차 검증 후 schema 34에서 48로 비파괴 업데이트했다. Dashboard/API는 관리 스크립트로 시작해 읽기 전용 HTTP 검사를 통과했으며 현재 로컬에서 실행 중이다. 실제 Blogger 읽기 권한 검증은 성공했지만, 공개 게시와 Auto 운영에 필요한 코드·정책·원고 조건은 충족되지 않아 게시 요청과 Auto 활성화를 수행하지 않았다.

이 작업은 실제 Blogger 운영 개시 완료가 아니다. `posts.insert` 공개 게시 0건, Blogger 게시물 수정·삭제 0건, 유료 AI API 0건이다.

## 선행 구현의 실제 상태

- P5-CODEX-011~014는 원고 Import, 검토 UI, 게시 HTML, Mock Publisher와 read-only 운영 현황을 제공한다. 이 범위의 Mock 성공은 실제 Blogger 쓰기 지원을 뜻하지 않는다.
- `services/api/woori/publications.py`의 Publisher는 Fake/Mock 및 `DisabledRealBloggerPublisher`뿐이다. 실제 Blogger 쓰기 어댑터·공개 URL 사후 검증은 없다.
- `services/api/woori/ai.py`의 `PRODUCTION_GENERATOR_CONFIGURED`는 `False`다. ChatGPT 예약 작업의 로컬 전달도 확인되지 않았다.
- 운영 `collection_sources` 3개는 모두 `scheduled=false`; `research_schedules`는 0건이다. 운영 Trends 표는 관측·수집 실행·주제·Research Package가 각각 0건이다.
- Task Scheduler의 `WooriBlogAgent-Worker`는 등록돼 있으나 마지막 실행 결과가 비정상 종료 코드 `3221225786`이고 운영 heartbeat가 없다. 이 Worker가 Trends 예약이나 공개 게시를 수행한다는 증거는 없다. `WooriBlogAgent-Backup`은 등록 상태 `Ready`, 직전 결과 `0`이다.
- P5-CODEX-009 미국 소비·물가 원고는 테스트 DB 평가용이다. 원문 권리 상태가 `unknown`, 사람 검토 대기, 독립 출처 검증 미완료, `generation_ready=false`, `publish_ready=false`다. 이를 운영 원고나 게시 승인으로 취급하지 않았다.

## 운영 DB 백업과 마이그레이션

- 사전 상태: `woori_blog_agent`, schema 34.
- 백업: `backups/20261028T164859Z.dump`, 437,385 bytes, SHA-256 `1948111FA09DCFE0D0F9DFEC825F344507899F8506C8F6E812C69AFB41000827`.
- PostgreSQL custom archive catalog 검증 통과. 격리 복원 리허설은 별도의 `woori_blog_agent_restore_*` DB에 수행했고 schema·스냅샷 행 수·감사 로그 UPDATE 차단 검증 후 해당 임시 DB만 제거했다. 운영 DB는 복원 대상으로 사용하지 않았다.
- Migration 035–048 SQL을 복제본에서 실행한 선행 리허설은 통과했다. 기존 콘텐츠 행 수와 과거 승인/감사 자료를 보존했고 카테고리 추가만 허용된 seed 차이로 확인했다. SQL의 `OR TRUNCATE` 문구는 append-only 테이블의 삭제 방지 트리거 선언이며 `TRUNCATE` 문 실행이 아니다. `DROP`, 데이터 `DELETE`, 기존 콘텐츠 초기화는 실행하지 않았다.
- 운영에는 저장소의 `scripts/migrate.py`를 통해 035–048을 적용했고 성공 종료 메시지와 schema 48을 확인했다.
- 적용 후 직접 조회: `content_versions=360`(기존 360 보존), `audit_events=1460`(마이그레이션·복원 및 Blogger 읽기 검증을 포함한 append-only 이력), `publishing_jobs=1`, `publishing_records=0`, `publication_approval_events=0`, `publish_ready=true=0`, 운영 Trends 관측 0건.
- 이 작업은 오프사이트 암호화 백업의 키 복구 리허설을 수행하지 않았다. 로컬 백업 복구 검증과 외부 재해복구 검증은 구분한다.

## Blogger OAuth 및 원격 읽기 검증

- 네 블로그의 기존 매핑은 계속 기존 `blogger.readonly` 연결을 참조한다. 이 연결의 만료 시각은 2026-10-27이며 매핑을 변경하지 않았다.
- DB에 이미 등록돼 있던 쓰기 OAuth 연결 2건은 모두 저장 scope가 `https://www.googleapis.com/auth/blogger`이고 refresh token이 암호화 저장돼 있었다. 두 연결 모두 기존 만료 시각이 지난 상태였다.
- 기존 `verify_common_connection` 읽기 검증 경로로 두 연결을 각각 갱신하고 `users/self/blogs`를 조회했다. 각각 1회의 OAuth token refresh와 1회의 Blogger `GET`이 성공했고 HTTP 200으로 네 Blog ID가 모두 일치했다: ko `3321654108096579717`, en `5240203250707821039`, ja `7562596540375659150`, zh-CN `1931836538202286191`.
- 두 후보 모두 네 블로그에 대한 읽기 접근이 확인됐다. 이것은 계정 신원 확인이나 글쓰기 성공 증명이 아니다. Google 계정 신원은 조회·추측하지 않았다. 공통 연결 검증만 감사 이벤트에 기록했고, 어떤 후보도 블로그 공통 OAuth 연결로 할당하지 않았다.
- Blogger 원격 호출은 읽기 GET 2회뿐이다. OAuth token refresh POST 2회가 있었고 Blogger `posts.insert`/공개 게시 요청은 0회다.

## 공개 게시와 Auto가 차단된 이유

1. 실제 Blogger Publisher가 코드에서 명시적으로 비활성화돼 있다. 현재 API는 `real_writes_enabled=false`, `live_auto_enabled=false`를 fail-closed로 반환한다.
2. 두 OAuth 쓰기 scope는 원격 읽기로 네 블로그 접근을 확인했을 뿐, 실제 쓰기 테스트는 하지 않았다. 현행 비용 승인 scope는 `blogger_read`, `private_draft_create`, `user_approved_post_update`다. 공개 게시와 무인 Auto 게시 권한은 포함되지 않는다.
3. Google Cloud Console의 프로젝트별 Blogger API quota 및 Billing 연결 상태는 이 실행 환경에서 확인할 수 없었다. 공식 문서는 실제 프로젝트의 quota와 사용량을 Cloud Console에서 확인하도록 안내한다. 따라서 비용 0원과 프로젝트별 quota를 검증 완료로 표시하지 않는다.
4. P5-CODEX-009 원고는 사람이 확인해야 하는 평가용 원고이고 출처 재사용 권리도 미확인이다. 현행 운영 DB에 `publish_ready=true`가 0건이다.
5. 자동 생성 Provider가 설정되지 않았다. GPT 예약 작업의 실행 상태·로컬 파일 전달·Import도 검증되지 않았다.
6. 운영 자동 수집 스케줄은 없다. 네 게시 정책은 모두 inactive 및 `auto_publish_allowed=false`, 네 언어의 `publishing_enabled=false`, publication mode는 Manual, Auto 설정·승인 건수는 0이다.

위 상태에서 기존 비용·권한 게이트를 늘리거나, 승인 상태를 변경하거나, 후보 연결을 지정하거나, 게시 엔드포인트를 우회하지 않았다.

## 로컬 서비스와 비밀정보 검사

초기에는 3100/8100이 비어 있었고 llama.cpp 11435 PID 39500은 기존 상태 그대로 유지됐다. `scripts/start.ps1 -Service all`로 관리된 API와 Dashboard를 시작했다.

- API `/health`: HTTP 200, 관리 runner PID 33920.
- Dashboard `/`, `/manuscripts`, `/publishing`, `/operations`, `/blogger`: HTTP 200, 관리 runner PID 17392.
- `scripts/verify-secrets.py`: 통과. HTTP 응답·DB 이력에 평문 비밀 값이 없고 게시 활성 플래그가 모두 꺼져 있음을 확인했다.
- API/Dashboard는 현재 사용자 테스트를 위해 실행 상태로 두었다. Worker는 시작하지 않았다. 기존 llama.cpp 서버는 건드리지 않았다.

## 다음 재개 조건

1. Google Cloud Console에서 OAuth 클라이언트가 속한 정확한 프로젝트를 선택하고 Blogger API 활성화, API별 Quotas & System Limits의 현재값·사용량, Billing 연결 상태를 확인한다. 관련 콘솔 경로와 확인 시각을 운영 기록에 남긴다. 공식 절차는 [Google Cloud quota 확인 문서](https://docs.cloud.google.com/docs/quotas/view-manage)를 참고한다.
2. 두 검증된 OAuth 연결 중 사용할 연결을 운영자가 선택한다. 실제 계정 신원은 로컬에 노출하지 않으며 필요하면 사용자가 Google 화면에서 확인한다. 현재 read-only 매핑과 연결을 바꾸기 전후에 감사를 남긴다.
3. `posts.insert`의 실제 Publisher, 중복/타임아웃 복구, 게시 후 HTTP 검증, Blogger 공개 게시 및 Auto용 비용·권한 게이트를 별도로 구현하고 격리 테스트한다. Blogger API는 공식적으로 OAuth를 요구하고 POST insert를 제공하지만, 이는 현 프로젝트에 실 Publisher가 있다는 뜻은 아니다.
4. 최신 공식 근거와 재사용 권리를 검토한 원고를 준비하고 사람 검토를 완료해 기존 승인 워크플로로만 publish-ready 상태에 도달시킨다. P5-CODEX-009 평가 원고는 이 절차를 마치기 전 게시하지 않는다.
5. GPT 예약 작업 또는 지원되는 원고 Import가 실제 동작하는지 별도로 확인한다. 확인 전에는 Auto 콘텐츠 생성으로 표시하지 않는다.
6. 위 조건을 통과한 블로그만 first-post 확인 뒤 Auto 범위를 설정한다. 현재 Auto는 네 블로그 모두 꺼진 상태다.

### 사용자 확인이 필요한 Cloud Console 항목

- **APIs & Services → Enabled APIs & services**: Blogger API가 해당 OAuth 프로젝트에서 활성 상태인지.
- **APIs & Services → Quotas & System Limits**: Blogger API의 quota 이름, 제한값, 사용량, 프로젝트별 조정 여부.
- **Billing → My Projects**: OAuth 프로젝트의 Billing 연결 상태. 예상 외 비용을 피하기 위한 알림/예산 설정도 함께 검토.

Console의 실제 값은 이 기록에서 확인되지 않았으며, 0원 보장이나 quota 수치는 추정하지 않는다.

## 변경·부작용 기록

- 실제 운영 DB 변경: 승인된 Migration 035–048 적용과 append-only 마이그레이션/검증 감사 이벤트만 추가.
- 기존 원고/콘텐츠 삭제·수정: 0건.
- Blogger 게시/수정/삭제: 0건.
- Auto 설정 변경: 0건.
- 유료 AI API 호출: 0건.
- Blogger 원격 요청: list/read GET 2회, 게시 쓰기 0회.
- main 변경: 없음. `.playwright-mcp/` 보존.
