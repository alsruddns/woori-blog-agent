# P5-CODEX-151 — automation-16 topic 및 event-group 복구

## 작업 기록

- 작업 일시: 2026-11-05 (Asia/Seoul)
- 브랜치: `develop`
- 시작 HEAD: `9950a4b02bc34df659045d53e795ab1a085ef625`
- 시작 감사 이벤트: `agent.work.started`, ID `382839`
- Blogger 쓰기 / 유료 API 호출: 0건

## 확인 결과

- 대상 Automation: `automation-16`, 브라질 경제, `pt-BR`, 대상 국가 `BRA`, 등록 Blogger ID `2780805325207451782`.
- 활성 설정: `RRULE:FREQ=DAILY;BYHOUR=20;BYMINUTE=20`, `gpt-6-luna`, Local 프로젝트. 예약 ID·시간·언어·블로그 매핑은 변경하지 않았다.
- 2026-11-04 20:20 KST 실행의 실제 사전검사 입력에서 토픽 `Brazil fiscal framework and inflation-interest rate outlook`, event-group ID `br-economy-2026-11-04`를 확인했다.
- 해당 사전검사는 감사 이벤트 `351444`에서 `local_status=not_found`, `draft_import_allowed=true`, `remote_status=not_checked`로 끝났다. 같은 ID/제목의 DB Import가 없고, 저장소에도 해당 토픽의 Research Package가 없다. 기존 실행은 조사·원고·Import까지 진행되지 않았다.
- 이번 사용자 보고의 실행에서는 첫 research-stage 명령을 호출하지 않았다. 과거 occurrence를 재실행하지 않았다.

## 변경

- Prompt updater에 `automation-16`의 확인된 미완료 토픽과 event-group ID를 복구 hint로 추가했다. 동일한 이슈를 이어 쓰는 경우 이 쌍을 그대로 쓰고, 새로 선택한 별도 이슈는 자체적인 안정 ID를 사용하도록 안내한다.
- 기존 prompt updater로 로컬 활성 Automation 20개를 확인했다. 새 복구 hint가 필요한 `automation-16`만 수정했다.
- 변경된 로컬 TOML 백업: `C:\Users\achie\.codex\automation-backups\P5-CODEX-147-20261105T120952Z`.
- Automation ID, 상태, RRULE, 모델, 언어, 대상 Blogger, 프로젝트 경로는 보존했다.

## 검증 및 남은 단계

- Prompt updater 격리 회귀와 authoring/duplicate CLI 회귀: **29 passed**.
- Ruff, Python `py_compile`, `git diff --check`: 통과.
- 로컬 TOML에서 정확한 topic/event-group hint와 기존 예약 설정을 확인했다. 공식 Codex Desktop UI가 갱신된 TOML을 다시 읽었는지는 확인하지 못했다.
- 실제 새 공식 예약 또는 Run now에서 research-stage 실행, Research Snapshot, 원고 파일, Import Receipt는 아직 검증되지 않았다. 이전 실패 실행을 성공 처리하지 않았다.
- 이번 변경은 prompt updater와 로컬 Automation TOML뿐이므로 API/Dashboard/Worker 서비스 재기동은 하지 않았다.

## 수정 파일 및 커밋

- `scripts/update-codex-automation-authoring-recovery.py`
- `services/api/tests/test_update_automation_authoring_recovery.py`
- `docs/development/P5-CODEX-151.md`
- 최종 커밋과 append-only 완료 감사 이벤트는 Git history 및 운영 DB에서 확인한다.
