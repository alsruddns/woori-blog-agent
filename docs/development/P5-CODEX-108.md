# P5-CODEX-108 — 통합 Blogger 발행 큐와 30분 공통 간격

- 작업 일시: 2026-11-03 (Asia/Seoul), 사용량 제한 중단 작업 이어서 진행
- 작업 브랜치: `develop`
- 시작 커밋: `856ddf9069fbe7609de9e0b54b74822e7996d954`
- stash: `stash@{0}` (P5-CODEX-099-101 이전 중단분, 확인만 했고 유지)
- 개발 커밋: 후속 갱신 예정

## 변경 사유와 문제

P5-CODEX-108에서 Trends 수집 30분과 Blogger 발행 간격을 별도로 관리하고, 수동·Trends·예약 발행 요청을 하나의 durable queue 및 전역 잠금으로 보호한다. 이전 구현에는 OAuth grant 기준 2분, 블로그별 5분 간격이 남아 있었고 LIVE 경로는 Draft 생성 후 별도 publish 단계로 진행해 LIVE 요청 결과가 혼동될 수 있었다. 새 요구사항은 Blogger 공통 최소 간격을 10분이 아닌 **30분**으로 고정하며, Trends 수집도 독립적으로 30분을 유지한다.

## 변경 전 / 변경 후

- 변경 전: 운영 스키마 80, Trends 설정에 `interval_minutes=60`, `pending_interval_minutes=30`; Blogger 발행 간격은 코드 경로별 2/5분. 예약/Trends 자동 원고에는 Import 이후 큐 연결이 있었으나 별도 Draft→LIVE 단계가 있었다.
- 변경 후 코드: additive Migration 081은 Trends 기본값·현재 유효값을 30분으로 만들고 pending 경계를 제거한다. `automation_controls.global_publish_min_interval_minutes`는 DB 기본 30, 최소 허용 30분이다. 모든 Blogger API POST/PATCH/PUT 전에 동일 advisory lock과 append-only write-start timestamp를 사용하며, 최근 실제 write-start/request 기록으로 30분을 다시 확인한다. 설정/이력 조회 실패 시 쓰기는 중단된다. 모든 자동·수동/ Draft·LIVE 경로는 기존 Publishing Job/queue를 재사용한다.
- 변경 후 LIVE: 신규 LIVE는 `isDraft=false`로 생성하고, 같은 postId의 실제 Blogger 상태·blog ID·title/content·공개 URL·게시 시각을 원격 read-back으로 확인해야 성공 처리한다. 자동 예약·Trends 신규 Import는 공통 job lane에 연결되고, 기존 실패/과거 job을 활성화 시점에 재등록하지 않는다.
- Google Trends 수집 간격과 Blogger 발행 간격은 별도의 DB 필드이며 서로 변경하지 않는다.

## 실제 운영 조사 및 보호

- 시작 시 API/Dashboard/Research Worker/Publication Worker는 기존 정상 프로세스로 확인되어 PID를 보존했다. Worker를 강제 종료하거나 Blogger에 쓰기 요청을 보내지 않았다.
- 운영 DB는 시작 시 schema 80, automation controls revision 12였다. Trends는 enabled이며 60분 effective, 30분 pending으로 남아 있었다. 기존 예약 자동화 15개 설정 및 과거 job/게시 데이터는 수정하지 않았다.
- 운영 백업 `backups/20261102T160010Z.dump` 생성 및 `pg_restore --list` archive catalog 검증 후 Migration 081을 적용했다. 운영 스키마는 81, revision은 13이며 `trend_collection_settings.interval_minutes=30`, pending=NULL, `global_publish_min_interval_minutes=30`을 DB에서 다시 읽어 확인했다. 기존 job 상태는 변경하지 않았다.
- 현재 운영 자동화 설정은 Trends 수집 ON, Codex 작성 ON, 전체 자동 발행 ON, Trends 자동 발행 OFF, 예약 자동 발행 ON, 수동 발행 ON, 긴급 정지 OFF이다. Trends 자동 발행은 기존 외부 승인 정책 부재로 OFF를 유지한다.
- 최신 감사/운영 정책 조사 결과 public Blogger write는 기존 외부 정책에서 허용되지 않았다. Blogger 비용/공개쓰기 승인과 Trends per-blog 공개 승인 및 최신 연결 쓰기 검증 증거가 없으므로 운영에서 자동 공개를 활성화하거나 승인 이벤트를 만들어 넣지 않았다. 사용자의 자동 발행 요구는 코드·Mock 검증 범위에서 구현하되, 운영 쓰기는 기존 append-only 정책과 AGENTS.md 게이트를 계속 따른다.
- 운영 migration 및 프로세스 재시작 적용 여부는 최종 검증 섹션에 기록한다.

