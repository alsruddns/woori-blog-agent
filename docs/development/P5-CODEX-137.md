# P5-CODEX-137 — Google Trends authoring and Blogger LIVE integration

## 작업 기록

- 작업 시작: 2026-11-05 00:40:52 KST (`agent.work.started`, audit ID 356622)
- 시작 브랜치/HEAD: `develop` / `eacdb2d814465278af9e0528a51fb1091b63ccf6`
- 시작 `origin/develop`: 시작 HEAD와 동일
- 운영 DB schema / automation revision: 91 / 23
- 시작 시 기존 stash: `P5-CODEX-099-101 interrupted implementation before startup repair 2026-11-01` (보존)
- 변경 사유: 수집은 정상인데 최근 Google Trends 작성 요청이 전부 실패하고, Trends 발행 정책이 Draft 또는 미설정 상태라 생성부터 LIVE 큐까지 운영 연결이 끊겨 있었다.
- 기존 상태: 6,720개 Observation, 최근 24시간 기준 기준값 5,000; 50개 Trends 작성 Job 전부 실패. 43 `json_schema_invalid`, 6 `insufficient_evidence`, 1 `web_research_not_observed`. Trends Import/Receipt 0건. EN/JA/KO Trends 정책은 `draft`; DE/pt-BR/VI 정책은 없음.

## 운영 기준선

- Google Trends collector enabled, 30분 간격, 14개 지역 설정을 확인했다. 최근 24시간 672개 지역 수집 회차가 성공했고, 14개 지역마다 48회씩 성공했다. 6,720건 모두 검색량 하한값을 보유했다. 최신 수집은 2026-11-05 01:00:35 KST였다.
- 자동 작성 검색량 하한은 5,000이다. P135 실패 사례 `IN / black friday sale ps5 / 2026-11-04 20:00 KST`는 읽기 전용으로만 확인했고 재평가·재실행하지 않았다. P135 기록에 남은 수집 당시 요청 미생성 원인은 시간당 자동 작성 슬롯 소진이었다.
- P136 설정은 revision 23, `AutoMode=auto`, `AutoPolicyActive=true`, `operations_auto_approved=true`, `blogger_write_mode=public_write_approved`, 15분 간격, KST 일일 상한 100건이다. 활성 Blogger 6개는 EN·KO·JA·DE·pt-BR·VI이며 `zh-CN`은 비활성이다.
- Publication Worker PID 36140과 Research Worker PID 21596은 heartbeat 정상이다. 운영 API PID 37816, Dashboard PID 6444. 전체 기준선에서 현재 진행 중 Research Job 0, Publication LIVE queued/running/uncertain 0, in-flight write 0이었다.
- 최근 24시간 Trends Publication Job은 기존 Draft 19건(성공 Draft 3, permission 실패 15, 폐기 차단 1)뿐이었다. 새 Trends LIVE Job은 없었다. 기존 24개 scheduled Import는 이전 검증대로 `awaiting_human_review`이며 변경하지 않았다.
- 최근 LIVE 기록 6건의 마지막 시각은 2026-11-04 16:45:53 KST로 P136 승인 시각보다 앞선 이력이다. 이번 점검에서 Blogger POST/PATCH/DELETE는 실행하지 않았다.

## 확인한 원인과 수정

1. Codex ChatGPT 인증 CLI 실행은 실제 동작했다. 실패의 주 원인은 모델이 미개봉 출처에 날짜만 있는 `observed_at`을 반환하면 `TrendArticleResult`의 timezone 검증이 실패하는 순서 문제였다. 기존 `make_envelope()`의 미개봉 출처 제거는 모델 결과 검증 뒤에 있어 도달하지 못했다.
2. 미개봉 출처와 그 출처만 인용한 문단·claim·event-focus 참조를 schema 검증 전에 제거하도록 했다. 열린 URL의 실제 수집 시각만 사용한다. 근거가 충분히 남지 않으면 `source_not_opened_in_this_run`으로 실패하며, 미개봉 출처의 날짜를 시간대로 꾸미지 않는다.
3. 성공적으로 검증된 Trends 결과는 기존 snapshot writer를 사용해 `.local/keyword-import/research/*.research.json`으로 원자적·불변 저장한다. 원고 ready 파일은 기존 exclusive handoff를 유지한다.
4. Trends API Import 뒤 `.local/keyword-import/import_receipts/*.json`에 해시·Import/Content Version ID·평가 오류·`blogger_write_performed=false`를 저장한다. Receipt 저장 전에는 Job을 Import 성공으로 전이하지 않는다. Receipt는 재실행 시 내용이 동일할 때만 멱등 처리한다.
5. P136의 기존 공개 LIVE 승인에 기록된 Blogger record ID와 정확히 일치할 때만, Trends 정책에서 과거 테스트 게시 시각을 별도 요구하지 않도록 했다. 이 경로는 test post를 만들지 않는다. 연결된 Blogger writer OAuth, 최근 읽기 전용 ID 확인, 기존 zero-cost approval, 명시적인 Trends 정책 요청/확인, 현행 정책·중복·권리·공통 writer gate는 그대로 요구한다.
6. 이미 운영 설정된 DE/VN authoring 매핑이 Trends LIVE 정책에서도 사용되도록 API/worker 허용 목록을 14지역으로 확장하고 순차 schema migration 092를 추가했다. `zh-CN`은 추가하지 않았다.
7. 전체 회귀에서 현재 코드와 맞지 않는 오래된 테스트 기대값을 정정했고, 승인된 상위 용어가 부분 엔티티를 포함하는 경우에도 localization entity 검사를 통과하도록 수정했다.

