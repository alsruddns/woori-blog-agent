# P5-CODEX-087 — Google Trends 수집 회차 설정

- 2026-10-30 KST, develop. 이전 상태: 11개 지역을 KST 시간당 순회하고 전역 5분·시간당 12회 제한 적용. 사용자 요청에 따라 Trends RSS에 한해 해당 내부 제한을 제거한다. Blogger 발행 정책과 간격은 변경하지 않는다.
- 변경 후: schema 64의 영속 설정 기본값 10분(5·10·15·20·30·60), ON/OFF 및 변경 감사 이벤트. 변경 주기는 기존 주기의 다음 경계부터 적용한다. 기존 Research Worker가 단일 advisory lock으로 회차를 소유하고 각 지역을 순차 조회한다. 슬롯 중복 성공과 동일 회차 중복 호출을 방지하며 지역별 성공·실패를 보존한다. Google 429/403 또는 quota 신호 시 1시간 영속 보류한다.
- Dashboard `/sources`에서 설정을 조회·변경하고 최근 수집·다음 회차·지역별 결과를 확인한다. 시간 소수 변환은 표시용이며 RSS `hours` 지원은 확인하지 못해 전송하거나 필터 적용으로 보고하지 않는다. 기존 관측·감사 이력과 15개 예약 및 Blogger 발행은 보존한다.
- 변경 파일: `scripts/064_trend_collection_settings.sql`, `scripts/migrate.py`, `scripts/provision-test-database.py`, `services/api/woori/trends.py`, `external_policy.py`, `research_routes.py`, `trend_editorial.py`, `worker.py`, `services/api/tests/test_trends.py`, `test_trend_editorial.py`, Dashboard `sources/trend-settings.tsx`, `sources/workspace.tsx`, `api/research/[...path]/route.ts`, `AGENTS.md`, `docs/operations/zero-cost-policy.md`, 이 기록.
- 검증: 격리 DB 65건, Ruff/mypy, Dashboard lint/typecheck/Production Build 통과. 격리 수집에서 11지역, 일부 실패, 동일 슬롯 중복 방지, 429 보류 및 설정 변경 감사를 확인했다. 실제 운영 migration·수집·브라우저 결과는 후속 기록에 남긴다.
- 롤백: 서비스 코드를 이전 버전으로 되돌리고 추가 설정 테이블과 감사·수집 이력을 보존한다. 과거 관측값·감사 이벤트를 삭제하지 않는다. 커밋 해시는 git log 참조.