## 수정 파일

- `scripts/081_trends_and_global_publish_intervals.sql` — Trends 30분 및 공통 Blogger 간격 30분 additive migration
- `scripts/migrate.py`, `scripts/provision-test-database.py` — schema 81 등록
- `services/api/woori/blogger_writes.py` — global 30분 durable write gate, 공통 lock, LIVE 생성/read-back
- `services/api/woori/automation_controls.py` — 최소 30분 설정 API와 revision 저장
- `services/api/woori/automation_auto.py`, `services/api/woori/publication_worker.py` — 예약/Trends 공통 queue lane, LIVE mode 보존 및 실행
- `services/api/woori/publications.py`, `services/api/woori/publication_monitor.py` — interval 상태 노출
- `apps/dashboard/app/operations/automation/controls.tsx`, `apps/dashboard/app/publishing/publication-manager.tsx`, `apps/dashboard/app/publishing/publication-worker-panel.tsx`, `apps/dashboard/app/sources/trend-settings.tsx` — 30분 상태 표시 및 별도 cadence 유지
- Dashboard E2E fixtures, Blogger LIVE/interval/Trends/API tests
- `docs/operations/zero-cost-policy.md` — 과거 2/5분 cadence가 P108의 30분 공통 제한으로 대체된 점 명시

## 검증

- 격리 test DB는 schema 81로 provision되어 migration 081을 통과했다. 운영 DB도 backup 후 schema 81 migration 적용을 확인했다.
- 변경 범위 API 테스트 `test_publication_interval.py`, `test_blogger_live_policy.py`, `test_publications.py`, `test_trends.py`: **128 passed**. 기존 테스트의 mock 정책 허용 및 운영 authoring-only 정책 기대값을 현재 fail-closed 계약에 맞췄다.
- Ruff: 변경 Python 모듈/테스트 통과. Mypy: 변경된 API 소스 6개 통과. Dashboard `npm run typecheck`: 통과. `git diff --check`: 통과.
- Blogger LIVE 검증은 `httpx.MockTransport`만 사용했다. 실제 Blogger write count: 0.
- 브라우저 UI: P103/P106 controls 14개 데스크톱/모바일 테스트는 개발 재개 시점의 코드에서 통과한 기록을 확인했다. 신규 화면은 간격 표기 변경이며 재시작 후 새 revision UI 확인은 아직 남아 있다.
- 운영 migration 전 백업: `backups/20261102T160010Z.dump`, archive catalog 검증 완료. Restore rehearsal는 이번에 하지 않았다.
- Blogger LIVE 검증은 `httpx.MockTransport`만 사용했다. 실제 Blogger write count: 0.
- API/UI revision 동기화와 운영 서비스 재시작은 실제 실행 결과를 확인한 뒤에만 완료로 기록한다.
- DB migration 운영 백업: 최종 적용 전 `scripts/backup.py`로 archive 생성·catalog 확인이 필요하다.

## 남은 작업

- API, Dashboard, Worker는 현재 이전 applied commit에서 정상 heartbeat 중이다. 코드가 commit/push된 뒤에는 `scripts/apply-verified-changes.ps1 -Apply`의 lint/test/build 및 graceful service reflection 절차를 사용해 영향을 받는 서비스만 반영한다. 강제 종료는 금지한다.
- 운영 DB backup/migration은 적용 완료했지만 신규 코드가 아직 실행 중 서비스에 반영되지 않았다.
- 사용자가 요구한 Trends automatic LIVE operating value는 별도 Trends public-write approval가 없어 운영 DB에 켤 수 없다. 기존 external/cost/manual-only gates를 우회하지 않고 미완료로 보고한다.
- 설정 Revision·Worker heartbeat 및 실제 30분 Trends 회차는 신규 코드의 안전한 서비스 반영 후 재확인한다.
- 테스트/검증 결과, migration 백업 이름, API/Dashboard/Worker revision, 최종 commit hash, 원격 HEAD를 후속 기록으로 추가한다.
