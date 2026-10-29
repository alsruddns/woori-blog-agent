## Current runtime baseline — P5-CODEX-038 (2026-10-29)

- Qwen3 and llama.cpp execution, model download, status, and lifecycle management have been retired from this repository. Older phase notes below that describe local inference are historical records, not current instructions.
- Existing model files, shared executables, saved articles, Research Packages, quality evaluations, and audit records are preserved. Never delete them as part of code cleanup.
- No in-process production manuscript-generation provider is attached. Mock generation is test-only; internal generation APIs and project-owned generation schedules fail closed.
- Official Codex desktop Scheduled tasks may be used as an external local-project manuscript authoring/export path. A scheduled execution wrote the local probe `.local/gpt-scheduled-import/probe/scheduled-test.json` at 2026-10-29 15:51 KST; this verifies probe-file writing only. It does not verify Research Package article generation, ready-envelope delivery, Import, quality/rights approval, auto eligibility, or Blogger publication.
- Scheduled runs use the account's default sandbox/approval settings and any administrator-enforced requirements; use the narrowest local-project permissions. The computer and Codex desktop must remain available for local files. Create/manage tasks in the desktop Scheduled UI; repository code, Codex CLI, and the IDE extension do not register them.
- Codex scheduled authoring must read the selected existing Research Package and existing import schemas, write only a complete UTF-8 envelope through `incoming/` then atomic rename into `ready/`, and fail without a ready file when evidence or schema requirements are unmet. It must not call Blogger, modify the database, run Git commit/push, or grant approval. The existing Import Worker and all quality, editorial, rights, publication, and Blogger gates remain independent and fail closed.
- No in-process AI Provider is connected; the external Codex scheduled export is not an API Provider and must not set `provider_connected`, `generation_ready`, `auto_eligible`, or `publish_ready` by itself.
- Collection, evidence validation, HTML/SEO, editing, human review, publication preparation, and the existing Manual/Auto publishing safeguards remain independent capabilities.

# Codex 개발 규칙
모든 후속 Codex 작업에 적용한다.

## Rule 1. 개발 기록 필수
모든 기능 추가·수정·삭제·버그 해결에 작업 ID, 작업 일시, 변경 사유, 기존 문제, 변경 목적, 변경 전 상태, 변경 후 상태, 수정 파일 목록, 테스트 결과, 커밋 해시, 관련 문서, 남은 문제를 docs/development에 기록한다. 자기 참조 해시는 후속 기록 또는 git log로 연결한다.
## Rule 2. 운영 감사 로그 필수
모든 에이전트 실행과 주요 상태 변경을 PostgreSQL에 기록한다. 작업 시작·완료, 키워드 선정, 자료 조사, 콘텐츠 생성·수정, 다국어 번역, SEO 검사, 발행 승인, 예약·실제 발행, 실패·재시도, 설정 변경, 검색 성과 분석을 포함한다. 일반 관리 기능으로 감사 이벤트 수정·삭제 금지. 정정은 새 이벤트를 추가한다.
## Rule 3. 콘텐츠 버전 관리
수정마다 새 버전을 생성하고 기존 버전을 덮어쓰지 않는다. 원본과 데이터베이스에 등록된 N개 언어·국가별 버전의 연결 및 전후 비교를 유지한다.
## Rule 4. Git 브랜치 정책 준수
main/develop만 사용한다. 개발·수정·리팩터링·테스트는 develop에서 진행한다. main 직접 개발 및 추가 브랜치 생성 금지. 완료 후 변경 확인, 테스트, 개발 기록, 파일 검토, `Type : [Scope] Description` 커밋, origin/develop 푸시, 결과 보고를 수행한다. 사용자 명시 승인 없이 main 병합·배포 금지. 원격 브랜치 삭제는 안전 확인 및 사용자 승인이 필요하다.
## Rule 5. 유료 AI API 호출 차단
기본 금지. 환경변수 누락·예외·재시도에서도 우발 호출을 차단하고 자동 테스트한다. 활성화는 별도 사용자 승인과 명시 설정이 모두 필요하다.
## Rule 6. Blogger 실제 발행 안전장치
초기 개발은 Mock 또는 테스트 블로그만 사용한다. Phase 2에서 승인된 운영 블로그 읽기 연결은 허용한다. 실제 생성·수정·삭제·자동 발행은 별도 승인 후 진행한다. 발행 실패·재시도·멱등성에 의한 중복 방지를 구현한다.
## Rule 7. SEO 및 콘텐츠 품질 검증
자동 발행 전 언어별 제목·본문 일치, 검색 의도, 사실·출처, 중복·유사성, 저작권, 언어별 메타데이터, 관련 게시글, 광고·검색 정책을 검증한다. 실패 시 발행 금지. Blogger에서 직접 설정 불가능한 SEO 기능을 구현됐다고 보고하지 않는다.
## Rule 8. 오류 및 장애 추적
실행 ID, 오류 유형·메시지·위치·시각, 재시도 횟수, 최종 상태, 해결 결과를 기록한다. 재시도 시 멱등성으로 중복 발행을 방지한다.
## Rule 9. 보안 및 민감정보 보호
OAuth 토큰·API Key·비밀번호를 코드에 저장하지 않는다. .env 등 민감 설정은 커밋 금지. 감사·실행 로그에도 인증 정보를 평문 출력하지 않는다. 관리 API 접근 제어와 루프백 바인딩을 적용한다.
## Rule 10. 변경 검증 및 보고
관련 테스트 실행. 전체 영향 변경은 lint·타입 검사·빌드·단위·통합 테스트 수행. 실패를 무시하거나 통과로 보고하지 않는다. 보고는 완료 기능, 변경 파일, 검증 결과, 실패·미완성, 개발 기록 위치, 커밋 해시, 현재 브랜치, 원격 푸시 결과, 후속 작업을 포함한다.

