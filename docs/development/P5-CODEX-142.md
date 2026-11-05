# P5-CODEX-142 — Manual Run now 원고 조사·작성 경로 복구

- 작업 일시: 2026-11-05 13:03:07 KST 시작; 종료 시각은 감사 완료 이벤트 참조.
- 시작 HEAD: `4ee9a3133d8ede6e8eddb9ac6d208148711e22d2`, branch `develop` (시작 시 tracked worktree clean). 기존 stash 및 미추적 파일 보존.
- 작업 시작 감사: append-only `agent.work.started`, ID `372414`.

## 문제 및 원인

사용자 제공 Run now 결과는 `execution_mode=manual`, `local_status=not_found`, `draft_import_allowed=true`, `remote_status=not_checked`였다. 기존 `manual_codex_import` envelope와 handoff는 있었지만 P140 웹 조사 broker가 scheduled trigger만 허용했고, 활성 Desktop prompt도 Run now에서 자체 web-search 도구가 보일 때만 조사하도록 되어 있었다. 따라서 manual trigger가 확실하고 새 로컬 원고 작성이 허용되어도 웹 조사 없이 끝났다. 기존 manual identity도 재사용 Desktop thread ID에서 파생되어 같은 thread의 별도 Run now끼리 충돌할 수 있었다.

## 변경

- `scripts/manual-research-broker.py` 추가: generation preflight JSON을 stdin으로 받고, 현재 resolver가 동일한 공식 `automation_cron_run_now` 및 manual contract를 재검증한 뒤에만 조사한다.
- `services/api/woori/scheduled_research.py`: scheduled/manual 공용 Codex CLI 조사·증거 검증 경로 추가. Manual package는 `manual_run_id`에 연결되고 immutable `write_snapshot` 경로에 저장되며, source URL/title/snippet은 실제 `web_search` 결과와 대조된다. 검색 결과 날짜는 기존 14일 freshness rule을 적용하고, 출처 의미/권리 검토는 미완료로 표시한다.
- Manual broker는 `local_status=not_found|failed_only`, `draft_import_allowed=true`, `remote_status=not_checked` 조건을 요구하고 실제 resolver invocation 및 `manual_codex_import` contract를 preflight에 포함된 값과 정확히 대조한다. overall/remote `unknown`은 그대로 보존한다.
- 기존 RSS helper를 같은 manual identity/package schema에 연결했다. RSS는 고정 승인 카테고리에서만 대체 조사 경로이며, Codex 인증·사용량·capacity·timeout·billable credential 차단은 우회하지 않는다.
- `automation_invocation.py`: manual run ID를 thread가 아니라 resolver가 검증한 현재 turn ID에서 파생하도록 변경. 같은 turn 재시도는 동일 ID를 유지하고 다음 Run now turn은 새 ID를 얻는다.
- `codex_runner.py`는 기존 ChatGPT-auth 격리 실행만 사용한다. 별도 OpenAI API key/종량제 API fallback은 없다.
- `scripts/update-codex-automation-authoring-recovery.py`: 20개 활성 Automation prompt를 manual broker 경로로 갱신했다. ID/RRULE/주제/언어/대상/모델/status는 유지했다. 기존 1개 paused task를 변경하지 않았고 새 예약을 만들지 않았다.
- `docs/operations/zero-cost-policy.md`에 manual Run now의 동일한 Zero-cost 및 review-held Import 제한을 기록.

## 정책 및 운영 상태

- 현재 Codex CLI 점검: `auth=chatgpt`, model `gpt-6-luna`, version `codex-cli 0.166.0`, `api_key_fallback=false`; `billing_credential_names()`는 빈 목록.
- 로컬 Automation TOML: 21 cron 정의, 20 active / 1 paused. 20/20 활성 prompt에 manual 및 scheduled broker instructions가 있고 설정값을 스크립트가 저장 후 다시 읽어 확인했다.
- computer-use 스킬의 명시 지침은 Codex Desktop app UI를 자동 조작하지 못하게 한다. 따라서 native Desktop UI에서 prompt가 실제 로드된 상태는 확인하지 못했다. 로컬 TOML 저장과 재읽기만 검증했다.
- Manual Import는 `manual_codex_import` 및 기존 review-held lane을 유지한다. Scheduled Auto 권한을 상속하지 않고, Publishing Job 생성/공개 발행/Blogger 호출을 하지 않는다. remote duplicate 확인은 Import/Publicaton 경로에 남긴다.
- 실제 Desktop Run now E2E는 이 개발 turn에서 가장하지 않았고 실행하지 않았다. 새 Snapshot, 원고, ready 파일, Import Receipt, Publication Queue 항목은 이 작업으로 생성되지 않았다. 사용자 제공 실행 결과의 미검증 remote 상태도 변경하지 않았다.
- 운영 API/대시보드/Workers가 import하지 않는 로컬 resolver/broker 경로만 수정했으므로 서비스 재기동은 하지 않았다.

