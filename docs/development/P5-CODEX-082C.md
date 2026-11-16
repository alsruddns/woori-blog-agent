# P5-CODEX-082C — 회차 제한과 선정 큐 연결 (진행 중)

- 2026-10-30 KST, develop. 기존 082B 기록과 운영 DB schema 63 확인. 시작 시 관측값 3,050, 주제 2,138, 선정 0, 보류 2,133, 폐기 5, 작성 큐 0. 과거 RSS 원본 부재와 보수적 뉴스 맥락 판정이 보류 원인이다.
- 기존 성공 수집의 `trend_collection_slots`와 관측값 run_id를 연결하여 현재 KST 시간 슬롯만 큐에 허용한다. UTC/KST 시간값은 절대 시각으로 비교한다. 계약에는 수집 슬롯과 실제 수집 시각을 별도 저장한다. 이전 회차 미처리 후보는 append-only `expired_collection_slot` 이벤트로 만료하고 관측값은 보존한다.
- 선정 주제는 현재 슬롯 관측과 뉴스 URL 및 유일한 국가 일치 대상이 있을 때에만 시간당 최대 한 건을 기존 영속 큐에 연결한다. 동일 주제·블로그의 기존 요청을 다시 생성하지 않는다. 예약된 Codex Job은 실행 직전 슬롯을 재검사하고 이전 회차 미시작 Job은 취소한다. 이미 실행 ID가 있는 Job은 보존한다.
- 수정 파일: `services/api/woori/trend_editorial.py`, `keyword_jobs.py`, `worker.py`, `services/api/tests/test_trend_editorial.py`, 이 문서. DB migration 없음. 격리 테스트 46건 통과, Ruff/mypy 통과.
- 남은 작업: 자동 정책 UI/API, Trends 전용 Publisher lane과 출처·권리·원격 중복 검증, 11개 지역 회차 지연 및 동시성 통합 검증, 완전한 격리 E2E와 실제 LIVE 검증, Dashboard 최신 회차 표시. 현재 구현을 전체 자동 발행 완료로 보지 않는다. 원격 게시 0건, postId/URL 없음.
- 커밋은 git log 참조. 기존 데이터·발행 이력 보존. 운영 반영과 후속 검증은 별도 기록한다.