## 다국어 확장 영구 정책
- 초기 언어 ko/en/zh-CN/ja는 시드 데이터일 뿐이다. 언어 수·목록 또는 언어별 분기를 에이전트, API, Worker, 화면의 비즈니스 로직에 고정하지 않는다.
- BCP 47 코드 검증·정규화를 공통 모듈로 수행한다. 언어와 대상 국가는 별도 개념이며 국가별 생성·현지화·검색 의도·SEO·스케줄·카테고리·용어집 정책을 관리한다.
- 한 언어에 여러 Blogger 블로그를 허용한다. 콘텐츠 그룹은 N개 언어·국가별 현지화와 독립 버전을 가진다.
- 언어·블로그는 삭제보다 비활성화를 사용한다. 기존 콘텐츠·감사·발행 기록과 참조 관계를 보존하고, 역사적 언어 코드·블로그 URL/언어 등의 정체성을 덮어쓰지 않는다.
- 제공받은 블로그 주소는 설정으로 등록할 수 있으나 Blog ID를 임의 생성하거나 입력값만으로 연결 검증을 완료하지 않는다. ID는 추후 Blogger API getByUrl 등으로 확인한다.
- 신규 언어·블로그 등록은 자동 발행 허가가 아니다. 생성·번역·품질 검증 어댑터의 정확한 언어 지원, 실제 Blogger 연결, 테스트 발행 검증, 정책 활성화 및 별도 운영 승인을 모두 확인한다. 미지원·미검증·비활성 상태는 발행을 차단한다.
- Phase 1에서는 자동 발행 허용값과 실제 네트워크 호출을 계속 차단한다. Worker는 향후 활성 언어·블로그·국가별 정책·검증 상태를 DB에서 조회하여 대상을 결정해야 한다.
- 각 현지화의 키워드·제목·본문·메타데이터·출처 적합성은 독립 검증한다. 번역 관계는 콘텐츠 그룹 및 출처 버전으로 연결한다. hreflang은 테마/API 지원을 확인하기 전 구현 완료로 보고하지 않는다.
- 언어·블로그·관련 정책 변경은 변경과 동일한 DB 트랜잭션에 감사 이벤트를 기록한다. 비밀값은 감사 payload에 남기지 않는다.
- 스키마 변경은 순차 마이그레이션으로 수행한다. 원본 콘텐츠 값·UUID·감사 이벤트 보존, 재실행, 권한, 국가/언어 참조 무결성을 테스트한다. 적용한 마이그레이션은 수정하지 않고 후속 마이그레이션을 추가한다.

