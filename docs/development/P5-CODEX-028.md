# P5-CODEX-028 — 실제 Blogger 게시 차단 진단

- 작업 시각: 2026-10-29, 12:51 KST
- 브랜치: `develop`
- 목표: 승인 범위 안에서 운영 차단을 재검증하고 실제 Blogger 게시 경로와 남은 사람 조치를 특정한다.
- 변경 사유: P5-CODEX-027 당시 Dashboard/API/Worker가 비기본 포트에서 실행됐고 Dashboard는 API 연결 오류, 게시 기록은 0건이었다.
- 기존 문제: 개발/테스트용 서비스가 운영 서비스처럼 보일 위험이 있었고, OAuth 연결의 실제 원격 접근 상태와 공개 게시 게이트의 구체적인 결손을 현재 시점에서 확인할 증거가 필요했다.
- 목적: 사용자 실행 프로세스는 종료하지 않고, 허용된 Blogger 읽기를 A 연결로 검증하며, 실제 운영 API·게시 적격·공개 승인·사람 검토 상태를 구분해 기록한다.

## 변경 전/후

- 변경 전: P5-CODEX-027 진단 이후 API는 port 18100, Dashboard 13100, Worker 구 코드 상태였고 실제 Blogger 원격 재검증 기록이 새로 없었다.
- 변경 후: 운영 DB에서 OAuth A의 Blogger `users/self`, 계정 블로그 목록, 네 블로그 `blogs.get`, live/draft 목록 및 기존 draft 상세 GET을 검증했다. 실제 live insert/publish는 호출하지 않았다. 소스 변경 없이 기존 live publisher/queue와 안전 게이트를 재확인했다.
- 작성 파일: 이 문서와 [operations runbook](../operations/runbook.md). 애플리케이션 코드·DB 스키마·원고·OAuth 매핑은 변경하지 않았다.

## 실제 운영 DB와 Blogger 결과

- OAuth A `4839f8b9-69c8-4ce4-b1c1-5b71e96d5896`: `connected`, scope `https://www.googleapis.com/auth/blogger`, refresh token 존재. 만료된 access token은 공식 OAuth refresh 경로로 갱신되었고, 토큰 값은 출력/문서화하지 않았다.
- 비용 정책: `google_blogger_read`의 `blogger_read` 범위 호출 허용, 비용 차단 자격증명 이름 0개, terms review 만료 아님. 이는 별도 Blogger API 요금/Cloud Billing을 Google Console에서 확인했다는 뜻은 아니다.
- Blogger 실 API 읽기: 26개 Blogger GET 결과가 HTTP 200. Blogger users/self 확인 완료(이메일 신원 확인은 하지 않음). 계정 목록에서 등록된 4개 ID 확인. 각 `blogs.get`의 ID와 정규화된 URL이 로컬 매핑과 일치.
- 각 블로그에서 기존 draft 1건을 발견하고 postId를 이용한 같은 연결의 GET으로 `DRAFT` 확인. 발견 postId는 en `6200412717175382056`, ja `3922184436060234592`, ko `3147869148049076326`, zh-CN `2489135230154436472`. 이 4건은 `publishing_records`와 `blogger_write_operations` 결과에 연결되지 않으므로 기존 원격 글로 취급했으며 이 에이전트의 게시 성공이나 신규 게시로 집계하지 않았다. 게시물 본문/제목은 출력하지 않았다.
- Blogger 실제 공개 게시: 0건. 실제 새 draft 생성: 0건. 게시 URL/공개 상태를 저장한 신규 publication record: 0건. 실제 live POST 0건.
- 운영 DB: 콘텐츠 버전 364개; manual Codex import 1건(사람 검토 대기); import assessment 3건 machine fail, 2건 machine pass이나 모두 `independent_source_verification=false`, `publish_ready=false`; publish_ready 평가 0건; publication approval event 0건; live job 0건; live attempt 0건; publishing record 0건. 기존 원고와 감사 기록을 수정·삭제하지 않았다.
- 현재 public publish 외부 승인 scope에는 `public_post_publish`가 없다. OAuth 비용 승인에 포함된 것은 `blogger_read`, `private_draft_create`, `user_approved_post_update`이다. 사용자 승인된 정확한 editorial version/hash도 없으므로 관련 게이트를 변경하거나 승인 행사를 만들지 않았다.

## 현재 프로세스 및 HTTP 점검

- `scripts/status.ps1`: Dashboard 35616 / 13100, API 부모·자식 36796/47060 / 18100, Worker 부모·자식 37512/46704. 기본 3100/8100은 listen하지 않았다. 소유 터미널을 확정하지 못해 종료·재시작하지 않았다.
- API 18100 `/health`: HTTP 200. Dashboard 13100 `/`: HTTP 200이나 본문은 “로컬 API 서버에 연결할 수 없습니다” fallback. 같은 API에서 `/admin/operations/dashboard`는 404여서 현재 프로세스는 develop의 Dashboard read-model API를 제공하지 않는다. `/admin/blogger/status`는 연결 0건/cost approval 없음으로 응답해 운영 DB API로 사용할 수 없다. 이 프로세스를 운영 API라고 간주하지 않는다.
- API Import HTTP: 인증된 임의 UUID detail GET은 404 `Imported manuscript not found`로 응답해 HTTP import route가 DB까지 도달했으며 503은 반환하지 않았다. Dashboard BFF의 detail GET도 404를 전달했다. 이는 현재 import가 운영 DB에서 성공한다는 증거는 아니다. 격리 DB 종단 간 import/assessment 테스트는 아래 통과했다.
- Dashboard의 운영 진단은 테스트용 13100/18100 포트 구성을 통해 현재 보이지 않는다. Dashboard/API 기본 운영 경로 3100/8100은 내려가 있다. 새 develop 코드의 실제 API/Worker 실행 및 heartbeat는 확인되지 않았다.
- Worker 최신 코드는 아직 로드되지 않은 것으로 확인되며, 현재 heartbeat PID는 과거 실행 프로세스다. 중복 프로세스 방지 스크립트는 현재 동작 중인 프로세스를 감지해 재시작을 거부한다.

