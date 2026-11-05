# P5-CODEX-150 — Manual Run now 중복 사전검사 HTTP 422 복구

## 작업 기록

- 작업 일시: 2026-11-05 KST
- 작업 ID: `P5-CODEX-150`
- 브랜치: `develop`
- 시작 HEAD: `953459019c1afaef199381642598c4949eea80b4`
- 시작 감사 이벤트: `agent.work.started`, ID `378486`
- Blogger 쓰기 / 유료 API 호출: 0건

## 원인

- 실패 세션은 공식 Desktop Run now로 확인됐으며 Automation은 `automation-2`(일본 증시 마감, `ja`/`JP`)였다.
- 실제 명령 인자는 `--target-blog-id "<registered Blogger ID>"`였다. 이 값은 프롬프트 예시 placeholder이며 등록된 숫자 ID가 아니다.
- 동일한 입력을 로컬 Dashboard/API 경로에 읽기 전용으로 재현한 결과 HTTP 422, `body.target_blog_id`, 숫자 ID 정규식 불일치를 확인했다. FastAPI DTO가 비숫자 Blogger ID를 거부하므로 중복검사 함수 및 중복검사 감사 이벤트에는 도달하지 않았다.
- 현재 활성 `ja` Blogger ID `7562596540375659150`을 운영 DB에서 읽기 전용으로 확인했다. 실패 Run now는 조사·원고·Import·발행을 실행하지 않았다. 그 Run을 재생하거나 과거 슬롯을 다시 실행하지 않았다.

## 수정

- `automation-research-stage.py`에서 Blogger ID를 숫자 5–32자리로 사전검사해 placeholder가 HTTP 요청으로 전달되지 않도록 했다.
- `scheduled_duplicate_check.py`도 같은 형식을 argparse 단계에서 거부한다.
- Automation 공통 프롬프트에 예시 placeholder를 실제 값으로 치환하라는 지침과 ID 확인 실패 시 중단 코드를 추가했다.
- 일본 마감 `automation-2` 프롬프트에 현재 확인된 `ja`/`JP` Blogger ID를 명시하고, 활성 매핑 변경 시 재확인하도록 했다.
- 기존 prompt updater를 사용해 활성 Automation 프롬프트 20개를 점검했다. 새 공통 지침이 미반영된 `automation-2`만 추가 변경됐다. ID, 활성 상태, RRULE, 모델, 대상, 프로젝트 경로는 유지했다.
- prompt updater 백업: `C:\Users\achie\.codex\automation-backups\P5-CODEX-147-20261105T085845Z`.

## 검증

- 실패 입력의 실제 Dashboard/API 재현: HTTP 422, 필드 `body.target_blog_id`, 숫자 ID 형식 위반.
- 격리 회귀 테스트: **28 passed**. 잘못된 ID는 HTTP/사전검사 호출 전에 차단된다.
- Ruff: 통과.
- `py_compile`: 통과.
- 20개 로컬 활성 프롬프트에 placeholder 치환 지침이 있으며, automation-2에 숫자 Blog ID 힌트가 있음을 확인했다.
- 공식 Codex Desktop UI가 변경된 TOML 프롬프트를 다시 읽었는지는 확인하지 못했다. 신규 Run now의 중복검사 통과, Snapshot, 원고, Import Receipt, Publication Queue 및 LIVE 결과도 아직 검증되지 않았다.

## 운영 영향 및 남은 검증

- 오류 원인은 서비스 heartbeat나 재기동이 아니며 API/Dashboard/Worker 코드 변경도 없으므로 서비스 재기동은 하지 않았다. PC 재부팅도 필요하지 않다.
- 다음 공식 Run now에서 동일 Automation 설정을 사용하되 정확한 숫자 Blogger ID를 전달하는지 확인해야 한다. 이후 수동 계약에 따른 조사·원고·Import를 별도 확인한다. 예약 Import의 자동 LIVE 권한은 수동 Run now에 상속되지 않는다.
- 실제 예약/수동 실행 완료 전에는 작성 및 발행 복구 완료로 간주하지 않는다.

## 수정 파일 및 커밋

- `scripts/automation-research-stage.py`
- `scripts/scheduled_duplicate_check.py`
- `scripts/update-codex-automation-authoring-recovery.py`
- `services/api/tests/test_automation_research_stage_cli.py`
- `services/api/tests/test_scheduled_duplicate_cli.py`
- `services/api/tests/test_update_automation_authoring_recovery.py`
- `docs/development/P5-CODEX-150.md`
- 최종 커밋 해시와 감사 완료 이벤트는 후속 Git 기록에서 확인한다.