## Phase 2 OAuth 및 로컬 포트 정책
- 기본 실행 주소는 Dashboard http://127.0.0.1:3100, FastAPI http://127.0.0.1:8100, PostgreSQL 5432다. 다른 프로젝트가 사용하는 3000/8000 포트를 점유하거나 그 프로젝트를 수정하지 않는다.
- Google OAuth redirect_uri는 http://127.0.0.1:3100/api/blogger/callback 이다. 포트 변경 시 콜백 라우팅·프록시·Origin·쿠키·실행 스크립트·테스트·문서를 함께 검증한다. 브라우저는 동일 출처 Next 프록시만 사용하고 API의 교차 출처 접근을 허용하지 않는다.
- OAuth는 사용자 동의, 최소 blogger.readonly 권한, 일회용 만료 state와 브라우저 바인딩, PKCE를 사용한다. Google 비밀번호를 요청·저장하지 않는다.
- 토큰과 PKCE verifier는 외부 환경 키로 암호화 저장한다. 키와 OAuth client secret은 Git 제외 설정에만 둔다. 토큰·인증 코드·쿠키·원문 Google 오류를 로그나 감사 payload에 출력하지 않는다. 콜백 query 로깅을 비활성화한다.
- 읽기와 쓰기 클라이언트를 분리한다. 운영 쓰기는 환경변수로 해제할 수 없다. 쓰기 구현은 MockTransport에서만 검증하고 실제 Blogger POST/PATCH/DELETE 경로를 노출하지 않는다. 모호한 쓰기 실패는 자동 재시도하지 않고 멱등성 원장을 통해 차단한다.
- 실제 연결은 Google 응답의 ID와 등록 URL 확인 및 승인된 계정의 AUTHOR 읽기 확인 후 저장한다. OAuth 전에는 미연결로 표시하며, 취소·해제 시 연결 검증을 제거하고 과거 Blog ID와 콘텐츠·발행 이력은 보존한다.
- Mock OAuth/쓰기 검증과 실제 Google 읽기 검증 결과를 분리한다. 사용자 동의나 외부 설정이 없으면 실제 연결 완료로 보고하지 않는다.

## Phase 3 조사·생성 영구 정책
- 검색량·경쟁도·CPC는 실제 공급자 근거가 있을 때만 저장하며 NULL을 임의 수치로 대체하지 않는다.
- 출처 URL·게시/수집/유효 시각·근거·신뢰성·이용 권리·접근 정책·검토 이력을 추적한다. 정정은 새 출처 버전/검토를 추가한다.
- 사람 검토, 출처 진위·전송 경로 확인, 규칙 검사, 모델 평가와 의미적 사실 검증을 구분한다. 모델 자기평가만으로 승인하지 않는다.
- AI 생성 Provider는 현재 운영 연결되어 있지 않다. Mock은 파이프라인 테스트 전용이며, 원고 생성 기능은 별도로 승인·구현된 Provider가 연결될 때까지 사용할 수 없다.
- 작업 설정/프롬프트/자료/검토 스냅샷과 원본·현지화·콘텐츠 버전·SEO·실행 이력을 연결한다. 재시도는 저장한 타깃을 재사용하고 오래된 임대는 저장을 차단한다.
- 스케줄은 DB와 영속 전달 원장을 사용한다. CPU/RAM 수용 검사와 실행 옵션을 OS 수준 강제 자원 상한으로 표현하지 않는다.

