# P5-CODEX-082 — Trends Codex 작성·발행 연결

- 작업일: 2026-10-30 KST, develop.
- 기존 문제: 081의 선정 주제 큐가 Codex 작성 Job이나 수동·예약 원고와 구분되는 Import provenance에 연결되지 않았다.
- 변경 목적/전후: `trend_generation_requests`의 선정된 정확한 지역·블로그 계약을 `google_trends` Codex Job으로 영속 변환한다. 실행은 080의 공식 ChatGPT 로그인 Codex CLI와 동일한 제한된 Reader workspace·웹 조사 경로다. 결과는 `codex_trends_export`로 Import되어 예약 Desktop 실행이나 사용자 수동 원고로 표시되지 않는다. RSS 검색량·헤드라인은 뉴스 사건의 사실 증거로 승격하지 않는다.
- 수정 파일: `scripts/063_trend_codex_provenance.sql`, `scripts/migrate.py`, `scripts/provision-test-database.py`, `services/api/woori/content_imports.py`, `keyword_jobs.py`, `trend_editorial.py`, `worker.py`, `services/api/tests/test_trend_editorial.py`.
- 격리 테스트: 선정 주제·지역 정책 → 영속 큐 → Codex Job 생성 및 중복 방지, Publishing Job 미생성을 확인. 정식 Import/실제 Codex/Web/Blogger 운영 결과는 후속 실행 기록에 남긴다.
- 운영: schema 63은 운영 DB 백업 후 적용했다. `scheduled_publication_policy_events`는 기존 Codex Desktop 예약 범위다. 이 이벤트만으로 Trends 자동 공개 권한을 추론하지 않는다.
- 남은 문제: Trends 전용 운영 승인 정책과 안전한 live publisher lane, 실제 근거 검증된 Trends 원고, 원격 중복 확인 후 실제 Blogger 게시. 외부 공개 postId와 URL이 없으면 게시 성공으로 보고하지 않는다.
- 커밋 해시: 이 문서 커밋의 `git log` 참조.