## 변경 파일

- `services/api/woori/keyword_jobs.py`
- `services/api/woori/trends_publication.py`
- `services/api/woori/publications.py`
- `services/api/woori/localization.py`
- `scripts/092_trends_de_vn_publication_geos.sql`
- `scripts/migrate.py`
- `scripts/provision-test-database.py`
- `services/api/tests/test_keyword_authoring.py`
- `services/api/tests/test_trends_publication.py`
- `services/api/tests/test_live_research.py`
- `services/api/tests/test_p096_operations.py`
- `services/api/tests/test_p4d_readiness.py`
- `services/api/tests/test_pipeline.py`
- `docs/development/P5-CODEX-137.md`

## 검증 결과 (코드/격리 환경)

- 집중 Trends/Import/정책/마이그레이션 테스트: 35 passed.
- 전체 API 회귀: 920 passed (격리 test DB; 운영 DB 쓰기 없음).
- API Ruff: 통과.
- 변경 API 모듈 mypy: 통과.
- Dashboard ESLint, typecheck, isolated production build: 통과. 빌드는 `.next-p5-p137`에 분리해 실행했고 `next-env.d.ts`와 `tsconfig.json` 원본을 복원했다.
- 격리 test DB는 schema 92까지 provision 완료. schema 92는 DE/VN을 허용하며 기존 정책/Job을 생성하지 않는다.
- 운영 DB schema는 이 개발 기록 작성 시점에 91이다. 운영 migration 및 코드/Worker 반영은 아직 수행하지 않았다.

## 운영 반영 전 남은 단계

- 기존 backup/restore 절차를 실행해 schema-91 운영 백업 아카이브 검증 및 격리 restore를 완료했다. 새 migration 092는 운영에 적용하지 않았다.
- 기존 운영 반영 검증 스크립트 실행, 운영 schema migration, API 인증 관리 경로를 통한 6개 Blogger Trends LIVE policy event 기록, 4개 서비스의 정상 종료·재기동, 실제 Worker 적용 revision과 HTTP/heartbeat 재확인이 남아 있다.
- 다음 신규 수집 회차에서 작성 요청→Research Worker→snapshot→원고 파일→Import Receipt→LIVE queue가 실제로 연결되는지 아직 확인하지 않았다. 현재 신규 회차의 실제 작성 Job은 기존 코드로 실패했고, 과거 회차를 다시 실행하지 않았다.
- Google Blogger 쓰기 0건, 테스트 게시/초안 0건, 유료 AI/API 호출 0건.
- 커밋/푸시 및 완료 감사 ID는 운영 반영 후 이 문서의 후속 기록에 추가한다.


## P5-CODEX-137 follow-up: fresh-slot failure and correction (2026-11-05 KST)

