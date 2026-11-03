# P5-CODEX-118 — Google Trends DE/BR/VN and publication UI fixes

## 작업 기록

- 작업 ID: P5-CODEX-118
- 작업 일시: 2026-11-03 (Asia/Seoul)
- 변경 사유: 독일·브라질·베트남 Trends 작성 경로가 설정/API 제약으로 막히고 발행 관리의 Unicode 및 수동 요청 UI가 오동작함.
- 기존 문제: 수집/외부 정책/DB geo 허용값이 11개 지역에 한정됨. Trends 대상 선택은 Blogger publication policy를 요구해 작성 대상과 발행 승인을 혼합함. Job 화면의 일부 단위는 JavaScript JSX 텍스트로 `\u...` 리터럴을 출력함. 실패 원고의 수동 발행 버튼은 `manual_publication_available=false`인 경우 설명 없이 반환함.
- 변경 목적: 세 지역을 기존 30분 Trends 회차와 기존 Blog/언어 프로필에 연결하고, 작성과 발행 권한을 분리하며, 수동 요청을 기존 공통 승인·큐 경로로 보낼 수 있게 함.

## 변경 전·후

| 항목 | 변경 전 | 변경 후 |
|---|---|---|
| Trends 허용 지역 | 11개 | 기존 지역을 보존하고 DE, BR, VN 추가 (14개) |
| DE/BR/VN 작성 대상 | 발행 정책이 없으면 선택되지 않음 | 활성 Blogger·언어와 명시적 단일 국가 프로필로 선택; 별도 발행 권한은 그대로 필요 |
| 작성 매핑 | DE/BR/VN 없음 | 실제 등록된 Blog ID와 URL에 맞는 활성 매핑 3건 |
| Job 단위 표시 | 일부 항목에서 `\\uac74` 같은 문자열 | 한국어 단위 정상 표시, 숫자 `ko-KR` 천 단위 구분 |
| 실패·검토 원고 수동 요청 | 요약 API 플래그가 false면 버튼이 무반응 | 정확한 Import/Content Version 확인 모달 진입; 기존 API가 정책 검사 후 공통 큐에 등록 |
| 결과 안내 | 큐 접수 이후 최종 상태가 화면에서 연결되지 않음 | 큐 접수와 실제 LIVE/Draft/실패/보류를 구분하고 읽기 전용 Job 상태를 제한적으로 조회 |

## 운영 DB·안전 경계

- 백업: `backups/20261103T064711Z.dump` (43,144,188 bytes; 2026-11-03 15:47 KST).
- Additive Migration 084 적용: Trends geo 제약을 14개로 확장하고 등록되어 검증된 DE/de/DE, BR/pt-BR/BR, VN/vi/VN 작성 매핑을 추가함.
- 적용 후 스키마 버전: 84.
- 기존 Blog ID, URL, 언어, 활성 상태와 기존 설정을 사용함. 신규 Blogger, OAuth 연결, 발행 정책, Publishing Job을 생성하지 않음.
- 변경 전후 데이터: content_groups 289, content_versions 519, imports 167, publishing_jobs 46, publishing_records 21, Blogger draft receipts 3, blogs 7, publication policies 8로 동일. geo authoring mappings만 9에서 12로 증가. Migration은 감사 이력을 추가함.
- 운영 설정 Revision 18 유지: Google Trends ON/30분, 자동 원고 작성 ON, 기존 자동/수동 발행 설정 유지, 글로벌 발행 간격 15분, KST LIVE 상한 100. 중국어 블로그는 기존 inactive 상태를 유지함.
- 실제 Blogger POST/수정/삭제 호출: 0. UI 요청은 기존 manual queue endpoint만 사용하며, 운영 정책 차단을 우회하지 않음.
- 승인 정책 제약: 저장소의 P5-CODEX-088에 따라 Trends lane은 Research Import까지만 동작하며 Publishing Job 또는 Blogger 발행 권한을 만들지 않음. 이번 작업도 Trends 자동 발행/정책을 활성화하지 않음. 예약·수동 경로의 기존 정책도 바꾸지 않음.
- 실제 DE/BR/VN RSS 회차 결과와 신규 Codex 원고/Import는 이번 검증에서 만들지 않음. 다음 정상 30분 슬롯과 기존 작성 실행에서 운영 결과를 별도로 확인해야 함.

