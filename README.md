# woori-blog-agent

## Phase 5-C: local runtime and publication approval

Use `scripts/status.ps1` to inspect loopback listeners, PID, executable, start time, and verified checkout ownership without printing environment secrets. `scripts/start.ps1 -Service api|dashboard` launches a tracked project process and checks the read-only health route. `scripts/stop.ps1` requests graceful window shutdown only for a process launched and recorded by this manager, after port ownership and active TCP clients are checked. Unmanaged existing listeners are left alone; stop them with Ctrl+C in their verified original terminal. `scripts/restart.ps1` stops only when graceful exit is confirmed. AI can be started only by explicitly naming an already-installed model (`-Service ai -AiModel ...`); no download command is provided. The AI stop helper signals only a verified process group and does not force-terminate.

Tests using the application DB connection verify the local operations DB/user identity and wrap the connection in a forced rollback under pytest. Direct migration checks retain their disposable-schema outer rollback. The 12 historical Phase 5-B fixture versions remain immutable; `/research` manuscript rows come from the separate evaluation DB and do not include those operational test fixtures, so no broad title-based hiding rule was added.

Publication approval is an append-only user decision for the latest exact editorial version and body hash. It requires a passing machine check and positive editorial review for that same version. A later edit means a new approval is required; revocation is another event. Approval creates no publication job, leaves `publish_ready=false`, and does not unlock Blogger writes.

## Phase 4-M editorial review

`/research` now displays the latest saved Fed/SEC evaluation drafts with their language, model, quality failures, source excerpts, linked facts, dates, numbers, keywords, and immutable review history. Reviewers can explicitly start a review, save an edited revision, and rerun the existing deterministic quality gate. Each revision is stored in the append-only operations DB table `article_editorial_versions`; the original evaluation DB version remains unchanged. Review pass is editorial only and never grants Blogger publication permission. No reviewer activity is synthesized automatically, all revisions keep `publish_ready=false`, and actual Blogger writes remain blocked.

Migration 029 creates the append-only review progress and editorial revision records. Apply it with `scripts/migrate.py` before using the new review controls. The current 3100 Dashboard process may need a planned restart to serve the updated UI; this phase did not interrupt an existing session.

## Phase 5-A manuscript editing

`/research` includes a manuscript manager for stored Fed/SEC drafts, with language/blog/category/status filters, title search, modified-time ordering, original and revision comparison, evidence/quality details, and human review history. A human editor can save a new version with H2/H3, lists, emphasis, HTTPS links, SEO description, Blogger labels, a locale-matched blog target, and a planned KST publication time. The server sanitizes HTML and re-runs the existing quality checks; stale base versions receive a conflict instead of overwriting another editor's work.

Preview uses a sandboxed iframe. Publication intent and planned time are metadata only: they do not enqueue real publication. If an actual Blogger post mapping exists, its ID is shown so a future approved edit can target the existing post. This phase does not enable Blogger writes, publishing approval, automatic publishing, or `publish_ready`.

Migrations 030–032 add append-only editor metadata, bind edits of an already published source version to its recorded Blogger blog/post identity, and store the optimistic base-body hash. Back up the dedicated database before `scripts/migrate.py`. Backup and isolated restore steps are in [the operations runbook](docs/operations/runbook.md). The current Dashboard listener is left running when a session-safe restart cannot be verified; use the documented planned restart steps after preserving editor state.

Windows 로컬 다국어 Blogger 운영 에이전트입니다. Phase 1 기반을 유지하며 Phase 2에서 읽기 전용 Google OAuth, Blogger 정보·ID·게시글 조회, 로컬 불변 콘텐츠 버전 관리와 API 감사 이력을 추가했습니다. 운영 Blogger 쓰기·자동 발행·유료 AI 호출은 계속 차단됩니다.

## Phase 5 trend discovery status (2026-10-27)

`/research` supports manual Google Trends Trending Now RSS collection for KR, US, JP, TW, HK and SG through the shared external-call policy. The live fetch is metadata-only, bounded, audited and stored as an immutable trend observation, separate from factual research sources. Google does not explicitly supply a rank in this RSS representation, so the application stores no rank; the source-provided traffic label is kept as text. Auto collection is off. Migration 035–036 must be applied through the reviewed database migration process before the operations database can persist these observations; it has only been verified in the isolated test database in this change.

The collector does not automatically select a topic or treat trend data as article evidence. Article generation still requires multiple current, reviewed, topic-relevant factual sources and must pass the existing quality gate. No production manuscript-generation provider is currently attached. Historical Qwen3 evaluations remain available as read-only records; they are not executable. No generated article was submitted to Blogger as part of this work.

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
Database-backed pytest application calls use the local `woori_blog_agent`/`woori_app` identity and forced rollback; migration tests use a disposable schema under an outer rollback. The suite verifies that application test writes do not persist. It never deletes audit history.