- After the initial implementation reached operations schema 92 and code commit `64af1fccae72d5117287923e87a3aff09c151fe9`, the approved Trends LIVE policy was recorded for the six active blogs through the authenticated management route. Policy event IDs 4?9 target only EN (AU, CA, GB, IN, PH, SG, US), KO (KR), JA (JP), DE (DE), pt-BR (BR), and VI (VN). The publication policy event did not issue Blogger writes.
- The new 01:30 KST collection slot completed successfully for all 14 configured regions. Two current-slot authoring requests were created and polled by Research Worker. Both authoring Jobs reached `article_schema_invalid` before snapshot/file/import creation. The recorded Pydantic error was missing `event_focus` in the Trends Import article contract. No prior slot was replayed.
- Root cause: the generation path extracted `event_focus` for immutable snapshot/audit metadata and then omitted it when passing the article to the Import envelope builder, whose Trends schema requires the field.
- Correction: retain the extracted `event_focus` in the article passed to Import; add a regression assertion reproducing the snapshot extraction boundary. Files changed: `services/api/woori/keyword_jobs.py`, `services/api/tests/test_keyword_authoring.py`.
- Verification after correction: focused authoring tests 17 passed; full API suite 920 passed; Ruff passed; mypy passed. Dashboard lint/typecheck/build previously passed on the same Dashboard source and it is unchanged by this follow-up.
- At this checkpoint the source fix is tested but has not yet been committed or applied to runtime; next operation is commit/push and the approved four-service graceful reflection procedure. No test article, Import, publication queue item, paid AI call, or Blogger write was created.


## P5-CODEX-137 follow-up: Import success and final wire-gate correction

- After commit `1c14618856f7d57b40e0fef22f1b7ec215528e04` was applied to all four services, the new 02:00 KST slot again collected 14/14 regions successfully and created two current-slot requests. The `gift nifty` request correctly ended `insufficient_evidence`; no content was fabricated.
- The `rice krispies recipe change` request ran through Research Worker, created an immutable Research Snapshot (`.local/keyword-import/research/10f6a8ba-4ade-4e5e-b17d-3a1aab783129-e341cdcf53f6f6b8.research.json`), wrote a unique manuscript envelope, imported it as review-held `codex_trends_export`, linked the native Content Version, and created Import Receipt `.local/keyword-import/import_receipts/10f6a8ba-4ade-4e5e-b17d-3a1aab783129.json`. The receipt records `claim_verification_status=unverified` and `blogger_write_performed=false`.
- The publication policy correctly recorded review gaps as follow-up items and created a current Trends LIVE job. At the wire, however, `automation_controls.job_permitted()` re-ran generic manual readiness, promoting review gaps into `quality_review_required`; the attempted operation was blocked locally as `authoring_only_blogger_writes_suspended` before an outbound Blogger POST (HTTP status null, no remote post ID). This is the precise reason the job failed; there was no public post.
- Correction in progress: for running `google_trends` auto grants, the last-moment `quality_ready` check now uses `trends_publication.validate_trends_job()`?the same fail-closed Trends blocker policy used for queue admission?while keeping ordinary review gaps as follow-ups. Non-Trends origins continue using the existing generic readiness check. A regression test asserts the Trends-specific path is used. The failed 02:00 publication job is preserved and will not be automatically restored or retried.
- Tests after this correction: `test_publication_origin_controls.py` 35 passed; full API suite 921 passed; Ruff passed; mypy passed. The code change is not yet committed or applied at this checkpoint. Dashboard source is unchanged; its ESLint/typecheck/isolated production build passed in the prior verified reflection.

## P5-CODEX-137 final operational closeout (2026-11-05, Asia/Seoul)