## 수정 파일

- `services/api/woori/trends.py`
- `services/api/woori/external_policy.py`
- `services/api/woori/keyword_jobs.py`
- `services/api/woori/trend_editorial.py`
- `services/api/tests/test_trends.py`
- `services/api/tests/test_trend_editorial.py`
- `scripts/084_trends_de_br_vn_authoring.sql`
- `scripts/migrate.py`
- `apps/dashboard/app/research/research.tsx`
- `apps/dashboard/app/sources/trend-settings.tsx`
- `apps/dashboard/app/publishing/publication-worker-panel.tsx`
- `apps/dashboard/app/publishing/publication-manager.tsx`
- `apps/dashboard/e2e/P5-CODEX-110-grid-publish.spec.ts`
- `docs/operations/zero-cost-policy.md`
- `docs/development/P5-CODEX-118.md`

## 검증 결과

- Backend focused tests: 59 passed.
- Dashboard lint: passed.
- Dashboard typecheck: passed.
- Isolated production build: passed.
- Playwright (1440px desktop and 390px mobile): 6 passed; covers grid confirmation/no detail sheet/cancel without POST and Unicode/comma formatting.
- Migration 084: isolated test DB and operations DB applied; operations mapping and policy/job/data counts verified.
- `git diff --check`: passed before final documentation/commit review.
- No actual Google RSS collection request or Blogger write was made as part of verification; RSS availability, real Codex generation/Import, and LIVE/Draft completion remain unverified.

## 배포·커밋·잔여 작업

- 운영 DB Migration 084 적용 완료. API, Dashboard, Research Worker, Publication Worker를 저장소의 `scripts/apply-verified-changes.ps1 -Apply` 절차로 순차 graceful stop/start 함. 정상 Blogger 쓰기 중이 아니고 게시 큐가 비어 있음을 확인한 뒤 교체함. 강제 종료 및 PostgreSQL 재시작은 없었음.
- 재기동 후 API PID 24316 및 Dashboard PID 27356의 HTTP GET 200, Research Worker PID 20256 및 Publication Worker PID 5912의 fresh heartbeat 확인. 각 프로세스의 적용 커밋은 `f7ad7a27d68ee1a01bc3eb30883ab40ae45b2104`.
- 재기동 후에도 Schema 84, 새 geo mapping 3건, automation Revision 18, Trends ON/30분, global publish 15분, daily LIVE limit 100, 중국어 블로그 inactive를 확인함. 활성 Bloggers 6개 및 기존 15개 예약 자동화 설정을 변경하지 않음.
- 최종 검증: Backend 집중 테스트 59 passed; Ruff, API type check, wheel build, Dashboard lint/typecheck/production build passed; Playwright desktop/mobile 6 passed. `PYTEST_ADDOPTS=--basetemp .pytest-p118-verify2`로 Windows 임시 디렉터리 권한 문제를 격리함. 이 과정에서 최초 검증은 unused test local 변수와 pytest temp cleanup 권한 때문에 서비스 중지 전 안전하게 중단됐고, 수정·격리 후 전체 검증 및 반영 성공.
- 구현 커밋: `f7ad7a27d68ee1a01bc3eb30883ab40ae45b2104`. 개발 기록의 배포 후속 커밋은 git history에서 확인.
- 실제 Google Trends RSS 요청, 신규 Codex Trends 원고/Import 및 Blogger POST는 0건. 실제 국가별 feed 수집·후속 Import는 다음 정상 슬롯에서 관찰해야 함.
- 관련 문서: `AGENTS.md`, `docs/operations/zero-cost-policy.md`.
- 남은 문제: 실제 DE/BR/VN 다음 30분 수집 슬롯과 후속 Codex 작성/Import를 운영에서 확인해야 함. Trends 자동 Blogger 발행은 저장소 정책상 본 작업 범위에서 허용되지 않으며 Import 이후 발행 작업 생성은 하지 않음.