## Phase 3.5 실제 추론·수집 정책
- Qwen3 및 llama.cpp 실행 경로는 제거되었다. 저장된 모델 평가 자료는 이력으로 보존하되 모델 파일·공용 엔진을 자동 삭제하거나 시작·종료하지 않는다.
- 새 in-process 원고 생성 Provider가 연결되지 않아 API 생성은 계속 fail-closed다. 다만 공식 Codex 데스크톱 Local 예약 실행의 파일 작성 probe는 2026-10-29 검증됐다. Research Package 기반 예약 초안 파일 작성은 기존 JSON 규격과 안전 지침에 따라 허용하되, 실제 원고 envelope·Import가 확인될 때까지 종단 간 생성 성공으로 표시하지 않는다.
- 수집은 고정 허용 RSS/API에 한정한다. 임의 URL fetch, 리다이렉트, 무단 대량 수집은 금지한다. 1MiB 응답 상한·시각·권리·호출 제한을 적용한다.
- Fed 공식 Board 본문의 전송 경로/시각/공공영역 사용 조건 확인은 자동 수용할 수 있으나 의미적 사실 검증 완료를 뜻하지 않는다. Wikidata CC0 메타데이터는 주제 후보이며 공식 발표/가격/영업/효능 근거로 자동 승인하지 않는다.
- 검증되지 않은 모델·언어의 일반 자동 처리는 차단한다. 명시적인 evaluation_only 작업은 품질 검증 선언 없이 시험할 수 있으며 결과는 quality_held로 보존하고 publish_ready=false를 유지한다.
- 모델별 동일 자료·프롬프트 조건의 측정과 실패를 보존한다. JSON 생성 성공, 언어 규칙 통과, 자연스러움과 사실 충실도를 구분한다. 측정하지 못한 GPU 이용률이나 처리 속도를 만들어내지 않는다.
- 스트리밍 취소는 해당 연결을 닫으며 전역 모델 프로세스나 다른 프로젝트를 임의 종료하지 않는다. 출처 개정 중 생성은 근거 재검사로 차단하고 재시도한다.

## Zero additional cost policy (permanent)
- The project must incur zero additional currency cost for external services or AI. No paid AI/API, metered API, paid data service, proxy, hosting, or cloud service may be called. An API key or paid account setting never grants permission.
- Every remote HTTP request must pass through the shared `woori.external_policy` provider/operation/host/method/path allowlist. Unknown or unreviewed providers fail closed; no environment switch may bypass the gate. Local loopback inference is separate and must use reviewed free licenses.
- Free provider quotas and local request caps are hard ceilings. On HTTP 429, quota exhaustion, terms/pricing change, or expired review, stop the task. Do not retry a quota response, switch providers, or upgrade tiers.
- Before each remote call, check for potentially billable credentials and billing/payment/proxy settings. If found, stop external execution and report variable names only; never expose values.
- Record every service's price basis, usage caps, terms, commercial-use conditions, license, and review date in `docs/operations/zero-cost-policy.md`. If price or terms are unclear, block by default. Re-review before monetized use or after provider terms change.
- Audit external calls with provider/operation/status/usage metadata only. Never log URL query strings, headers, bodies, tokens, credentials, or secret values.
- Add automated tests that prove paid/unknown providers, billable credentials, quota exhaustion, and paid fallback paths are blocked. Update the development record and cost policy when changing any integration.

## Phase 3.6 model evaluation and content quality (permanent)
- Treat local model output as untrusted. Split reviewed evidence into immutable source-linked facts, plan an outline, generate sections from that ledger, then run deterministic grounding/localization/SEO rules before creating a version.
- Keep source identity attached to every fact and require valid `[source:ID]` markers on every substantive factual paragraph. Preserve evidence-backed names, dates, and numbers; flag repeated paragraphs, unsupported names/URLs/numbers, and language/script mismatches.
- Distinguish syntax/heuristic/model checks from semantic fact verification and naturalness review. A model's self-evaluation never approves factual claims. Any failed or unverified quality gate remains `quality_held`; `publish_ready` stays false.
- Validate source URLs only through the exact shared outbound allowlist. A syntactically valid URL or a model-generated citation does not prove that a URL exists or that its content supports a claim.
- Compare model versions using identical, checksummed material, prompt, language, and scoring rules; retain output, errors, versions, and measured resource data. Do not claim GPU measurements when unavailable.
- Before loading a model, enforce available-RAM headroom and project-local disk limits. Run one inference model at a time and do not stop or alter other projects or system services.
- Model acquisition is limited to unauthenticated public files with reviewed free terms and pinned revision/SHA-256. Never download gated weights, use hosted inference, or fall back to a paid service.

