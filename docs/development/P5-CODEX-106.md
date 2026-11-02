# P5-CODEX-106 — 자동화 설정 저장 및 신규 예약 원고 LIVE 제어

- 작업 일시: 2026-11-02 KST
- 브랜치/기준: `develop` / `d485d2396611559484a91c83dac1d5769156a977`
- 관련 문서: `P5-CODEX-099-101.md`, `P5-CODEX-103.md`, `P5-CODEX-104.md`, `P5-CODEX-105.md`, `docs/operations/scheduled-outage-recovery.md`
- 현재 커밋: 본 기록의 자기 참조 해시는 후속 Git log와 최종 추가 기록으로 연결한다.

## 기존 문제와 확인된 원인

일일 예약 원고 스위치의 확인 모달은 변경 사유가 비어 있어도 적용 버튼을 활성화했다. 저장 함수는 10자 미만 사유에서 API 요청 전 반환했고, 오류 안내가 모달 밖에만 표시됐다. 따라서 체크박스를 선택해도 설정은 저장되지 않았다. Draft/LIVE 및 Blogger 범위는 화면에서 선택할 수 있지만 전체 자동 발행을 켜는 요청 외에는 저장 경로가 없었다. 5초 조회가 이전 응답으로 새 값을 덮을 수 있었고, Worker 적용 토스트는 저장 revision에 묶여 있지 않았다.

백엔드 신규 자동 발행 적격성 검사는 예약 원고에도 수동 발행용 `_assess`의 개별 승인 조건을 적용했다. 별도의 기존 예약 근거·권리 검사가 있음에도 미래 예약 원고가 무조건 막힐 수 있었다. 구형 예약 Import 전수 스캔 함수는 수동 Worker 순회에서 호출되어, 별도 예약 정책을 켜면 과거 Import로 Job을 만들 위험이 있었다. 운영 예약 정책 이벤트는 확인 시점에 `disabled`였다.

## 변경 목적과 적용

- 모든 설정 변경에 변경자 2자·사유 10자 검증을 화면과 확인 모달에 표시한다. 저장 성공 응답 후에만 최신 값을 재조회하고 저장 revision과 Worker ACK가 일치할 때 적용 완료를 표시한다. 충돌 시 모달을 닫고 최신 상태를 재조회해 새 요청으로 다시 시도할 수 있게 한다.
- Draft/LIVE 및 대상 Blogger를 독립적으로 저장한다. 전체 자동 발행이 ON인 상태의 변경도 확인 절차를 거치며, LIVE 선택은 별도 체크가 필요하다. 백엔드도 LIVE 전환과 대상 Blogger 유효성을 확인한다.
- 예약 원고는 실제 Import/occurrence/receipt 기원 확인과 기존 `_scheduled_eligibility` 근거·권리·형식 검사를 사용한다. 일반 원고의 수동 승인 값을 사실 검증 통과로 바꾸지 않는다. 기존 P099 정적 평가, 최신 Content Version, HTML/중복 검사는 유지한다.
- 신규 revision 기반 자동 발행 경로만 Worker에서 Job을 생성한다. 구형 예약 Import 전수 스캔을 일반 순회에서 제거해 과거 Job 및 Import 재활성화를 막는다. 기존 예약 정책 이벤트는 별도 정확한 Blogger 범위 승인으로 유지한다.
- 운영 반영 전 검토에서 신규 경로의 예약 정책 일일 한도 누락을 확인했다. 기존 KST 일일 한도를 신규 Job 생성에도 적용하고, 한도 도달 시 감사 차단 사유를 남긴다. 이는 한 Blogger에서 하루에 발행할 수 있는 예약 원고 수를 제한한다.

## 운영 사전 확인 및 백업

- PostgreSQL 16은 Automatic/Running; API·Dashboard·Research·Publication Worker는 기존 PID로 정상 실행 중이었다. Crypto 클러스터와 다른 서비스는 건드리지 않았다.
- 운영 백업: `backups/20261102T080937Z.dump` (`pg_restore --list` 검증, 복원 리허설은 미실시).
- 운영 schema 79. 이번 변경의 DB Migration 없음.
- 최초 설정 revision 9: 수집·자동 작성·수동 발행 ON, 전체/Trends/예약 자동 발행 OFF, 긴급 정지 OFF, Draft, 대상 없음.
- 현재 변경 직전 스냅샷: `.local/p106-before.json` (38 Publishing Job, 18 게시 기록, 58 Blogger 쓰기 원장, 15개 예약 TOML SHA-256). 초기 조사 때는 Job 37건이었으며 다른 정상 작업으로 증가했다. 이 스냅샷의 기존 행은 변경하지 않는다.
- Blogger 계정 제한 해제 신고와 읽기 성공은 쓰기 성공의 증거가 아니다. 운영 테스트 글은 만들지 않는다.

## 변경 파일

`AGENTS.md`; `services/api/woori/automation_auto.py`, `automation_controls.py`, `publication_worker.py`; `services/api/tests/test_automation_controls.py`; `apps/dashboard/app/operations/automation/controls.tsx`, `controls.module.css`; `apps/dashboard/e2e/P5-CODEX-106-controls.spec.ts`; Dashboard 1440px/390px 증거 이미지 2개; 본 기록.

## 검증 체크포인트

- 격리 DB의 변경 범위 75 tests passed: 설정/기원/예약 근거/일일 한도 검사. Ruff 및 세 모듈 strict mypy 통과.
- Dashboard ESLint, TypeScript, 독립 Production Build `.next-p5-p106-final` 통과.
- Mock API Playwright 데스크톱 1440px·모바일 390px 각 2개, 총 4건 통과: 전체 스위치, 모달, LIVE 이중 확인, Draft/LIVE 저장, 저장 실패 유지/재시도, 새로고침 revision, 가로 넘침 없음. 다크 테마 이미지 저장. 실제 Blogger 쓰기 0건.
- 옛 `test_publications.py`/`test_blogger_live_policy.py`의 선택 실행 3건은 구형 fixture가 현행 수동/자동 wire guard를 구성하지 않아 실패했다. P104 기준선에 이미 존재하던 실패이며, 제품의 발행 차단을 약화시켜 맞추지 않았다. 같은 실행의 다른 8건은 통과했다. 운영 반영 전 신규 경로의 Mock 검증은 별도로 유지한다.

## 운영 반영 체크포인트

아래 항목은 코드 반영과 실제 설정 활성화 후에만 기입한다. 활성화 전에는 기존 전체/예약 자동 발행 OFF를 유지한다.

## 남은 문제

- 인증된 읽기 전용 Blogger ID 확인, 별도 예약 정책 이벤트의 정확한 4개 Blogger 범위 활성화, 운영 프로세스의 안전한 코드 반영, 설정 revision/Worker ACK/과거 Job 불변 검증, LIVE 성공 여부 확인, 최종 Git commit/push.
