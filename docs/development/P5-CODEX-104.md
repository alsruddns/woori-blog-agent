# P5-CODEX-104 — Blogger 자동 발행 경로별 독립 제어

작업일: 2026-11-02 KST. 브랜치 develop, 기준 HEAD `7108f9b`.

## 변경 이유와 범위

P103의 전체 자동 발행 제어는 생성 경로를 구분하지 않았다. Trends와 Desktop 예약 원고를 별도로 허용하고, 수동·불명 원고 및 이전 대기 Job을 자동 발행에서 제외한다. P099+101 기능과 기존 시작 스크립트를 재작성하지 않는다. stash `c879d3dfe08a87baae278944ba6c0caf9426847a`를 유지한다.

## 구현

- Migration 078: 기존 controls에 `trends_auto_publishing_enabled`, `scheduled_auto_publishing_enabled`를 모두 false로 추가한다. 각 경로의 독립 UUID epoch와 활성화 시각을 추가하고 revision을 증가시킨다. 기존 immutable grant에 origin, source_epoch, Import/native Content Version FK를 추가한다. 과거 grant의 origin은 unknown이며 소급 권한을 부여하지 않는다. 기존 테이블·콘텐츠·평가·감사·Job을 삭제하지 않는다.
- 공통 `publication_origin.classify/decide`: 실제 Import/native Version/대상 Blogger 관계로 판정한다. Trends는 완료된 authoring Job → imported request → topic/observation 계보를 확인한다. 예약은 정확한 Automation ID·실제 RRULE 슬롯·occurrence·대상 Blogger와 로컬 Desktop 실행 증거를 재검증한다. 문자열 제목/본문은 판정에 사용하지 않는다. 수동·모호한 원고는 차단한다.
- `scheduled_execution_receipts`: 공통 실행 식별 CLI에서 검증된 scheduled 실행만 로컬 원자적·배타적 receipt로 보존한다. 예약 설정 15개와 프롬프트는 수정하지 않는다. receipt를 단독 신뢰하지 않고 원본 Desktop session의 trigger/checkout/Automation/슬롯을 다시 확인한다. 프로젝트 파생 occurrence는 scheduler 발급 ID로 주장하지 않는다. 과거 실행 증거가 없는 원고는 unknown으로 남는다. 기존 Import는 계속 가능하며 이 증거는 사실·게시 승인이 아니다.
- `automation_controls`: 인증·strict boolean·revision 경합 검사·변경자/사유·append-only 감사 유지. 경로 ON은 별도 확인, 저장된 모드가 LIVE이면 별도 LIVE 확인이 필요하다. 경로별 OFF/ON은 해당 epoch만 교체하므로 다른 경로/수동 권한에 영향을 주지 않는다. 전체/방식/대상 변경은 기존 global epoch를 교체한다. 두 활성화 시각 이후 완료된 Import와 새 Job만 허용한다. 기존 원고를 편집한 시각으로 원래 Import 완료 시각을 갱신하지 않는다.
- 자동 enqueue, Worker admission, 실제 Blogger HTTP 직전 guard에서 공통 정책을 적용한다. 전체/경로 OFF, 긴급 정지, API 제한, 대상/Version/Import/epoch 불일치, 중복·품질 조건을 검사한다. wire 직전 최신 품질/Version/동일 Import 게시 기록을 재확인한다. 최신 정적 품질 평가가 없거나 unsafe HTML이면 차단한다. 기존 출처·권리·사람 검토·OAuth·게시 준비 조건을 완화하지 않는다. 설정 저장과 wire HTTP는 기존 공통 DB advisory lock으로 직렬화한다. DB 장애는 fail-closed다.
- 차단 사유를 `automation.origin_publication.blocked` 감사에 보존한다. 같은 Version/대상/revision/사유/단계는 중복 기록하지 않는다. 비활성·만료 경로 Job은 선택하지 않고 보존한다. 경로 밖 후보 때문에 이후 정상 후보가 영구적으로 밀리지 않도록 후보 검사와 최대 생성 10건을 분리했다.
- Dashboard 자동화 제어센터에 경로별 스위치 2개를 전체 자동 발행 카드 안에 추가했다. 전체 OFF에서도 하위 설정 저장 가능, 실제 적용은 전체 OFF로 차단임을 표시한다. 수동 발행·긴급 정지는 독립이다. 발행 Worker ACK는 `automation-controls/2`여야 적용 완료로 표시한다. 변경 없는 Research의 `/1` ACK는 기존 수집/작성 정책에 유효하다.

## 변경 파일

