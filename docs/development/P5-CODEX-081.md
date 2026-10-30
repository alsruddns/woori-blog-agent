# P5-CODEX-081 — Google Trends 수집·기사화 상태

- 작업일: 2026-10-30 KST. 브랜치: develop.
- 기존 문제: RSS 관측값 2,990건은 보존됐지만 검색량·원본 카테고리와 기사화 선정·폐기를 한 화면에서 조회할 수 없었고, 082용 영속 큐 계약도 없었다. 기존 분류 함수에서 특수 `technology` 마커가 일반 `technology` 마커를 덮어쓰는 오류가 있었다.
- 변경 전: 11개 지역 KST 시간별 RSS 순회, 시간당 최대 12회·전역 요청 5분 간격, 정확 검색어·동일 국가만 그룹화. RSS 발행 순서를 순위로 표시하지 않았다.
- 변경 후: 동일 시간대·지역의 성공 수집 재실행을 방지하고 RSS 항목 XML, 뉴스 맥락, 원본 카테고리, 원본 검색량을 보존한다. 분류 결과·폐기 사유·운영자 재분류는 append-only 이벤트다. 출처 뉴스 헤드라인은 사실 입증이 아니라 추가 조사 맥락이다. 서로 다른 언어·사건은 자동 병합하지 않는다. 지역·블로그 정책이 정확히 일치할 때만 `trend-authoring/1` 영속 큐에 전달한다. 이 단계에서는 큐에서 Codex나 Blogger를 호출하지 않는다.
- 변경 파일: `scripts/062_trend_editorial_queue.sql`, `scripts/migrate.py`, `scripts/provision-test-database.py`, `services/api/woori/trends.py`, `topics.py`, `trend_editorial.py`, `worker.py`, `main.py`, `apps/dashboard/app/sources/workspace.tsx`, `legacy-workspace.tsx`, `app/api/research/[...path]/route.ts`, `services/api/tests/test_trend_editorial.py`.
- 데이터: 운영 DB 백업·archive catalog 확인 후 schema 62 적용. 기존 관측값·감사 기록 보존. 기존 관측값에는 새 RSS 원본 필드가 없어 UI에 정보 없음으로 표시한다.
- 검증: 격리 DB 관련 테스트 41건, Ruff, mypy, Dashboard ESLint/TypeScript 통과. 운영 수집은 기존 시간대 성공으로 재실행이 `already_collected`였고, 다른 지역 요청은 기존 5분 제한으로 정당하게 `global_minimum_spacing` 차단되었다. 추가 허용 시각 이후 실제 RSS 수집 결과는 후속 기록.
- 남은 문제: 082의 실제 자동 원고 생성·발행 연결, Dashboard 실제 브라우저/Production Build 검증, 운영 런타임 반영. 이번 단계의 선정은 자동 게시 적격을 의미하지 않는다.
- 커밋 해시: 이 문서의 커밋과 `git log` 참조. 자기 참조 해시는 포함하지 않는다.
