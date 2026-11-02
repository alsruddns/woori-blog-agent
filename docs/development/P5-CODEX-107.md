# P5-CODEX-107 — 발행 관리 출처·폐기·성능

- 작업 일시: 2026-11-02 KST
- 기준: `develop` / `0cd72553d857095ef1d6fe5f36a3b424677bbf1d`
- 기존 stash 및 두 `.playwright-mcp/` 미추적 디렉터리 보존

## 사전 측정과 백업

- 운영 목록 API 5개 탭: `queue` 2,325ms/389KB/1건, `review` 2,238ms/456KB/25건, `published` 2,236ms/410KB/19건, `held` 2,158ms/409KB/17건, `auto_failure` 2,244ms/393KB/7건. 매 응답에 전체 Job 40건과 모든 후보를 함께 반환한다.
- `cProfile` 직접 호출 2,087ms 중 본문 중복 비교 1,339ms(3,339회), 운영 모드 조회 498ms. 현재 Content Version 484, Job 40, 게시 기록 19, Import 132, Blogger 4개. 인덱스 추가 전에 애플리케이션의 반복 연산과 과다 응답을 우선 수정한다.
- 운영 백업 `backups/20261102T112055Z.dump`(38,235,956 bytes, `pg_restore --list` 성공). 변경 전 요약 `.local/p107-before.json`: Content Version 484, Job 40, 게시 기록 19, Blogger 쓰기 원장 61, Import 132, 감사 125,280. 운영 설정 revision 12, 수집·작성·전체/예약 자동·수동 발행 ON, Trends 자동 OFF, LIVE, 긴급 정지 OFF.

## 진행 체크포인트

- Migration 080은 `manuscript_discards`를 추가하며 원본 Version, Job, 게시 기록을 삭제하지 않는다. 2026-11-02 KST에 운영 schema 79 → 80 적용, 격리 테스트 DB에도 적용했다.
- 폐기와 복원은 그룹·대상 Blogger 단위로 기록한다. 폐기 시 queued Job을 차단하고 복원 시 재실행하지 않는다. 발행 후보, 자동 Job 생성·Claim, 수동 요청, Blogger HTTP 직전 공통 정책에서 폐기를 재확인한다. 실제 Blogger 쓰기와 같은 트랜잭션 advisory lock을 사용해 진행 중인 쓰기와 충돌을 알린다.
- 출처는 Import 링크, Codex Trends Job, 예약 origin 감사 이벤트 및 occurrence 메타데이터에서 판정한다. 목록 표시용 배치 판정은 출판 허용을 부여하지 않으며, 실제 자동 발행의 별도 실행 영수증 검증은 유지한다. 모호한 출처는 unknown이다.
- Dashboard는 상위 발행 관리/Job 관리 탭을 분리하고 Job 패널을 지연 마운트한다. 출처 배지·필터, 개별/선택 폐기, 보관함/복원, 확인 모달, 검색 320ms debounce, 오래된 목록 응답 무시, 30초 표시 중 자동 갱신을 추가했다. 처음 진입은 발행 관리다.
- 병목은 전체 원고의 본문 정규화 반복과 항목별 예약 실행 영수증 파일 재검증이었다. 중복 본문 인덱스와 출처 배치 조회로 해소했다. 운영 DB 신규 코드 직접 호출 compact 결과: review 880ms/약 86KB/25건, published 839ms/약 36KB/20건, held 867ms/약 34KB/17건, auto_failure 854ms/약 15KB/7건. 출처 필터 scheduled review 843ms/7건. 기준 API 2.2초/약 400KB 대비 개선됐으나 권장 p95 500ms 목표는 미달이며 측정은 단발성이다.
- 격리 DB 집중 테스트 74건 통과. Dashboard typecheck, 변경 파일 ESLint, production build 통과. 기존 광범위 발행 테스트는 87건 중 80건 통과, 7건 실패(이전 정책 fixture 기대값 및 TestClient/DB 상태 불일치). 이 7건을 성공으로 처리하지 않는다. 테스트 과정에서 운영 Blogger에 쓰기 요청을 보내지 않았다.
- 운영 API·Dashboard·Publication Worker 교체와 1440px/390px 브라우저 확인, 운영 전후 기록 및 최종 Git 결과는 다음 체크포인트에서 기록한다.

## 사용량 제한 중단 후 재개

- 중단 지점: 기능 커밋 `7fabe2a`와 운영 Migration 080 완료. API·Dashboard·Publication Worker는 보호 스크립트로 정상 종료·기동했으나, Dashboard는 `.runtime/validated-source.json`에 지정된 이전 격리 빌드를 제공해 새 상위 탭이 보이지 않았다. 읽기 전용 Playwright 1440px·390px 첫 실행 2건 실패는 이 빌드 불일치가 원인이다.
- `scripts/apply-verified-changes.ps1`의 검증·격리 빌드·서비스 반영 절차를 확인했다. 사전 ruff에서 신규 코드 스타일 2건을 발견해 수정했다. 기존 운영 DB 설정 revision 12는 그대로이며 오래된 queued Trends Job 1건은 Auto grant가 없다. 실제 사용자의 원고에 폐기·복원을 실행하지 않았다.
- 다음 단계: 변경 코드 커밋 후 검증된 격리 빌드를 반영하고, Playwright 및 운영 정합성을 다시 측정한다.

## 운영 반영 체크포인트

- 표준 반영 스크립트는 ruff·mypy·격리 테스트 39건·Python wheel·Dashboard lint/typecheck/build를 통과하고 커밋 전용 `.next-p5-255f6ccd44a1` 빌드를 만들었다. API에 기존 연결 1건이 있어 보호 스크립트가 종료를 거부해 전체 교체는 중단됐다. 강제 종료하지 않았고 Research Worker는 계속 실행됐다.
- 검증된 빌드로 Dashboard만 정상 종료·기동한 뒤 PC Playwright는 통과. 모바일 테스트는 PC 전용 컬럼을 선택해 실패했으며, 모바일 제목 아래 출처를 배지로 표시하도록 바꿔 재검증한다. 실제 원고 폐기나 Blogger 쓰기 테스트는 운영에서 하지 않았다.