## Phase 3.7 evidence-led pipeline rules
- Keep source collection, verbatim evidence extraction/validation, outline, section generation, localization, claim review, SEO quality, and draft persistence as separately identified and audited stages. Store the input/output, model/prompt version, source IDs, validation, timing, retry, and terminal status for each attempt.
- Only extract evidence spans that occur in the reviewed source revision. An evidence ID proves traceability, not truth or semantic support.
- Give each generated section only its assigned evidence IDs. Enforce bounded retries; failed checks remain held and cannot be promoted by model self-review.
- Retain detected source names, numbers, dates, and source IDs through localization. Country-specific claims require reviewed country-relevant evidence.
- Keep machine checks and human approval separate. If semantic entailment, language quality, rights, or freshness is uncertain, retain `quality_held` and `publish_ready=false`.
- Evaluation runs may not enable Blogger writes, automatic publication, or paid/metered services.

## Phase 3.8-B evidence-preserving localization rules
- Store source-span facts independently of localized wording, with stable fact/source identity, source language, exact excerpt, entity/numeric/date snapshots, and citation references. Only an exact span from a current reviewed source may be marked `source_span_verified`.
- Keep historical source language as `und` until a source review explicitly records BCP 47 language attribution. Never rewrite the source row to retrofit language metadata; append a review/fact/evaluation record.
- Treat original-language quotations as quotations in that source language. They cannot satisfy another target language's language check. Never render translated text as a verbatim source quote.
- Glossary terms are unapproved by default. Use a translated proper name as official only when an approved glossary revision records its source language, target language, official status, and translation source. Glossary revisions and localization evaluations are append-only.
- A future explicitly approved provider may process only supplied evidence excerpts or propose localized candidates. Validate numbers, dates, known entities, citations, URLs, language fields, repetition, and approved terminology; machine checks do not establish semantic equivalence or naturalness. No provider is currently attached.
- Before localization inference, protect every verified date span and numeric token with typed, unique placeholders alongside protected entity names. Require each placeholder exactly once, restore the exact evidence value, and reject collisions or leaked markers. Formatting normalization may compare equivalent representations, but never changes the recorded value; localized display conversion must be a separate deterministic step with its own tests.
- Compose localized drafts only from machine-checked fact spans. Any held/missing translation or unresolved claim blocks composition; semantic fidelity, naturalness, rights and editorial approval remain human review items. `publish_ready` remains false until separate human and operations approvals.

## Phase 3.8-C1 official-source article rules
- Financial and stock research may use the Federal Reserve's reviewed RSS/release pages and SEC EDGAR public submissions/companyconcept data only. SEC requests must include the configured contact in the User-Agent; fetch no arbitrary paths, companyfacts bulk files, attachments, or third-party filing assets.
- Preserve each actual provider retrieval time, filing/release date, period, accession, exact evidence excerpt, terms review, and use limits. Tie XBRL values to the same filing accession; never mix periods or imply a filing proves investment merit.
- Assess fact spans and finished articles separately. Every substantive article paragraph needs source markers; check numeric/date/name/script drift, repeated content, source overlap, title/body/search-intent fit and source freshness. Unsupported claims remain `quality_held`.
- Article length must follow evidence depth; do not pad narrow filings/releases. A machine-passed article still needs human semantic, naturalness, rights and editorial review. Keep every generated version and quality evaluation append-only and `publish_ready=false`.
- Every external and model attempt must retain its execution/batch ID, status, sanitized error category, elapsed time, model/call count, source/fact references, measured resource usage, quality checks and review status. Never log contact details, request headers/bodies, credentials, or tokens.

## Phase 3.8-C2 generation and verifier rules
- Re-evaluate stored output by inserting a new immutable evaluation row linked to its prior evaluation/version. Never update the historical version, evaluation, or audit event. If original model output was not retained, mark that failure not replayable instead of inventing an explanation.
- Retry structured-output JSON/schema failures at most once with a new fixed seed. Never repair missing factual fields or accept a partial parse. Store bounded parse-failure response excerpts and the full response hash in the immutable local DB failure-artifact table; audit only the hash, IDs, model, and sanitized error category.
- Keep thousands-grouping normalization semantics-preserving. Treat proper-name, numeric, date, language/script, citation, SEO-keyword, and internal-ID checks as separate gates with focused regression tests. A detector uncertainty does not grant content approval.
- Internal source citations may remain only in their designated citation marker; internal UUIDs and run identifiers must not appear in title, summary, or user-facing prose. Model failures remain failed/held; human semantic review stays separate.