- `scripts/078_origin_publication_controls.sql`, `scripts/migrate.py`, `scripts/provision-test-database.py`
- `services/api/woori/publication_origin.py`, `scheduled_execution_receipts.py`, `automation_controls.py`, `automation_auto.py`, `publications.py`
- `scripts/resolve-codex-automation-run.py`
- `apps/dashboard/app/operations/automation/controls.tsx`, `controls.module.css`
- `services/api/tests/test_publication_origin_controls.py`, `test_automation_controls.py`
- `apps/dashboard/e2e/P5-CODEX-103-controls.spec.ts` (기존 공통 제어센터 회귀 확장), P104 운영 읽기 전용 E2E 및 스크린샷
- 본 개발 기록과 AGENTS.md의 최신 제어 계약

## 백업 및 운영 보호

- 운영 DB 백업 `backups/20261101T214940Z.dump`, pg_dump archive catalog 검증 완료. checksum/작업 전 37개 Job 상태/15개 automation.toml checksum/쓰기 원장을 ignored `.local/p104-before.json`에 보존했다.
- 운영과 물리적으로 분리된 schema78 테스트 DB 사용. test app의 운영 DB CONNECT 권한 없음 확인. 테스트 트랜잭션은 rollback한다.
- Migration078 운영 적용 및 재실행 확인. 두 경로 false, 기존 전체 false, 수집/작성/수동 true, 긴급 정지 false 유지. Migration은 실제 발행을 활성화하지 않았다.
- 기존 서비스 PID/Windows 소유자/checkout/instance identity와 작업 스케줄러 상태를 확인한 뒤 변경 서비스만 협력적 종료·교체한다. PostgreSQL16/Crypto/Research/15개 예약 작업을 중단하지 않는다. 강제 종료 금지.
- Google API 제한 상태, 로컬 긴급 정지, 운영 설정을 구분한다. 이번 작업은 외부 공급자 추가·유료 호출·Google 권한 변경·실제 게시를 수행하지 않는다.

## 검증

- 통합 범위 Python: **105 passed** (origin34 + P103 controls17 + editorial/automation invocation/P102 pending54).
- 안전 회귀: **88 passed / 8 failed**. 8개는 `test_blogger_live_policy.py`의 과거 무조건 쓰기 허용/오류 순서 가정이다. 변경 전 `7108f9b` 패키지를 별도 경로에 읽어 같은 8개 실패와 20개 통과를 재현했다. 보호 정책을 완화하지 않았으며 전체 suite green으로 보고하지 않는다.
- Mock Dashboard Chromium **10 passed**, desktop1440/mobile390. 독립 설정·ON 확인·취소·전체 OFF 표시·LIVE 별도 확인·긴급 정지·장애 화면·가로 넘침 없음/pageerror0 확인. P104 screenshot 4개 보존.
- 변경 Python Ruff 및 4개 정책 모듈 strict mypy 통과. Dashboard TypeScript/ESLint 및 독립 `.next-p5-p104-final` production build 통과. Next가 검증 중 갱신한 기존 next-env/tsconfig는 원본 bytes로 복원한다.
- 운영 프로세스 반영/실제 revision ACK/HTTP/UI/쓰기0/최종 커밋·push 결과는 아래 후속 체크포인트에 기록한다. 위 테스트는 자동 발행 운영 활성화 증거가 아니다.

## 남은 제한

실제 Blogger 쓰기 권한·수동 쓰기 성공은 이번 작업에서 검사하지 않는다. 자동 발행은 끝까지 OFF다. 예약 과거 원고에 실행 receipt를 조작·소급 생성하지 않으며, 증거 부족은 unknown이다. 15개 예약의 다음 실제 작성/Import 실적은 이번 변경 테스트와 별도 관찰 대상이다. 기존 8개 legacy 테스트는 현재 승인 계약에 맞춘 후속 갱신이 필요하다.

관련 문서: P5-CODEX-099-101.md, P5-CODEX-102.md, P5-CODEX-103.md. 자기 참조 커밋은 `git log --grep=P5-CODEX-104` 및 아래 후속 기록으로 연결한다.

## 운영 적용 체크포인트 — 2026-11-02 07:05 KST

