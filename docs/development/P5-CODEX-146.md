# P5-CODEX-146 — 발행 목록에 Google Trends 검색량 표시

- 작업 일시: 2026-11-05 14:46 KST 시작
- 브랜치: `develop`
- 시작 HEAD: `1fe314635fc951646f59b66190efe3e642d3bfa0`
- 시작 감사 이벤트: PostgreSQL `agent.work.started`, ID `374299`
- 변경 사유: 발행관리의 검토 필요, 게시 완료, 실패·보류, 자동발행실패 목록에서 Google Trends 수집 원고의 검색량을 확인할 수 없었음.

## 구현

- 발행 목록은 기존 검증된 `origin_kind=google_trends` 및 `trend_request_id`를 사용해 해당 `trend_generation_requests.contract`의 `query`, `source_country`, `search_volume_raw`, `volume_kind`를 한 번의 일괄 조회로 연결한다.
- Dashboard 원고 셀에 `Trends 검색어 · 검색량 원본 표기 · 국가`를 표시한다. 수동/예약 원고에는 표시하지 않는다.
- 값은 Google Trends 원본 구간값(예: `5000+`, `10K+`) 그대로 보여 주고 정확한 검색 횟수가 아닌 하한 구간임을 설명한다. 값을 정확한 건수로 바꾸거나 추정하지 않는다. 과거 Trends 계보 또는 검색량 값이 없으면 `정보 없음`으로 표시한다.
- 이 데이터 표시 변경은 발행 적격성이나 발행 정책에 영향을 주지 않는다.

## 운영 데이터 확인

운영 DB `woori_blog_agent`에서 transaction-level read-only로 네 목록을 조회했다. 검색량 계약이 확인된 Trends 항목은 아래와 같다.

- 검토 필요: 전체 4건 중 Trends 3건
- 게시 완료: 전체 44건 중 Trends 24건
- 실패·보류: 전체 2건 중 Trends 2건
- 자동발행실패: 전체 5건 중 Trends 5건
- 샘플 원본값: `5000+`, `10000+`; `volume_kind=bucket_lower_bound; not internationally comparable`
- 읽기 확인 중 DB 변경 0건, Blogger 쓰기 0건

## 변경 파일

- `services/api/woori/publications.py`
- `services/api/tests/test_publications.py`
- `apps/dashboard/app/publishing/publication-manager.tsx`
- `docs/development/P5-CODEX-146.md`

## 검증 및 적용 상태

- 통과: `pytest services/api/tests/test_publications.py -q` — 53 passed. pytest cache 경고 1건은 캐시 경로 권한 문제였으며 테스트 실패는 없음.
- 통과: Ruff 대상 파일 2개
- 통과: `npm run lint`
- 통과: `npm run typecheck`
- 통과: `npm run build`
- 통과: `git diff --check`
- 운영 Read-only smoke: `list_publications`의 `review`, `published`, `held`, `auto_failure` 네 응답에서 실제 Trends 원본 검색량 라벨을 확인했다.
- 서비스 재기동 및 운영 배포는 하지 않았다. 코드 변경은 커밋·푸시 후 로컬 실행 서비스에 자동 반영되는지 별도로 확인하지 않았으므로 런타임 반영은 미확인이다.
- 구현 커밋: `8e104d2a5c05a10b816e0dc095d555eda922a434` (`Feat : [Publishing] Show Trends volume in publication lists`). 완료 감사 이벤트: PostgreSQL `agent.work.completed`, ID `374308`, 2026-11-05 14:48:24 KST.
- 개발 기록 후속 커밋 및 최종 브랜치 상태는 `git log -- docs/development/P5-CODEX-146.md`와 `git status`에서 확인한다.

## Operations deployment follow-up

- Deployment request and start time: 2026-11-05 15:05 KST; append-only `agent.work.started` audit ID `374962`.
- Source HEAD and runtime reflection: `9a86cdaef2e7105eaedd7f1ecf735298e51712e5`; previous service baseline was `e8fd1d17e24fd5fd6904ff853a852d3b72349a57`.
- Pre-deploy: operations schema 92; no running Research/Publication job or in-flight Blogger write. One existing queued publication job was retained. Runtime policy remained AutoMode `auto`, AutoPolicyActive `true`, 15-minute minimum interval, daily limit 100, and six approved Blogger IDs.
- Backup: `backups/20261105T060547Z.dump` (59,501,011 bytes); `pg_restore --list` archive validation passed. No schema migration or settings change was made.
- Reflection: `scripts/apply-verified-changes.ps1 -Apply -Confirm:$false` completed successfully. It gracefully stopped all four services after their current work cycles, then started them from the validated HEAD. New PIDs: API 4952, Dashboard 9600, Research Worker 21732, Publication Worker 20068. API `/health` and Dashboard `/publishing` returned HTTP 200. Both Worker heartbeats are fresh; Publication Worker mode is `operations-scheduled-auto-and-manual-and-trends`, with AutoMode `auto` and AutoPolicyActive `true`.
- Verification: Pester 32 passed; targeted API pytest 144 passed (one pytest cache-path permission warning); Ruff, mypy, isolated wheel build, Dashboard lint, typecheck, and production build passed. The first `WhatIf` preview was unsuitable because `WhatIf` propagated into Pester. A subsequent overlapping pytest invocation hit a Windows shared-temp cleanup permission error; the final single run used an isolated pytest base path and passed.
- Deployment-window effects: zero new authoring jobs, zero new publication jobs, and zero Blogger write operations. The existing queued publication job remains held by `global_minimum_interval_not_elapsed`. No test post or draft was created.
- Completion audit: append-only `agent.work.completed` ID `375000`; links to start ID `374962`. No audit rows were updated or deleted.
- Git policy: source commit remains `8e104d2a5c05a10b816e0dc095d555eda922a434`; this deployment follow-up is recorded in the documentation commit and `git log`.