See [architecture](docs/architecture/overview.md), [operations](docs/operations/runbook.md), [audit](docs/audit/events.md), [decisions](docs/decisions/0001-foundation.md), [development record](docs/development/P1-001.md) and [AGENTS.md](AGENTS.md).

## Multilingual configuration
Open http://127.0.0.1:3100/config to manage languages, multiple blogs per language, country profiles, policy schedules, categories and glossaries. The initial four user-provided Blogspot addresses are registered. Google Blog IDs stay NULL until user-consented API verification succeeds in /blogger. Registering a URL alone makes no external request. API/worker startup never loads administrator or migration-owner credentials.

Apply updates using `.venv/Scripts/python scripts/migrate.py` (latest version: 33). Migrations 001–004 are unchanged. Existing version IDs/content and audit records are preserved. Back up the dedicated database first. Configuration, application, and migration tests roll back synthetic records.

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



## Research and manuscript generation status

The research API and dashboard continue to support source collection, evidence packages, deterministic quality checks, editorial review, Blogger HTML/SEO previews, and Manual/Auto publication policy configuration. No in-process production manuscript-generation provider is connected. Synthetic Mock output is test-only. Official Codex desktop Scheduled tasks may write Research Package-based draft envelopes into the local scheduled-import inbox; a probe file write was confirmed on 2026-10-29, while manuscript generation and Import have not yet completed end to end. Internal generation APIs remain fail-closed.

The project no longer installs, starts, monitors, or stops Qwen3/llama.cpp. Historical Qwen evaluations, original articles, research packages, and audit records remain preserved and visible as stored records. A separate official Codex desktop Local Scheduled task can author a review-held draft file from an existing Research Package; this external task is not an in-process generator and does not bypass Import, review, rights, eligibility, or Blogger gates.

Run the API, dashboard, and collection worker through the existing project scripts when needed; there is no local model server startup step.

## Zero additional cost
All external requests pass through the closed provider allowlist in `services/api/woori/external_policy.py`. Paid AI, metered services, paid data, proxies, hosting and cloud services are blocked. Free quotas are hard stops; a 429 never triggers retries or provider fallback. Blogger reads are blocked until the Google Cloud project's billing status is verified. The authenticated research state reports provider blocks and suspicious credential variable names only. See [the cost and provider review](docs/operations/zero-cost-policy.md).
## Evidence-led generation pipeline

Research generation runs through persisted source, evidence, outline, section, localization, claim, SEO, and draft-persistence stages. Inspect per-attempt inputs, outputs, source links, validations, retries, and timings in the authenticated `/research` dashboard. Machine checks do not approve semantic truth or naturalness; uncertain versions remain `quality_held` and unpublished. See [the staged pipeline architecture](docs/architecture/pipeline-stages.md), [schema model](docs/architecture/data-model.md), and [Phase 3.7 source review and evaluation record](docs/development/P3-7-001.md).

## Evidence-preserving localization

Current source excerpts, reviewed source language, fact snapshots, approved glossary revisions, and per-language localization evaluations are stored separately and append-only. Deterministic checks protect numeric/date values and `/research` displays stored values beside each source excerpt. Original-language excerpts do not count as target-language prose. Cross-language generation remains held because no production translation provider is attached. The screen shows stored source/output comparisons, glossary revisions, and review status. See [the localization architecture](docs/architecture/evidence-localization.md), [Phase 3.8-B record](docs/development/P3-8B-001.md), and [measured evaluation](docs/development/P3-8B-evaluation.json).


## Phase 3.8-C1 finance/stock article evaluation

Historical source-backed evaluations used Federal Reserve releases and SEC EDGAR filings/XBRL facts. Retrieval timestamps, per-claim fact ledgers, saved drafts and machine checks remain available in `/research`; new production drafts are not generated until an approved provider is attached. The recorded C1 run is in [the evaluation artifact](docs/development/P3-8C1-evaluation.json); quality failures remain held and require editorial review. No Blogger write or paid API path is enabled. See the [architecture](docs/architecture/complete-articles.md) and [operations guide](docs/operations/live-research.md).

Phase 3.8-C2 adds append-only rechecks and preserves future bounded JSON/schema failure excerpts locally. Recheck historical output without regeneration using `.venv/Scripts/python scripts/recheck_article_quality.py`; it refuses to overwrite its evaluation artifact and never promotes drafts. See [C2 regression output](docs/development/P3-8C2-regression.json) and [the development record](docs/development/P3-8C2-001.md).
# Phase 3.8-C3 fact-first evaluation