## 게시 경로와 차단 사유

- develop 코드에는 `BloggerLivePublisher`, durable idempotency ledger, `publishing_jobs` live adapter, `publication_worker.py` public queue worker, `posts.insert` draft stage / `posts.publish` stage, 원격 GET 확인과 publication record 저장 경로가 이미 있다. P5-CODEX-025에서 구현된 구조를 이번 작업에서 중복 구현하지 않았다.
- Worker는 격리 테스트에서 MockTransport 기반으로 검증한다. 실제 공개 작업은 별도 `public_post_publish` append-only 승인, 정확한 원고 버전의 편집/게시 승인, `publish_ready`, 매핑·한도·긴급중지 재검사를 요구한다. dispatcher의 명시적 운영 승인 플래그도 추가로 필요하다.
- 현재 차단 이유: publish-ready 원고 0, publication approval 0, public publish scope 승인 없음, 실행 중인 운영 API/Worker 없음. 이들 중 승인·편집은 사람 조치이고, 런타임은 사용자가 원래 터미널에서 정상 재시작해야 한다.
- 정책: 코드 안전 상한 KST 전역 50/일, ko/ja/zh-CN 각 10/일, 영어 전역 잔여량 우선, 영어 20/시간(기타 지원 언어 10/시간), blog 5분·계정 2분 최소 간격이 존재한다. DB 운영 모드는 `manual`, Auto 승인 false, `daily_auto_limit=1`, `minimum_interval_minutes=1440`, 긴급 중지 false였다. 설정은 변경하지 않았다.

## 검증 및 감사

- 격리 DB 테스트: `test_content_imports.py`, `test_publications.py`, `test_blogger_live_policy.py`, `test_publication_daily.py`, `test_dashboard_read_models.py` — **63 passed**. 실제 운영 데이터가 아니라 `.env.test` 격리·rollback fixture를 사용했다.
- 실제 API에서 Blogger GET 26건 모두 200, OAuth refresh 성공 1건. 공개/초안 쓰기 0건.
- Import API detail 조회는 404 expected; 신규 Import POST는 운영 DB에서 실행하지 않았다. 격리 테스트에서 POST, 버전 생성, 평가와 실패 폐쇄를 검증했다.
- run id `51c5ead5-796a-491d-b15c-1a83111cf445`; 실행 시작, 외부 Blogger GET 메타데이터 및 `blogger.read_validation.completed`를 append-only audit로 기록했다. 완료 이벤트는 테스트·커밋 종료 후 기록한다.

## 남은 운영자 작업

현재 user-owned VS Code/PowerShell 터미널을 찾아 테스트용 Dashboard, API, Worker를 각각 `Ctrl+C`로 정상 종료하고 `scripts/status.ps1`로 13100/18100/Worker 프로세스가 사라졌는지 확인한다. 새 프로젝트 PowerShell에서 `WOORI_TEST_MODE`가 설정되지 않았고 애플리케이션이 `.env` 운영 DB 설정을 읽는 것을 확인한 뒤 `scripts/start.ps1 -Service all`, 별도 터미널에서 `scripts/run-worker.ps1`을 한 번씩 실행한다. 기존 터미널을 특정하지 못하면 PID를 강제 종료하지 않는다. Dashboard는 기본 `127.0.0.1:3100`에서 API `127.0.0.1:8100`에 연결되고 `/admin/operations/dashboard`가 200인지 확인해야 한다.

그 다음 사용자는 Dashboard에서 Fed 원고의 근거·권리·주장·표현을 검토하고 새 immutable editorial revision을 승인해야 한다. 사람이 확인한 해당 버전에 publication approval을 부여한다. 공개 쓰기 전에 Google Cloud Console의 프로젝트 Billing/quota를 확인하고, 특정 블로그·원고 버전/body hash·공개 범위를 담은 explicit public approval을 별도 기록해야 한다. 승인 전에는 실제 draft/write/publish를 실행하지 않는다. 최초 public run도 Auto가 아닌 정확히 승인된 수동 live job 하나로 수행하고 Blogger GET·URL·DB·Dashboard 결과를 확인한다.

실행 환경이 정상화되기 전과 해당 승인 기록이 만들어지기 전까지 게시 성공 판정은 불가하다. 이 작업에서 Auto, OAuth 연결 매핑, 일일 제한, 외부 공개 설정을 바꾸지 않았다. 커밋 해시는 후속 git log 참조.
