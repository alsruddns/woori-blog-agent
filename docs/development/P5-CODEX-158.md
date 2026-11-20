# P5-CODEX-158 — 예약 Automation 조사 완료 결과 대기 보강

## 작업 기록

- 작업 일시: 2026-11-17 (Asia/Seoul)
- 작업 ID: `P5-CODEX-158`
- 브랜치: `develop`
- 시작 HEAD: `7eac721238f15401b3f4657fb70ca0f37df5cc24`
- PostgreSQL 감사: `agent.p5_codex_158.started` ID `695621`, `agent.p5_codex_158.completed` ID `695622`
- 변경 사유: 사용자가 예약 원고 Automation이 “조사 단계 명령이 아직 종료되지 않아 원고 작성이 안 된다”고 보고함.

## 기존 문제와 실행 증거

- `automation-3`의 2026-11-17 10:30 KST 실행을 Codex Desktop thread 기록에서 확인했다. `scripts/automation-research-stage.py` 명령은 **completed, exit code 0**으로 끝났고 최종 JSON에 `status=evidence_available`, `source_count=3`, `research_package_path`, `preflight_json_path`가 반환됐다.
- 같은 Automation 응답은 명령이 아직 실행 중이라며 종료했으며, 그 결과 원고·검증·핸드오프·Import를 진행하지 않았다. 실행 결과와 사용자에게 표시된 최종 메시지가 서로 어긋났다.
- 저장된 Research Package도 `evidence_available`이며 출처 3건을 담고 있다. 다만 preflight는 `local_status=not_found`, `draft_import_allowed=true`인 반면 `remote_status=not_checked`, 전체 `status=unknown`이다. 원문 출처는 Import Worker의 확인, 의미·권리·편집 검토를 거치지 않았다.
- 이 실행에 대한 incoming/ready 원고 및 Import receipt를 찾지 못했다. 과거 occurrence를 재실행하거나 작성·Import를 대신 수행하지 않았다.

## 변경 목적 및 전후 상태

- 변경 전: 자동화 지침에는 같은 명령의 결과를 기다리라는 규칙이 있었지만, 최종 응답이 완료된 명령 JSON과 모순되어 조사 이후 단계가 중단될 수 있었다.
- 변경 후: 기존 `automation-3` 프롬프트에 terminal JSON 완료 장벽을 추가했다. 첫 tool action으로 조사 명령을 실행하고, 같은 프로세스/session을 terminal 결과까지 기다리며, JSON과 exit code를 읽은 뒤 같은 Automation turn에서 `evidence_available`이면 원고·검증·핸드오프·Import 영수증 확인을 계속하도록 했다. 중간 상태나 파일 존재만으로 최종 상태를 추정하지 못하게 했다.
- Automation ID, 활성 상태, 일일 10:30 KST 일정, 모델, 프로젝트 및 대상은 보존했다. 다른 Automation을 복제·변경하지 않았다.

## 수정 및 검증

- 저장소 파일: `docs/development/P5-CODEX-158.md`
- Codex Desktop automation: `automation-3` prompt updated via `mcp__codex_app__automation_update`.
- 검증: Automation 응답에서 업데이트 성공을 받았고, 로컬 설정을 다시 읽어 barrier 문구·`ACTIVE` 상태·일일 10:30 KST RRULE·`gpt-6-luna` 모델을 확인했다.
- 코드 변경 없음. Blogger 쓰기와 Import는 0건이다. 새 자동화 실행은 생성하거나 강제로 시작하지 않았다.
- 관련 문서: `docs/operations/scheduled-outage-recovery.md`, `docs/development/P5-CODEX-157.md`.

## 커밋과 남은 확인

- 개발 기록 커밋: 후속 `git log`에서 확인한다.
- 원격 푸시 결과: 개발 기록 커밋 후 `origin/develop`으로 푸시한다.
- 남은 확인: 다음 자연 예약 실행에서 tool 결과가 완료될 때까지 대기한 뒤 같은 turn에서 원고 envelope, 검증, ready handoff 및 Import receipt까지 도달하는지 확인한다. 원격 중복 확인과 각 발행 gate는 별도로 유지된다.
