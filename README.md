# woori-blog-agent

Windows 로컬 다국어 Blogger 운영 에이전트입니다. Phase 1 기반을 유지하며 Phase 2에서 읽기 전용 Google OAuth, Blogger 정보·ID·게시글 조회, 로컬 불변 콘텐츠 버전 관리와 API 감사 이력을 추가했습니다. 운영 Blogger 쓰기·자동 발행·유료 AI 호출은 계속 차단됩니다.

Dashboard: http://127.0.0.1:3100 · Blogger 관리: http://127.0.0.1:3100/blogger · API health: http://127.0.0.1:8100/health · PostgreSQL: 기존 localhost:5432. 다른 프로젝트의 3000/8000 포트는 사용하지 않습니다. 브라우저는 동일 출처 Next 프록시를 사용하며 API CORS는 열지 않습니다.

## Requirements and setup
Windows, Node 22+, Python 3.13+, PostgreSQL 16, npm and Git. No Docker.

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.lock.txt
.venv/Scripts/python -m pip install -e . --no-deps
npm --prefix apps/dashboard ci
```

Provision on a fresh installation only: create ignored `.env.bootstrap` containing `BOOTSTRAP_DATABASE_URL` for an administrator, then run `.venv/Scripts/python scripts/bootstrap.py`. It refuses existing project databases/roles and never migrates other databases. Existing local setup is already provisioned: do not rerun bootstrap.

```powershell
.venv/Scripts/python scripts/migrate.py
./scripts/run-api.ps1
# Separate terminal, from repository root:
./scripts/run-worker.ps1
# Separate terminal:
npm --prefix apps/dashboard run dev
```

Open http://127.0.0.1:3100. API listens on 127.0.0.1:8100. Root `.env` contains runtime database credentials and a random administrator bearer token; dashboard `.env.local` contains only that token, used server-side. Never prefix it with NEXT_PUBLIC. `.env.migration` is reserved for database owner tools. `.env.bootstrap` is never loaded by API/worker.

The local dashboard is viewable and editable by trusted local OS users; API administration requires the bearer token. Do not expose either port externally. Future remote operation requires dashboard authentication and TLS.

## Validation
```powershell
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m ruff check .
.venv/Scripts/python -m mypy services/api/woori
npm run lint
npm run build
npm run typecheck
```
Integration tests require the dedicated migrated PostgreSQL database and append identifiable diagnostic events permanently. No test deletes audit history.

See [architecture](docs/architecture/overview.md), [operations](docs/operations/runbook.md), [audit](docs/audit/events.md), [decisions](docs/decisions/0001-foundation.md), [development record](docs/development/P1-001.md) and [AGENTS.md](AGENTS.md).

## Multilingual configuration
Open http://127.0.0.1:3100/config to manage languages, multiple blogs per language, country profiles, policy schedules, categories and glossaries. The initial four user-provided Blogspot addresses are registered. Google Blog IDs stay NULL until user-consented API verification succeeds in /blogger. Registering a URL alone makes no external request. API/worker startup never loads administrator or migration-owner credentials.

Apply updates using `.venv/Scripts/python scripts/migrate.py` (latest version: 6). Migrations 001–004 are unchanged. Existing version IDs/content and audit records are preserved. Back up the dedicated database first. Configuration tests roll back synthetic records; diagnostic worker tests still append identifiable run history.

BCP 47 tags are normalized (e.g. pt-br -> pt-BR); language identity cannot be renamed in place. Deactivate an old identity and register a replacement to preserve references. New languages receive a default country profile with every capability unverified. Neither registration nor policy activation enables automatic publishing. Country-specific settings are saved as complete profiles, so review all fields before updating an existing language/country pair.

The summary API preserves its language-code array and adds language_details/blogs. The authenticated /admin/config API supports typed registration and safe updates; no delete, Blog ID editing, capability verification or automatic publishing switch is exposed. The dashboard proxy accepts same-origin JSON from loopback port 3100 only.

See [data model](docs/architecture/data-model.md), [multilingual decision](docs/decisions/0002-multilingual.md) and [development record](docs/development/P1-003.md). Search performance storage/display is implemented; data collection and actual language-specific SEO validation remain deferred.

## Phase 2 Google 연결

[설정 가이드](docs/operations/google-oauth.md)에 따라 Blogger API, 동의 화면, 웹 OAuth 클라이언트와 `http://127.0.0.1:3100/api/blogger/callback` URI를 등록합니다. 루트 `.env`에 GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET을 추가하고 `scripts/setup-oauth-key.py`로 암호화 키를 준비합니다. 기존 설정을 덮어쓰지 않습니다. API를 재시작하고 /blogger에서 사용자가 직접 Google 로그인을 승인합니다. 계정 비밀번호를 앱에 입력하지 않습니다.

권한은 blogger.readonly 하나입니다. 일회용 state·브라우저 바인딩·PKCE, 토큰 암호화·만료 갱신·취소·연결 해제를 지원합니다. 승인 전에는 미연결로 표시합니다. 일반 HTTP 쓰기 클라이언트와 운영 쓰기 경로는 없으며 쓰기 프로토콜은 MockTransport에서만 검증합니다. 로컬 콘텐츠 저장은 Blogger 초안 생성과 별개입니다.

WOORI_API_BASE_URL은 Dashboard 서버 전용 선택 설정으로 기본/허용 값은 `http://127.0.0.1:8100`입니다. GOOGLE_REDIRECT_URI는 위 3100 URI만 허용합니다. Next query 로그와 API access 로그를 비활성화해 인증 코드를 보호합니다. localhost와 127.0.0.1을 OAuth 도중 섞지 않습니다.

```powershell
npm run build
./scripts/run-dashboard.ps1
# 서버를 중지해 3100/8100이 비어 있을 때 HTTP 검증
.venv/Scripts/python scripts/smoke.py
.venv/Scripts/python scripts/smoke.py --mock-oauth
# 사용자 Google 동의 후 실제 읽기 검증
.venv/Scripts/python scripts/verify-blogger-live.py
```

Mock OAuth 검증의 DB 변경은 롤백합니다. 실제 Google 검증은 사용자 동의가 없으면 미실행으로 보고하며, 동의 후 정보·ID·게시글 GET만 수행합니다. [연동 구조](docs/architecture/blogger-integration.md)와 [Phase 2 개발 기록](docs/development/P2-001.md)을 참조하세요.

## 예약 작업과 복구

WooriBlogAgent-Worker와 WooriBlogAgent-Backup을 현재 사용자 Interactive 작업으로 등록하고 실제 큐 처리·백업 성공을 확인했습니다. 백업은 매일 03:00 및 로그인 시 수행합니다. 로그아웃 중 무인 실행은 지원하지 않습니다. 실제 재부팅은 하지 않았고 [검증 절차](docs/operations/runbook.md)를 마련했습니다.

격리 임시 DB의 실제 복원·건수·감사 불변성 검증을 완료하고 해당 임시 DB만 정리했습니다. 대시보드는 디스크 여유 20% 미만, 백업 실패 또는 26시간 지연을 경고합니다. 외부 알림과 암호화된 외부 백업 보관은 후속 운영 과제입니다. 경고를 이유로 다른 프로젝트 파일을 삭제하지 않습니다.
