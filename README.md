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



## Phase 3 / 3.5 콘텐츠 리서치·실제 로컬 AI

[관리 화면](http://127.0.0.1:3100/research)에서 후보/출처/검토, 실제 수집, 모델 상태·성능, 평가 초안, 버전 비교, 최신 품질 검사를 관리한다. 기존 API 8100, Dashboard 3100, PostgreSQL 5432를 유지한다.

- 실제 무료 수집: Fed 보도자료 RSS/공식 본문, Wikidata CC0 주제 메타데이터. 일곱 카테고리 후보는 수집하지만 모든 카테고리의 공식 발표/영업/효능 검증까지 연결한 것은 아니다.
- 실제 CPU 추론: 프로젝트 전용 llama.cpp b11889와 Qwen3 0.6B/1.7B Q8_0. 엔진과 모델의 라이선스·해시를 확인하며 .local은 Git 제외다.
- 실제 네 언어 내부 초안 저장은 검증했다. 두 모델의 품질 문제로 일반 자동 처리는 승인하지 않았고 평가 초안은 quality_held다. 검색량/CPC는 미수집, 운영 발행·유료 AI는 차단한다.
- 모델별 실제 속도·CPU/RAM과 실패를 보존한다. GPU 이용률은 미측정이며 GPU 가속을 사용한 것으로 보고하지 않는다.
- 한국어 UI와 Phase 3 개발 규칙의 이전 문자 인코딩 손상을 복구했다. 과거 Git 이력과 DB 감사·콘텐츠 버전을 삭제하지 않는다.

```powershell
.venv/Scripts/python scripts/migrate.py
.venv/Scripts/python scripts/setup-local-ai.py
.venv/Scripts/python scripts/start-local-ai.py Qwen3-1.7B-Q8_0.gguf
.venv/Scripts/python scripts/setup-local-ai.py --with-vulkan
.venv/Scripts/python scripts/start-local-ai.py Qwen3-4B-Q4_K_M.gguf 4 vulkan
.venv/Scripts/python scripts/benchmark-local-ai.py
# 기존 API/Dashboard/Windows Worker를 실행한 상태에서 명시적 평가:
.venv/Scripts/python scripts/verify-live-pipeline.py --evaluation-only
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify.ps1
.venv/Scripts/python scripts/verify-secrets.py
```

[실제 추론 아키텍처](docs/architecture/live-research.md), [소스·권리·설치·운영](docs/operations/live-research.md), [Phase 3.5 개발 기록](docs/development/P3-5-001.md)을 참조한다. setup은 최소 20GiB 여유를 요구하며 기존 리스너·PATH·다른 프로젝트를 변경하지 않는다.

## Zero additional cost
All external requests pass through the closed provider allowlist in `services/api/woori/external_policy.py`. Paid AI, metered services, paid data, proxies, hosting and cloud services are blocked. Free quotas are hard stops; a 429 never triggers retries or provider fallback. Blogger reads are blocked until the Google Cloud project's billing status is verified. The authenticated research state reports provider blocks and suspicious credential variable names only. See [the cost and provider review](docs/operations/zero-cost-policy.md).
## Evidence-led generation pipeline

Research generation runs through persisted source, evidence, outline, section, localization, claim, SEO, and draft-persistence stages. Inspect per-attempt inputs, outputs, source links, validations, retries, and timings in the authenticated `/research` dashboard. Machine checks do not approve semantic truth or naturalness; uncertain versions remain `quality_held` and unpublished. See [the staged pipeline architecture](docs/architecture/pipeline-stages.md), [schema model](docs/architecture/data-model.md), and [Phase 3.7 source review and evaluation record](docs/development/P3-7-001.md).

## Evidence-preserving localization

Current source excerpts, reviewed source language, fact snapshots, approved glossary revisions, and per-language localization evaluations are stored separately and append-only. Original-language excerpts do not count as target-language prose. Cross-language generation uses only the already installed local model; if it is unavailable or the target language is unsupported, the result remains held. The `/research` screen shows source/output comparisons and review status. See [the localization architecture](docs/architecture/evidence-localization.md), [Phase 3.8-B record](docs/development/P3-8B-001.md), and [measured evaluation](docs/development/P3-8B-evaluation.json).


## Phase 3.8-C1 finance/stock article evaluation

The current source-backed evaluation is limited to Federal Reserve releases and SEC EDGAR filings/XBRL facts. It stores retrieval timestamps and a per-claim fact ledger, generates local-only Qwen drafts for active language profiles, and exposes complete saved drafts and machine checks in `/research`. The recorded C1 run is in [the evaluation artifact](docs/development/P3-8C1-evaluation.json); quality failures remain held and require editorial review. No Blogger write or paid API path is enabled. See the [architecture](docs/architecture/complete-articles.md) and [operations guide](docs/operations/live-research.md).

Phase 3.8-C2 adds append-only rechecks and preserves future bounded JSON/schema failure excerpts locally. Recheck historical output without regeneration using `.venv/Scripts/python scripts/recheck_article_quality.py`; it refuses to overwrite its evaluation artifact and never promotes drafts. See [C2 regression output](docs/development/P3-8C2-regression.json) and [the development record](docs/development/P3-8C2-001.md).
# Phase 3.8-C3 fact-first evaluation

The content worker can persist exact source spans in `evidence_facts`, translate each span separately with the local model, attach citations in code, and retain per-fact checks in immutable generation-stage records. Run the bounded Fed/SEC evaluation with `python scripts/run_fact_first_evaluation.py` only when its model and resource preflight pass. This remains evaluation-only and cannot enable Blogger publishing.