## 검증

- 집중 회귀: 45 passed.
- 전체 `services/api/tests`: 944 passed, pytest cache permission warning 1건(테스트 실패 아님).
- Ruff: 통과.
- mypy (`scheduled_research.py`, `automation_invocation.py`): 통과.
- py_compile: 변경 Python 모듈 및 broker/prompt updater 통과.
- Codex 검색 실제 실행, 원고 생성, Import Receipt, Desktop UI 반영, Blogger 게시: 이 turn에서 실행/검증하지 않음.

## 파일

- `scripts/manual-research-broker.py`
- `scripts/update-codex-automation-authoring-recovery.py`
- `services/api/woori/scheduled_research.py`
- `services/api/woori/automation_invocation.py`
- `services/api/woori/codex_runner.py`
- `services/api/tests/test_scheduled_research.py`
- `services/api/tests/test_automation_invocation.py`
- `docs/operations/zero-cost-policy.md`
- `docs/development/P5-CODEX-142.md`

- Local prompt backup: `C:\Users\achie\.codex\automation-backups\P5-CODEX-140-RETRY-20261105T041006Z`.
- 종료 감사, 커밋, push 및 최종 Git 상태는 후속 개발 기록/`git log`로 연결한다.

## Manual Run now 후속 실행 진단 — 2026-11-05

- 실제 Desktop 세션 `01a1a9f7-7e39-7091-9bc4-3dbbc95b5934`, turn `01a1a9f7-8078-7573-a23b-d16846861eee`, Automation `automation-3`, trigger `automation_cron_run_now`를 읽기 전용으로 확인했다. 실행은 13:28:52 KST경 시작해 13:29:13 KST경 끝났고, 보고된 지속 시간은 21.485초다.
- 해당 실행 prompt에는 `manual-research-broker.py`와 `scheduled-research-broker.py` 경로가 모두 포함돼 있었다. Tool trace에는 Resolver와 `scheduled_duplicate_check.py`만 있고 manual broker/Codex 검색 호출은 없다. Desktop은 명시적 실행 오류 없이 턴을 정상 완료했다.
- 따라서 현재 관찰된 실패는 API/Research Worker/Publication Worker의 오래된 코드나 heartbeat가 아니라, preflight 후 같은 Desktop turn에서 broker를 호출하지 않고 끝난 실행 흐름이다. 서비스 재기동은 broker 호출을 발생시키지 않으므로 필요하지 않으며 수행하지 않았다.
- Preflight 결과는 사용자가 제공한 대로 `local_status=not_found`, `draft_import_allowed=true`, `remote_status=not_checked`, `overall_status=unknown`으로 유지한다. 이번 run에서 웹 조사, Snapshot, 원고/ready 파일, Import Receipt, Publication Queue 결과는 확인되지 않았다. Blogger 쓰기는 0건이다.
- 이 관찰은 broker의 실제 Desktop E2E 성공을 입증하지 않는다. 같은 완료된 turn을 재실행하거나 과거 run을 재사용하지 않았다. 후속 신규 Run now에서 broker 호출과 그 이후의 Snapshot → 원고 → Import Receipt를 별도로 확인해야 한다.
- 후속 진단 완료 감사: append-only `agent.work.completed` ID `373089`. 문서 커밋 해시는 `git log`의 후속 문서 기록으로 연결한다.

- ?? ??: append-only `agent.work.completed` ID `372526`; manual Desktop E2E? Desktop UI prompt load? ????? ????. ?? ?? `95934ce`; ? ?? ??? ?? ?? `5af2d4f`. ?? ?? ?? ??? `git log`?? ????.