The evidence architecture retains exact source spans in `evidence_facts`, citation links and per-fact checks in immutable generation-stage records. Historical C3 model runs are preserved as records; the retired local inference runner is no longer available.


## Phase 3.9 operations check

The dashboard reports the research worker heartbeat as current only when it was observed within 45 seconds; missing or stale heartbeat is shown as unknown/stale. Evaluation summaries come from stored PostgreSQL rows. To append a deterministic, zero-AI recheck of the saved Phase 3.8-C1 batch, run `.venv/Scripts/python scripts/run_phase39_quality_evaluation.py` from PowerShell. It preserves the source rows, writes new immutable evaluations and a unique artifact, and leaves `publish_ready=false`.

## Phase 3.9-S evaluation safety

Operations and evaluation have separate daily quotas, with shared global resource limits. Phase 3.9-T created a physically separate local evaluation database and verified the identity guard; actual C3 inference remains subject to its per-language quota and global resource checks. Do not manually reset quota or run evaluation against the operations database. `scripts/verify-worker-isolated.py` runs a diagnostic-only real Worker against a temporary isolated schema and records its results under `docs/development/`.
# Isolated C3 evaluation (Phase 3.9-T)

The local evaluation database is provisioned separately from `woori_blog_agent` by `scripts/provision-evaluation-database.py`. Its snapshot excludes OAuth, Blogger connection/API, publishing, search-performance, and heartbeat rows. Credentials are written only to ignored `.env.evaluation*` files. The dashboard reads evaluation drafts through the separate read-only `woori_eval_reader` role when `EVALUATION_DATABASE_URL` is configured.

Phase 3.9-T evaluation artifacts are historical and preserved under `docs/development`. Local Qwen/llama.cpp setup and evaluation commands have been retired. The project has no in-process production manuscript-generation provider. The separately configured official Codex desktop Local Scheduled export is allowed for draft-file creation, but only a real Research Package-based envelope and Import receipt prove manuscript delivery; it does not enable review, auto eligibility, or Blogger writes.


### Publication workflow (simulation only)

Open `http://127.0.0.1:3100/publishing` to inspect blocked requests and run an offline Fake Publisher simulation. It cannot approve content or publish to Blogger. Real Blogger writes and `publish_ready` remain disabled in code and schema. Schema migration 025 is applied by `scripts/migrate.py`.


Phase 4-B keeps scheduled jobs simulation-only. To process one isolated fake job, run `.venv/Scripts/python.exe scripts/publication-worker.py --evaluation`. The worker checks database isolation before starting. Real Blogger writes remain disabled; Blogger reconciliation is read-only and its live API result is not verified by mock tests.


## Phase 4-C status (2026-10-27)

`/research` provides an append-only human editorial review workspace for the four machine-passed Federal Reserve C3 drafts. Editorial approval now requires positive human checks and remains separate from Blogger publication authority. The Phase 4-D readiness table reads current DB/API state and cites historical isolated Worker evidence. Blogger API reads remain blocked because its per-call pricing/free allocation and project billing attachment could not be verified; SEC C3 inference remains quota-gated. Blogger writes, automatic publication, and `publish_ready` remain disabled. See [P4-C-001](docs/development/P4-C-001.md), [P4-D-001](docs/development/P4-D-001.md), and [the corrected Phase 4-D evaluation record](docs/development/P4-D-evaluation-correction-20261027.json).

## Phase 4-K model comparison

The Phase 4-K model comparison is a historical evaluation record. Local Qwen3 execution and model overrides have been retired; saved comparisons remain read-only. `/research` compares saved Fed/SEC evaluation runs by source, language, model and measured quality. The 2026-10-27 comparison was stopped after repeated held localization checks, so the candidate has no full zh-CN result and is not promoted. All evaluation drafts remain unpublished, require human review, and keep `publish_ready=false`. See [the Phase 4-K evaluation](docs/development/P4-K-results.json), [development record](docs/development/P4-K-001.md), and [pinned model policy](docs/operations/zero-cost-policy.md).

## P5-CONTENT-001: trend research packages

`/research` can group exact query observations within one geography, propose cross-region event matches for human review, apply a versioned publication-value triage rubric, and create immutable Research Packages from existing current reviewed sources and source-span-verified facts. Query clusters do not establish event identity. Scores never approve content. Packages without sufficient independently reviewed evidence remain `insufficient_evidence`; all packages retain human-review-required and `publish_ready=false`.

Migrations 037?039 have been verified on the isolated `woori_blog_agent_test` database only. No operations DB migration was applied. Actual US/JP/TW/HK/SG RSS requests returned ten observations each; RSS did not supply ranks, so rank is null. Across those plus the prior KR sample, all current candidates remain held because the test DB has no topic-linked reviewed sources/facts. No article or Blogger draft was generated.
