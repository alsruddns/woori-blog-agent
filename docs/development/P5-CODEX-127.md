# P5-CODEX-127 — 수동·자동 발행 차단 조건 수정

- 작업 일시: 2026-11-04 KST
- 브랜치: `develop`
- 시작 HEAD: `fdc2add590bbbd9164dd4b3172f86d2549048f69`
- P126 운영 상태: Migration 089, API, Dashboard, Research Worker, Publication Worker가 P126 커밋으로 반영된 상태를 확인했다.
- 기존 stash와 미추적 파일은 보존했다.

## 변경 전후

- 수동 발행은 `source_live_verification_missing`, `claim_source_verification_unavailable`, `source_original_review_required`를 차단 사유 대신 코드가 포함된 보완사항으로 전환한다.
- `manual_supported_revision_required`를 발행 차단 코드로 사용하지 않는다. 검증되지 않은 문단을 제거한 안전 본문을 발행 스냅샷에 사용하고 보완사항을 기록한다.
- 정제 후 실질적인 게시 본문이 남지 않으면 `no_supported_body_after_sanitization`로 보류한다. 빈 본문이나 근거 없는 내용을 게시하지 않는다.
- 기계 품질, SEO, 일반 편집 검토, 기존 `publish_ready` 상태는 P126처럼 보완사항이며, 검토 상태나 사실 검증 결과를 통과로 바꾸지 않는다.
- 수동 Job, exact-version intent, 리뷰 및 보완 항목 생성은 같은 DB 트랜잭션에 기록한다. 리뷰 원장을 저장할 수 없으면 요청을 실패시켜 큐만 남는 상태를 방지한다.
- 예약 자동 발행은 P052/058의 기존 publish-first 흐름과 자동 정제 revision 경로를 유지한다. 검증되지 않은 claim이 포함된 원본 버전을 그대로 발행하도록 gate를 약화하지 않았다. Trends 자동 발행의 검증되지 않은 claim 차단도 유지한다.

## 수정 파일

- `services/api/woori/publications.py`: 수동 발행 보완사항 분류, 정제 본문 사용, 보완 원장 저장 실패 처리.
- `services/api/tests/test_publications.py`: revision 요구의 일반 차단 제거와 게시 가능한 근거 본문 부재의 안전 보류 확인.
- `docs/development/P5-CODEX-127.md`: 작업·검증 기록.

## 검증 및 운영 반영

- pytest: 발행·예약 검증·Trends 관련 93건 통과.
- 실제 Blogger POST/초안 생성: 0건.
- 이번 단계에서는 운영 DB/서비스를 변경하지 않았고 운영 반영은 미완료다. 운영 반영 전에 P127 코드를 포함한 최신 develop 커밋, 운영 DB 백업 및 안전 반영 절차가 필요하다.
- 기존 15분 간격, KST LIVE 100건, 블로그 범위, OAuth, 중복 방지, 우선순위는 변경하지 않았다.

## 남은 문제

- `no_supported_body_after_sanitization`인 원고는 수동 revision 없이도 발행을 강제하지 않는다. 이 경우 사실 기반의 유효한 본문을 만들 수 없으므로 보류가 안전하다.
- Trends의 검증되지 않은 주장과 예약 원고의 검증되지 않은 본문은 각각 기존 근거 검증 및 자동 정제 revision이 처리한다. 검증 상태를 warning만으로 바꾸어 원문 내용을 그대로 공개하지 않는다.
- 최종 커밋 해시는 후속 Git 이력으로 기록한다.

## P127 운영 반영 업데이트

- 개발 검증 후 커밋 `b77ace192d38937bcd437819a59070ab98982437`를 origin/develop에 푸시했다.
- 작업 전 운영 DB schema 89, 설정 Revision 20, 발행 간격 15분, LIVE 상한 100건을 확인했다. Migration이나 운영 설정 변경은 필요하지 않았다.
- 반영 전 큐에는 blocked 3, failed 19, succeeded 24건만 있었고 queued/running 발행 Job 및 실행 중 Blogger 쓰기 시도는 0건이었다.
- 검증된 서비스 반영 스크립트로 API와 Publication Worker만 graceful restart했다. API HTTP 200, Worker heartbeat 정상, 두 서비스 AppliedCommit은 P127 커밋이다. Dashboard와 Research Worker는 변경 대상이 아니어서 기존 PID/커밋으로 계속 실행 중이다.
- Trends 수집은 ON/30분, 발행 제한은 15분/KST 100건으로 유지됐다. Blogger 발행 요청 및 테스트 게시물은 0건이다.
- 서비스 반영 스크립트 변경 범위 테스트 50건 통과, 격리 wheel build 및 Dashboard build 통과. pytest 캐시 경로 권한 경고는 있었고 테스트 결과에는 영향이 없었다.
- 최종 문서 갱신 커밋은 이 문서 작성 커밋으로 이어서 기록한다.
