# P5-CODEX-110 — 발행 제어 및 큐 UX 개선

## 작업 기록

- 작업 ID: P5-CODEX-110
- 작업 시각: 2026-11-03 (Asia/Seoul)
- 변경 사유: 운영자가 발행 간격을 조정하고, 예약 원고 우선순위와 그리드 수동 큐 등록을 명확하게 사용할 수 있도록 개선. 추가로 폐기 및 설정 변경 사유 입력에 편집 가능한 기본값을 제공.
- 기존 문제: 전역 발행 간격의 화면 변경 경로가 없었고, 자동 발행 큐에서 예약 원고가 Trends보다 우선한다는 점이 일관되게 강제되지 않았음. 그리드의 수동 발행 동작이 상세 시트를 열었고, 폐기·운영 설정 사유를 매번 입력해야 했음.
- 변경 목적: PostgreSQL에 영구 저장되는 전역 간격 변경, `scheduled > manual > trends` 공통 큐 처리, 상세 시트를 열지 않는 명시적 수동 큐 등록, 두 사유 입력란의 실제 value 기본값을 제공.

## 변경 전후

- 변경 전: API에는 `global_publish_min_interval_minutes` 설정이 있었지만 Dashboard 직접 수정 UI가 없었음.
- 변경 후: 자동화 설정에서 30~1440분으로 값을 편집하고 기존 revision 확인·감사 경로를 통해 저장한다. 기본값은 30분이며 Trends 수집 간격 30분과 별개 설정이다.
- 변경 전: 자동 발행 처리 우선순위가 경로별 tick 호출과 Job 선택에서 완전히 일치하지 않았음.
- 변경 후: 신규 적격 자동 원고는 예약 우선, 그 다음 명시적 수동 요청, 마지막으로 Trends 순으로 처리한다. Trends 내부에서는 기존 EN→KO→JA→ZH 순서를 유지한다. 모두 기존 공통 발행 간격·승인·적격성·멱등성 검사를 따른다.
- 변경 전: 그리드 수동 발행 버튼은 상세 시트 진입 동작과 연결되어 있었음.
- 변경 후: 버튼은 정확한 Content Version 및 발행 적격성을 확인하는 발행 확인 모달을 열고, LIVE 기본 또는 사용자가 고른 Draft 요청을 기존 수동 승인 큐 API에 등록한다. 큐 등록 완료와 실제 게시 완료를 구분한다.
- 변경 전: 원고 폐기 사유 입력란은 비어 있었음.
- 변경 후: 개별·일괄 폐기 모달을 열 때 `폐기처리 하기로 결정함`을 textarea의 실제 value로 넣고, 사용자가 수정할 수 있다. 기존 10자 검증과 API 감사 사유 전달은 유지한다.
- 변경 전: 자동화 설정 변경 사유 입력란은 비어 있었음.
- 변경 후: 화면 진입 시 `운영 목적을 위해 설정을 변경함`을 실제 value로 넣고, 확인 모달 및 후속 변경에 그대로 유지한다. 기존 10자 검증·위험 작업 체크·revision 충돌 확인·감사 저장은 유지한다.

## 운영 보호 및 적용 상태

- 운영 API의 읽기 확인에서 설정 revision 14를 확인했다. Trends 수집 ON/30분, Codex 자동 원고 ON, 전체/Trends/예약 자동 발행 ON, 수동 발행 ON, 긴급 정지 OFF, 공통 발행 간격 30분이었다. 이 작업은 해당 설정을 변경하지 않았다.
- Research Worker와 Publication Worker의 관측 revision은 14였다.
- 읽기 전용 DB 조회에서 자동 발행 큐에 실제 `manual` 대기 1건과 `trends_auto` 대기 1건이 확인됐다. Publication Worker를 재시작하면 실원고가 게시될 가능성이 있어 운영 Worker/API 프로세스는 재시작하지 않았다. 따라서 변경된 Worker 코드는 운영 프로세스에 아직 반영되지 않았다.
- Blogger API 쓰기 및 운영 원고 폐기 요청은 0건이다. 실제 Blogger LIVE 동작은 수행하지 않았다.
- 운영 DB 백업: `backups/20261103T001935Z.dump` (41,297,919 bytes). 백업 아카이브 카탈로그 검증 성공. 이 작업에는 DB migration이 필요하지 않았다.
- 기존 15개 예약 자동화 설정과 원고·Content Version·Publishing Job·발행 이력은 수정하지 않았다.
- P5-CODEX-099~101 보호 stash `stash@{0}`는 확인 후 그대로 보존했다.

## 수정 파일

- `apps/dashboard/app/operations/automation/controls.tsx`
- `apps/dashboard/app/publishing/publication-manager.tsx`
- `apps/dashboard/app/style.css`
- `services/api/woori/automation_auto.py`
- `services/api/woori/publication_worker.py`
- `services/api/tests/test_automation_controls.py`
- `services/api/tests/test_publication_queue_priority.py`
- `apps/dashboard/e2e/P5-CODEX-110-controls.spec.ts`
- `apps/dashboard/e2e/P5-CODEX-110-grid-publish.spec.ts`
- `apps/dashboard/e2e/P5-CODEX-110-discard-default-operational.spec.ts`
- `docs/development/P5-CODEX-110.md`

## 검증

- API 범위 테스트: `test_publication_queue_priority.py`, `test_automation_controls.py`, `test_publication_origin_controls.py`, `test_publication_discards.py` — 62 passed. 설정 revision 및 실제 reason 감사 payload, 폐기 사유·작업자 저장을 확인했다.
- Dashboard TypeScript typecheck — 통과.
- Mock API Playwright — 자동화 사유 기본값/설정 저장 및 발행 간격 변경, 그리드 수동 큐 등록: 데스크톱·모바일 4 passed.
- 실제 운영 GET 전용 Playwright 확인 — 폐기 모달 기본 사유 및 편집 가능성: 1440px·390px 2 passed. 변경 요청은 모두 차단했고 취소만 실행했다.
- 별도 기존 P107 operational spec은 출처 필터 기대값이 현재 운영 API 응답과 맞지 않아 원고 선택 단계에서 실패했으며, 폐기 확인 단계까지 도달하지 못했다. 이 실패는 본 변경의 폐기 기본값 검사와 별개이며, 기존 출처 필터 동작은 이번 검증으로 확인되지 않았다.
- `git diff --check` — 통과.
- 실제 운영 API/Dashboard/Worker에 신규 코드가 반영된 것은 아니다. 대기 중인 실제 발행 작업 보호를 위해 서비스 재시작은 보류했다.

## 남은 문제 및 후속 확인

- 대기 중인 실제 Publishing Job이 안전하게 완료되거나 운영자가 별도 처리한 후, 배포된 코드가 포함된 Dashboard/API/Publication Worker를 정상 절차로 반영하고 Worker revision을 확인해야 한다.
- 운영에서 신규 예약 원고의 우선 처리 효과는 실제 발행 전까지 미검증이다. 본 작업에서 실제 게시를 유발하지 않았다.
- 기존 P107 출처 필터 operational spec이 운영 응답과 불일치한 원인은 후속 조사 대상이다.
- 커밋 해시 및 원격 푸시 결과는 커밋 이후 이 문서의 후속 기록 또는 `git log`에 연결한다.

## 관련 문서

- `AGENTS.md`
- `docs/development/P5-CODEX-109.md` (존재 시 이전 기준)
- `docs/operations/zero-cost-policy.md`
