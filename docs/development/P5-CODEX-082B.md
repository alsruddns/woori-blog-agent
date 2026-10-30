# P5-CODEX-082B — Trends 재시도 provenance 복구 (부분 완료)

- 작업일: 2026-10-30 KST, develop. 시작 커밋 `7765a744`.
- 운영 상태: 관측값 3,050건, 주제 2,138건; 최신 분류는 review_candidate 2,133건, discarded 5건, selected 0건; 작성 큐 0건. 과거 관측값에는 RSS 뉴스 원본이 없어 분류기가 확인되지 않은 선정으로 승격하지 않는다. 현재 선정 규칙은 분야와 관련 뉴스 문맥을 요구한다. 기존 관측값이나 이력은 삭제하지 않았다.
- 발견된 버그: 기존 retry는 Import 복구 시 `manual_codex_import`만 찾았고, Trends 실행 실패 시 사용자 키워드 신규 Job으로 바뀔 수 있었다. 이는 동일 Trends 원고의 중복 작성 및 provenance 손실 위험이다.
- 수정: Import 복구 시 Job 유형별 정확한 provenance로 조회한다. 저장된 동일 실행 결과는 기존 Job/Trends 요청 링크와 감사 이벤트를 유지하며 재검증한다. 저장 결과가 없으면 수동 원고로 변환하지 않고 명확한 오류로 중단한다. Import 결과 불명 시 기존 복구 가드는 유지한다.
- 파일: `services/api/woori/keyword_jobs.py`, `services/api/tests/test_trend_editorial.py`, 이 문서. 변경 범위 격리 DB 테스트 20건, Ruff/mypy 통과.
- 미완료: 선정→자동 큐 정책의 중복 확인, Trends 전용 발행 정책 및 Publisher 레인, 검증된 실제 Trends 원고의 운영 E2E, 대시보드 발행 상태 연결. Trends 자동 공개 Job, postId, URL, 원격 LIVE 검증 모두 없음. 예약 Auto 정책을 Trends 공개 권한으로 간주하지 않았다.
- 기존 데이터·감사 기록 및 15개 예약 설정 보존. 마이그레이션 없음. 커밋은 `git log` 참조.
