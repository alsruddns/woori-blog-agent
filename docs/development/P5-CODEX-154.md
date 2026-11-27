# P5-CODEX-154 예약 Automation ID 혼동 수정

## 작업 기록

- 작업 ID: P5-CODEX-154
- 작업 일시: 2026-11-16 13:17 KST
- 변경 사유: `current_session_automation_id_mismatch`로 Fed·SEC 예약 연구가 중단됨
- 기존 문제: 2026-11-14 10:55 KST의 실제 Desktop 예약 호출은 `fed-sec`였지만 연구 단계 명령이 `--automation-id automation-7`을 전달했다. 두 ID는 서로 다른 예약이다. Resolver가 ID 불일치를 거부한 뒤 원고와 전달 파일은 생성되지 않았다. 사후 Import 조회에서 동일 event-group 및 시간대에 일치하는 Import/audit 기록을 찾지 못했다.
- 변경 목적: `fed-sec` 예약 프롬프트에서 실제 등록 ID와 다른 미국 정치 예약 ID를 선택하지 않도록 명시한다.

## 변경 전 / 변경 후

- 변경 전: `fed-sec` TOML 프롬프트에 여러 예약의 공통 Blogger 매핑이 나열되어 있었고, `automation-7`을 미국 정치 대상으로 명시했지만 `fed-sec` 자체의 CLI ID를 고정하지 않았다.
- 변경 후: `fed-sec`에 `--automation-id fed-sec`를 반드시 사용하고 `automation-7`로 대체하지 말라는 전용 지시를 추가했다. ID 또는 현재 호출이 다르면 작업을 중단하도록 했다.
- 예약 ID, 활성 상태, RRULE, 모델, 대상, 언어, Blogger 매핑, 작업 디렉터리는 변경하지 않았다. 과거 슬롯은 재생하지 않았고 연구·원고·Import·Blogger 쓰기를 수행하지 않았다.

## 변경 파일과 검증

- 로컬 Codex task 설정: `%USERPROFILE%\.codex\automations\fed-sec\automation.toml` (Git 외부)
- 원본 백업 및 SHA-256 manifest: `%USERPROFILE%\.codex\automation-backups\P5-CODEX-154-20261116T041754Z\`
- 개발 기록: `docs/development/P5-CODEX-154.md`
- 검증: TOML 재파싱 성공, 프롬프트 marker 및 수정 후 SHA-256 확인, `id/status/rrule/model/target/cwds/created_at` 보존 확인.
- Import 추적: `us-politics-fed-sec-20261114`와 2026-11-14 10:00–12:00 KST의 영문 scheduled export를 DB에서 조회했다. 일치하는 Import 행이나 관련 audit event는 0건이었다.
- 자동화 엔드투엔드 실행: 미실행. Codex Desktop Scheduled UI에서 변경 프롬프트가 반영됐는지와 다음 공식 `fed-sec` 실행, Import Receipt는 아직 확인되지 않았다. UI 실행 경로는 현재 세션에서 사용할 수 없었다.
- PostgreSQL 감사: `agent.p5_codex_154.started` 및 `agent.p5_codex_154.completed` 이벤트를 추가했다. 실행 작업 중 Blogger 쓰기 0건.

## 변경 결과 및 남은 문제

- 예약 프롬프트의 명확한 ID 혼동 원인은 수정했다. 이 변경은 예약 원고 작성/Import가 성공했다는 의미가 아니다.
- 다음 Desktop 예약 호출에서 해당 대화의 `Automation ID: fed-sec`와 CLI의 `--automation-id fed-sec`가 일치해야 한다. 그 동일한 호출에서 resolver, 정책, 중복, 근거, envelope, Import Receipt를 각각 확인해야 한다.
- 실패한 과거 실행의 exact occurrence ID는 resolver 단계에서 생성되지 않았다. 일치하는 Import/audit 행은 조회되지 않았지만 Desktop UI/Receipt 교차 확인과 로컬 프롬프트의 재로드 여부는 미확인이다. 과거 슬롯을 재생하지 않는다.
- 코드 테스트: 실행 대상 코드 변경 없음. TOML 구조 및 불변 task 설정만 직접 검증했다.
- 브랜치: `develop`. 커밋 해시는 이 기록의 `git log` 항목으로 확인한다. 원격 푸시는 이 기록 커밋 후 실행한다.
- 관련 문서: `docs/operations/scheduled-outage-recovery.md`, P5-CODEX-131 및 P5-CODEX-140 예약 연구 계약.