- Start: `develop` at `eacdb2d814465278af9e0528a51fb1091b63ccf6`; end source revision: `170f17ee24638a5092af45a9ddc9e7ca3e9952af`. Operations DB schema is 92; automation/settings revision remains 23. The P135 2026-11-04 20:00 KST observation was only diagnosed; no historical slot or failed Job was replayed.
- Follow-up blocker: the 02:00 and 02:30 current-slot Trends Jobs imported and entered the LIVE queue, but all three Trends wire operations (`create_live`, `create_draft`, `publish_draft`) lacked the exact running `AUTO_JOB` context required by the write guard. Two actual LIVE attempts ended locally as `authoring_only_blogger_writes_suspended` with HTTP status and remote post ID absent. Added the exact job-bound context together with the existing scoped Trends publication context for these three operations. The terminal failures were preserved and not retried.
- The 02:30 fresh-slot `aek – real madrid` candidate failed `article_schema_invalid` because its factual output had no valid source citation. The other 02:30 candidate imported review-held; the existing DE/DE, pt-BR/BR and VI/VN country policies were absent and caused `publication_policy_missing`. Added only those three policy rows for the existing six-blog authorization scope, through the existing configuration route. Each remains `auto_publish_allowed=false`; no Blogger was added and no old Import was changed.
- Regression: `test_trends_post_edit.py` now asserts the exact current Publication Job is bound at each Trends write entry point. Focused test: 8 passed. Full isolated pytest: 921 passed. Full Ruff: passed. Changed Publication Worker mypy: passed. Dashboard ESLint and TypeScript typecheck: passed; isolated production build passed. A broader mypy run reports three errors in untouched modules `grounding.py`, `topics.py`, and `worker.py`; no changes were made to those files. Pytest emitted a non-fatal cache permission warning for the shared `.pytest_cache` directory.
- Official `scripts/apply-verified-changes.ps1 -Apply -Confirm:$false` completed for API and Publication Worker. Per the task's four-service restart requirement, all four services were then stopped gracefully with no forced termination and restarted using the existing scripts. API health and Dashboard `/research` both returned HTTP 200. Final processes: API PID 27168, Dashboard PID 30216, Research Worker PID 26460, Publication Worker PID 37292. Both Worker heartbeats are fresh; Publication Worker applied commit `170f17ee24638a5092af45a9ddc9e7ca3e9952af` and reports `AutoMode=auto`, `AutoPolicyActive=true`.
- New 03:00 KST slot: all 14 regions succeeded with 10 observations each (140 total, all with stored volume lower bounds). The enabled threshold remains 5,000. Two threshold-authoring requests were emitted; one stopped as `insufficient_evidence`, and one was handled through `codex_exec_chatgpt`, with no paid AI API. It saved immutable snapshot `.local/keyword-import/research/c69531c1-eca5-4771-b5dd-2be93566675e-18e9a63500bc2004.research.json`, unique ready manuscript `.local/keyword-import/ready/c69531c1-eca5-4771-b5dd-2be93566675e.ready.json`, imported as `codex_trends_export`, and saved `.local/keyword-import/import_receipts/c69531c1-eca5-4771-b5dd-2be93566675e.json`. The receipt/import correctly retain `awaiting_human_review`, `generation_ready=false`, and `publish_ready=false` with unverified claims; no status was fabricated.
- The imported Japanese/JP manuscript generated Trends Publication Job `ed31a7f8-9d3a-4ade-9ab2-72459caea63a`. Existing sanitization removed quoted blocks and the common policy wrote prepublication follow-up items for incomplete source/claim verification, rights review, quality, and SEO. The LIVE job passed current duplicate, scope, idempotency, interval, daily-cap and write gates. Blogger returned HTTP 200 and verified readback HTTP 200; the immutable publication record is `LIVE`: remote post `1262983714088965498`, URL `https://trend-ja.blogspot.com/2026/11/e-tax.html`, KST 03:04. This is one authorized operational LIVE post, not a test post. Zero test posts/drafts, zero paid AI/API calls, zero historical retries.
- Current operating scope verified: exactly six active Blogger languages EN, KO, JA, DE, pt-BR, VI; zh-CN denied/inactive. `configured_mode=auto`, `operations_auto_approved=true`, `blogger_write_mode=public_write_approved`, `AutoMode=auto`, `AutoPolicyActive=true`; global LIVE interval 15 minutes, KST daily limit 100, ScheduledDailyLimit 100, and scheduled → manual → Trends priority remain recorded in revision 23. Emergency stop and API restriction are false. Existing scheduled Imports, OAuth mappings, post history, and failed Jobs were preserved.
- Actual current-slot counts: 14/14 regional collection runs; 140 observations; 2 threshold authoring requests; 1 evidence-held generation failure; 1 Research Job imported; 1 immutable Research Snapshot; 1 ready manuscript; 1 Import Receipt; 1 Trends LIVE queue Job succeeded; 1 successful operational Blogger LIVE write. The two earlier failed LIVE Jobs remain failed and were not retried.
- Start and completion audit events: `agent.work.started` ID 356622 and append-only `agent.work.completed` ID 359867. Completion audit links code commit `170f17ee24638a5092af45a9ddc9e7ca3e9952af` and records the new-slot counts and one verified operational LIVE post.
- Changed files in the final follow-up: `services/api/woori/publication_worker.py`, `services/api/tests/test_trends_post_edit.py`, and this development record. Code commit `170f17ee24638a5092af45a9ddc9e7ca3e9952af` was pushed to `origin/develop`. This documentation closeout is committed separately. Existing stash and pre-existing untracked files were left in place.
- Remaining issue: the full-repository mypy command is not clean because of the three untouched-module errors above. Individual Trends/Publication Worker checks and the complete pytest, Ruff, Dashboard lint/typecheck/build checks passed. The published manuscript remains factually and rights review-held as recorded; follow-up warnings were not converted into verification or approval.
