# P5-CODEX-083 — 자동발행실패와 Job 현재 상태 동기화

- 2026-10-30 KST, develop. 자동발행실패 조회가 과거 이벤트와 LIVE 이력만 확인하여 같은 Import·Content Version·블로그의 수동 queued Job을 무시했다.
- 운영 조회 변경 전 자동발행실패 6건, 변경 후 1건. 예: Import `e08117bd-bba4-45d4-84a8-f728f9eb2a55`, Content Version `85c65051-4e7d-4ff0-a2d5-b4c7bdf7114c`, 블로그 `769d3996-335c-4037-9216-a62f058f8638`, 수동 Job `aff633b7-9c1c-4b35-852a-03998de54062` queued. 실시간 상태는 Worker에 따라 변할 수 있다.
- 실제 live Job이 queued/running/failed/blocked/uncertain인 경우 같은 Import와 content version, blog에 한해 과거 pre-job 실패를 목록에서 숨긴다. 실패 Job은 기존 실패·보류 및 Worker Job 화면에서 조회한다. 검증된 LIVE 기록도 제외하며 감사 이벤트는 보존한다. 다른 버전·블로그의 실패는 별도 항목이다.
- Worker 모니터의 이벤트 그룹 기준을 버전까지 확장하고 같은 기준으로 pre-job 실패를 판단한다. 수동 요청 성공 후 재조회 및 Worker 모니터 갱신을 유지하며, 목록은 10초마다 보이는 화면에서 갱신한다. 페이지가 비면 유효한 페이지로 이동한다. API 조회 실패는 오류로 표시한다.
- 변경 파일: `services/api/woori/publications.py`, `publication_monitor.py`, `services/api/tests/test_publication_monitor.py`, `apps/dashboard/app/publishing/publication-manager.tsx`, 이 문서. DB 변경 및 Blogger 쓰기 없음.
- 격리 DB 테스트 47건, Ruff/mypy, Dashboard lint/typecheck/Production Build 통과. queued/running/failed/blocked/uncertain에 대한 정확한 연결과 원본 감사 이벤트 보존 검증. 실제 브라우저 및 런타임 결과는 후속 기록 참조.
- 커밋 해시는 git log 참조. 기존 정책, Worker 및 감사 이력 보존.