## Phase 3.8-C3 fact-first localization rules
- Append reviewed, exact source spans to `evidence_facts`; retain source ID, BCP 47 source language, entity fingerprints, numbers, dates and citation IDs. Never assert semantic verification from span matching alone.
- Historical C3 outputs and fact spans remain immutable. No local provider is available; a future provider must localize registered fact spans and let the deterministic renderer attach source IDs and structure.
- Preserve per-fact machine checks and model-call metrics in stage output. Any unsupported claim, number/name drift, unapproved term, language failure, or missing source remains held. Meaning and naturalness require human review.
- Local model overrides, Qwen execution and model downloads are retired. Historical model identity and evaluation evidence are read-only; cleanup must not delete them.
- Evaluation-only drafts always keep `publish_ready=false`; test results never activate language verification, production generation, Blogger writes, or automatic publishing.


## Phase 3.9 ?? ?? ??
- ?? ?? ??? ??, ??, ?? ?? ??? ???? ?? ????? ?? ????????? ???? publish_ready? ???? ???. ???? ? append-only ?? ?? ?? ???? ????.
- Worker ?? ??? PostgreSQL heartbeat? freshness? ????. heartbeat ??????? ???? ???? ?? ???/????? ????. ?? ????? ??? ?? ???? ??? ????? ?? ??? ???? ???.
- ???? ?? ??? ???? ???, ???? ?? ??? ??? fixture ?? ??? ?? ??? ????. ?? ?? ?? ??? ?? ??, OS ???, Blogger ??? ?? fallback? ????.

## Phase 3.9-S quota and evaluation isolation rules
- Keep operational and evaluation daily quotas separate. Count each generation target once when it is created; failed or cancelled targets remain counted, while an idempotent retry or duplicate request does not create another counted target. Do not reset consumed usage manually.
- Apply the same global pause, resource, concurrency, CPU, RAM, disk, and bounded retry gates to every mode. Daily quotas reset at 00:00 Asia/Seoul, using an explicit timezone conversion independent of the PostgreSQL session timezone; evaluation quotas do not bypass operational or system-wide safety limits.
- Evaluation generation and evaluation Workers fail closed unless an explicit isolation flag is enabled, the evaluation database is physically distinct from the configured operational database, and the evaluation queue is filtered from operational work. Separate quotas alone are not sufficient isolation.
- Preserve heartbeat and audit state per Worker mode. Diagnostic testing must use an isolated schema/database and test-only queue, and must leave operational content and queues unchanged.


## Phase 4-M immutable editorial review policy
- Derive editorial review status only from explicit human review records and append-only review-start/revision events. Never fabricate a reviewer or mark an unreviewed article as passed. Editorial review is separate from Blogger publication approval.
- Save every human edit as a new immutable editorial version linked to the original evaluation and content version. Re-run the existing language, evidence, number/date, proper-name, citation, quotation, and SEO gates before recording it; failed revisions remain `quality_held`. Preserve original content and evaluations.
- Keep review events, revision metadata, quality results, body hashes, and audit records append-only. Keep `publish_ready=false`; no review action enables Blogger writes or automatic publishing.

