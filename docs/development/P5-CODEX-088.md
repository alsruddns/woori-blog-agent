# P5-CODEX-088 — Google Trends country authoring and Research Worker Import

- 작업 일시: 2026-10-31 (KST)
- 기준 브랜치/커밋: `develop` / `c9c370a9cca6e635243fda7db7005534dcfe9cb8`
- 변경 사유: P5-CODEX-087의 11개 지역 수집 결과가 국가별 Codex 작성 요청 및 Research Worker Import로 이어지지 않았다.
- 변경 목적: 명시적으로 연결한 Blogger·지역에서 현재 수집 슬롯의 검색량 순위 후보를 공통 `google_trends` Codex Runner에 전달하고 기존 Import까지 연결한다.
- 기존 상태: 블로그와 source geo의 정확 일치만 사용, 시간당 요청 1건 제한, RSS 뉴스 URL/제목 일치가 분류 선택의 선행 조건이었다. Trends job은 공통 Runner/Import 계약에 연결돼 있었지만 운영 요청과 국가 매핑 UI가 없었다.
- 변경 후 상태: 여러 지역을 한 Blogger에 매핑하고 국가별 처리 순서를 순환시킨다. 각 geo의 현재 슬롯 후보를 제공된 검색량 하한·시작 시각으로 순위화하고, 주제 신호가 불명확하면 제외한다. RSS는 발견 맥락으로만 취급하며 Codex에 독립적인 최신 웹 조사를 요청한다. 동일 job 요청은 기존 UUID/idempotency 계약을 사용한다. 본 작업은 원고 Import에서 끝나며 Publishing Job/공개 게시 경로는 호출하지 않는다.
- 운영 매핑: Trend KO `ko/KR` ← KR, Trend Journal EN `en/US` ← US, Trend JA `ja/JP` ← JP. Trend ZH `zh-CN/CN`은 수집 allowlist에 CN이 없어 기본 매핑하지 않았다. 다른 영어권·중문 지역은 Dashboard의 명시적 운영자 매핑 설정으로 추가할 수 있다. 단일 geo의 다중 Blogger 자동 공유는 막는다.
- 관측 근거: 최신 확인 슬롯 `2026-10-31 00:00 KST`, 11/11 geo 수집 성공, 각 10개 관측. 운영 읽기 전용 검사 당시 `trend_generation_requests` 최근 1일 0건, `codex_trends_export` Import 0건, Publishing Job 14건.
- category: 현행 taxonomy/DB에 스포츠 category가 없어 검증된 스포츠 후보가 FK에서 실패할 수 있어 additive schema migration 66으로 `sports`를 등록했다. 스포츠 분류는 RSS 검색어와 직접 관련된 헤드라인이 존재할 때만 lane을 정하며, 헤드라인 자체는 claim evidence가 아니다.
- DB 보호: 운영 백업 catalog 검증 후 migration 066 적용. 직전 백업: `backups/20261030T150629Z.dump` (4,406,464 bytes). schema 66 확인. 격리 test DB도 66으로 갱신했으며 운영 테스트 row를 만들지 않았다.
- 수정 파일: `AGENTS.md`; `docs/schemas/woori-content-import-1.0.schema.json`; `apps/dashboard/app/api/research/[...path]/route.ts`; `apps/dashboard/app/sources/trend-settings.tsx`; `apps/dashboard/app/sources/workspace.tsx`; `apps/dashboard/app/style.css`; `scripts/065_trend_blog_geo_authoring.sql`; `scripts/066_sports_editorial_category.sql`; `scripts/migrate.py`; `scripts/provision-test-database.py`; `services/api/woori/editorial_taxonomy.py`; `services/api/woori/topics.py`; `services/api/woori/trend_editorial.py`; `services/api/woori/keyword_jobs.py`; `services/api/tests/test_content_imports.py`; `services/api/tests/test_trend_editorial.py`.
- 테스트: 집중 API integration/contract tests 42 passed; API Ruff passed; changed modules mypy passed; Dashboard lint, typecheck, production build passed. Isolated database identity and operations DB denial verified.
- 커밋: 후속 `git log` 기록을 사용한다.
- 운영 반영 및 실제 Codex/Import E2E: 진행 중이며 본 기록을 최종 결과로 갱신한다. 계정 사용량 한도·근거 부족 시 실제 원고를 허위 성공 처리하지 않는다.
- 관련 문서: P5-CODEX-080/081/082/082B/082C/085/086/087; `docs/operations/zero-cost-policy.md`.
- 남은 문제: 운영 최신 회차에서 공식 Codex CLI 실행, JSON 검증, Research Worker Import, Dashboard 확인을 수행해야 한다. 공개 Blogger 게시 및 Trends 발행 정책은 이번 범위가 아니다.
