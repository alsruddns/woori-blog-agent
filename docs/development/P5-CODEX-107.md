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

## 최종 운영 검증

- 표준 반영 스크립트가 커밋 `576e502535b18841b2962bcf0c86471db1e11d89`의 검증된 격리 빌드를 생성했다. ruff·mypy·테스트 39건·Python wheel·Dashboard 전체 lint/typecheck/build 통과. API→Dashboard→Publication Worker→Research Worker를 기존 보호 스크립트로 정상 종료하고 순서대로 기동했다. 강제 종료 없음.
- 운영 API/Dashboard HTTP 200. Research Worker PID 33136, Publication Worker PID 35204 heartbeat running. 양쪽 자동화 정책 applied_revision 12, policy_applied true. Dashboard/API의 설정 revision 12. 수집 ON, 자동 원고 ON, 전체 Auto ON, Trends Auto OFF, 예약 Auto ON·LIVE, 수동 ON, 긴급 정지 OFF. 설정값 변경 없음. 자동화 제어센터 effective 표시도 예약 Auto 정상, Trends Auto 신규 실행 중지로 확인했다.
- 실제 운영 DB의 `manuscript_discards` 0건. Content Version 487, Publishing Job 40, 게시 기록 20, Import 135. 기준 백업 이후 원고·Import가 각각 3건, 게시 기록 1건 증가했으나 마지막 게시 Job은 20:21 KST 수동 lane이며 P107 작업의 Blogger 쓰기 테스트가 아니다. Blogger 쓰기 원장 62건의 마지막 기록도 20:21 KST로 반영 작업(22:55 KST) 이전이다. 과거 queued Trends Job 1건은 Auto grant가 없고 일괄 재실행되지 않았다.
- 운영 Dashboard 프록시 compact GET 실측: queue 1,035ms/6KB/0건, review 939ms/81KB/101건, published 934ms/34KB/20건, held 896ms/32KB/17건, auto_failure 920ms/14KB/7건, discarded 1,037ms/6KB/0건. 기준 2.2초/약 400KB와 달리 빈 응답까지 경량화됐다. 단발성 수치이며 p95 500ms 목표는 달성 검증되지 않았다.
- 읽기 전용 Playwright 1440px·390px 2건 통과. 기본 발행 관리 탭, Job 지연 조회, 출처 배지·필터, 개별 폐기 확인 모달 취소, 보관함, Job 탭 새로고침 URL 유지, 다크 테마, JS 오류 없음, 가로 넘침 없음. 스크린샷은 `docs/development/assets/P5-CODEX-107-publication-dark-{desktop,mobile}.png`, `P5-CODEX-107-{desktop,mobile}.png`.
- 미확인/남은 문제: 실제 사용자 원고 폐기·복원은 실행하지 않았으며 격리 DB 테스트로만 검증했다. `started_at` 정렬 기준 마지막 Google Trends 수집 성공은 22:10 KST로 현재 시각보다 오래됐다. 최초 ID 정렬 확인에서 20:10을 최신 행으로 잘못 읽었으나 시각 정렬로 정정했다. P107에서는 수집 설정을 변경하지 않았고 수집 주기 정상화까지 주장하지 않는다. 발행 자동화의 향후 정상 예약 원고 LIVE 성공도 이번 작업에서 새로 검증하지 않았다.
- 자기 참조 최종 문서 커밋 해시는 후속 `git log`에서 확인한다.

## 변경 파일과 이력

- DB: `scripts/080_publication_discards.sql`, `scripts/migrate.py`.
- API/Worker: `services/api/woori/publications.py`, `publication_discards.py`, `publication_origin.py`, `content_representatives.py`, `automation_auto.py`, `automation_controls.py`, `publication_worker.py`.
- Dashboard: `apps/dashboard/app/publishing/page.tsx`, `publication-manager.tsx`, `app/api/publications/[[...path]]/route.ts`, `app/style.css`.
- 검증: `services/api/tests/test_publication_discards.py`, `test_automation_controls.py`, `apps/dashboard/e2e/P5-CODEX-107-operational.spec.ts` 및 위 스크린샷.
- 관련 문서: `docs/development/P5-CODEX-099-101.md`, `P5-CODEX-103.md`~`P5-CODEX-106.md`, 프로젝트 `AGENTS.md`.
- 구현 커밋 `7fabe2a`, 수정·검증 체크포인트 `255f6cc`, 모바일 배지 `576e502`. 최종 문서 커밋은 `git log`에 이어서 기록된다.