## Phase 5-A manuscript editing and publishing preparation
- Keep evaluation originals and every prior editorial version immutable. Human edits create a new version with author, reason, source version, plain-text and sanitized HTML hashes, metadata, quality results, and an optimistic base-version check. A stale editor must receive a conflict and may not overwrite newer work.
- Human HTML is server-sanitized through a tag/attribute allowlist. Never render untrusted markup in the Dashboard DOM; previews must be isolated and sandboxed. Strip scripts, active embeds, event attributes, and unsafe URL schemes.
- Blogger labels, target blog, SEO description, and planned publication time are versioned editorial metadata. Target blog must be registered, active, and match the content locale. A publication mode or planned date is metadata only and must not enqueue a real publication.
- Default publication mode is manual. Editing approval, publication approval, and actual Blogger write permission are separate. Keep live Blogger create/update/delete and automatic publication blocked until a separate explicit operations approval; do not set `publish_ready=true`.
- If a published Blogger post ID exists, future edits must be modeled as updates to that same blog/post identity, not as a duplicate insert. Read-only synchronization is the only Blogger integration allowed before approval; never fabricate remote post IDs or treat Mock IDs as real.
- Preserve external service cost gates and append-only audit events for revisions, review decisions, publication state, and settings. Scheduling, preview, and editor saves do not bypass quality or human approval.

## Database-backed integration test isolation
- Tests that create content, jobs, revisions, or audit events must run in an explicitly disposable isolated database or inside a forced-rollback outer transaction. API and Worker connections used by the same test must share that isolation boundary.
- Tests must verify that operational content and audit counts remain unchanged after teardown. Never rely on test names, random keys, or later cleanup to make writes to the operational `.env` database safe.
- Do not delete leaked test rows from immutable operational tables. Diagnose and preserve them, then fix the test isolation before rerunning.
- Pytest requires the ignored `.env.test` and the dedicated `woori_blog_agent_test` database with `woori_test_app` and `woori_test_owner`. The app account must have no effective CONNECT privilege to `woori_blog_agent`; missing or mismatched identity fails closed before a database-backed test runs. Provision only project-prefixed test objects; never change another database or account.

## Phase 5-C local runtime and publication approval
- Manage only processes whose executable/command path and recorded checkout ownership match this repository. Check port owners and active connections before shutdown; request graceful exit and never force-kill a process or clear a live PID record. Unmanaged listeners require operator action in their original terminal.
- During pytest, application database connections must verify the expected local operations database identity and use an outer forced-rollback transaction. Direct migration tests must target a disposable schema under their own outer rollback. Do not rely on teardown deletes or fixture naming to protect operations data.
- Record publication approval as an append-only human event bound to the exact latest immutable editorial version and body hash. Approval requires a passing machine gate and an explicit positive editorial review for that version; edits invalidate applicability, revocation appends an event, and approval never changes `publish_ready` or enables live Blogger writes.

## Phase 5-G shared Blogger OAuth connection
- One connected OAuth grant with the exact `https://www.googleapis.com/auth/blogger` scope may serve Blogger reads and writes; do not add separate read/write OAuth foreign-key columns. Keep existing OAuth records and audit events. Do not infer or expose Google account identity unless the API explicitly verifies it.
- Before replacing the existing blog-to-OAuth mappings, pass the zero-cost provider gate, use the same existing OAuth connection to list accessible Blogger IDs, match every active registered blog ID and URL, and record an immutable verification event. A fresh verification and an explicit authenticated operator approval are both required before an atomic common-mapping update; record previous/new connection references. If cost is blocked or any blog does not match, preserve every current mapping.
- Do not create another writer OAuth flow while a connected full-scope connection or an unexpired writer consent flow already exists. Never delete old read or writer connections as part of common mapping. A shared OAuth mapping does not enable Blogger writes, automatic publishing, or `publish_ready`; the real write adapter remains disabled.

## Phase 5 editorial writing standard (permanent)
- Draft reader-centered explainers or expert columns, not administrative summaries or press-release rewrites. Lead with the reader question and evidence-based point; use topic-specific structure and avoid repeated caveats, filler, and internal workflow language.
- Separate sourced facts, attributed positions, and analysis. Explain implications only when they follow logically from reviewed evidence and label interpretation clearly. Never invent expert opinions, interviews, statistics, firsthand experience, or forecasts.
- Preserve proposed, planned, approved, enacted, and paid status distinctions. Localize institutions, units, and policy terms naturally while preserving verified meaning; cite factual paragraphs and paraphrase independently.
- Deterministic checks do not approve semantic accuracy, naturalness, rights, or publication. Quality failures remain held; human editorial review is required.