- 구현 커밋 **`22c72ef`**. Migration078 적용 후 재실행도 정상이며 schema78 유지. 최종 설정은 인증된 실제 API PUT으로 저장하고 감사에 남겼다. **revision9: collection=true / auto_manuscript=true / global_auto=false / trends_auto=false / scheduled_auto=false / manual=true / emergency=false**. 기존 API 제한 게이트 false/사용자 제한 해제 보고/읽기 검사 기록은 변경하지 않았다. 자동 방식은 기존 Draft, 대상 목록은 비어 있다. 실제 Google 쓰기 권한은 미검증이다.
- 실행 중인 실제 발행 Job0/pending write0/자동 스위치3개 OFF를 먼저 확인했다. Publication28516은 지원되는 stop-file 요청으로 현재 작업 주기 후 정상 종료했다. 새 Publication32104는 기존 `manual-confirmed` 실행 모드를 유지한다. API28088 → **2940**, Dashboard30680 → **22536**은 Windows 소유자·정확한 checkout·PID별 instance identity를 확인한 협력적 종료로만 교체했다. 새 launcher는 API31244/Dashboard11344다. 실제 runtime applied_commit은22c72ef다. 강제 종료0, scheduler stop0, PostgreSQL/Crypto 변경0.
- Migration에서 저장한 두 경로 OFF 값이 프로세스 교체 후 API/DB/Dashboard에서 동일하게 읽히는 것을 확인했다. 이후 동일한 최종 값의 명시 저장으로 revision9가 되었고, **Publication32104 `/2` + Research10232 `/1` 모두 revision9/fresh PID ACK**를 확인했다. Research는 P104에서 실행 정책을 바꾸지 않아 재시작하지 않았다. `/1`은 수집/작성에만 호환 인정하며 발행 Worker의 `/1`은 적용 완료로 인정하지 않는다. 저장 직후 적용 대기에서 다음 heartbeat 적용 완료로 전환함도 확인했다.
- API health, 실제3100 제어센터/sources/manuscripts 모두 HTTP200. 정상 API 및 API503를 주입한 trusted repository authoring policy 모두 allowed=true/revision9. Import intake thread도 기존 PID10232의 ACK를 갱신한다. 이번 구간 새 운영 Import0건이므로 실제 신규 Import 성공을 주장하지 않는다.
- 실제 운영 읽기 전용 Chromium **2 passed** 추가: 1440/390 다크 테마, 스위치7개 최종 값, revision9, publishing engine2 ACK, 실행 가능 Job0, 쓰기 미검증 표시, 가로 넘침/pageerror0. 비GET API는 브라우저 테스트에서 차단했다. Mock10 + 실제2 = **12 browser passed**. `P5-CODEX-104-live-{desktop,mobile}.png` 보존. 초기 운영 테스트의 5초 ACK 대기는 정상 30초 Worker 주기보다 짧아 다음 poll을 기다리도록 수정했다. APIRequestContext의 Origin 없는403도 보안 정상 동작이며 실제 same-origin 브라우저 fetch로 검증했다. 제품 보안 게이트를 완화하지 않았다.
- 운영 감사 **282665**: 기존37 Job의 id/status/publication_state/remote_post_id/lane 및15 automation.toml checksum이 작업 전과 일치한다. 새 publication grant0, Blogger write operation0, live attempt0, Blogger 비GET 외부 호출 감사0. 기존 원장 전체도41 succeeded/15 failed로 동일하다. 실제 자동 Draft/LIVE 활성화0건, 수동 게시 실행0건이다.
- PostgreSQL16 Running/Auto PID6880 유지. WooriBlogAgent-Worker Ready/LastTaskResult0 유지. 기존 stash c879d3d 보존. 기존 두 `.playwright-mcp/` 미추적 디렉터리는 커밋 대상에서 제외했다.

### 별도 미완료 운영 관찰: Trends 수집 최신성

11개 지역의 가장 최근 성공 회차는 **2026-11-02 02:10 KST**이며 07:03 점검 시 새 회차는 확인되지 않았다. Research heartbeat/설정 ACK가 정상이라는 이유로 10분 수집 전체가 정상이라고 보고하지 않는다. 읽기 전용 점검에서 Research10232의 로컬 DB 연결(client port51934)에 해당하는 backend26692가 기존 `trend_grouping_proposals` 파생 비교 트랜잭션을 약4시간54분 진행 중임을 확인했다. 원본 query/인증정보를 출력하지 않았다. 별도 intake thread와 heartbeat는 계속 실행된다. 기존 P103의 168시간 관찰 간 비교 비용 문제가 남아 있는 상태이며, P104는 이 Worker/해당 트랜잭션을 취소·종료·재시작하지 않았다. 수집/작성 설정은 ON으로 유지했지만, **새 10분 회차 성공 및 다음 실제 자동 작성/Import 확인은 미완료**다. 이는 P104 경로별 발행 제어/프로세스 적용 완료와 구분한다. 파생 비교 비용 개선은 별도 후속 작업이 필요하다.

최종 고유 Python 결과는 **193 passed / 기존 baseline 동일 실패8**, 브라우저12 passed다. 전체 suite 통과나 실제 Google 쓰기 성공으로 과장하지 않는다. 최종 test/docs 커밋과 push SHA는 Git 후속 기록으로 연결한다.
