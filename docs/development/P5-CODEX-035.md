# P5-CODEX-035 — 무인 Blogger 게시 파이프라인 실증 점검

- 작업 ID: P5-CODEX-035
- 작업 시각: 2026-10-29 15:25 KST
- 브랜치: `develop`
- 작업 기준 커밋: `8b3338bf7e9c591fe4960a38252d231ecd30973e`
- 변경 사유: 실 운영 기준 Trends 수집부터 무인 원고 작성·수신·검증·Blogger 공개 게시까지 처음 0건이 되는 지점을 확인한다.
- 기존 문제: 앞선 기록은 Trends 수집과 Worker 실행을 성공으로 설명했으나, provider·후보·큐·실 발행 단계의 현재 상태 및 공식 예약 작업의 최신 기능 지원 여부가 서로 다른 시점의 자료에 흩어져 있었다.
- 목적: 실제 운영 PostgreSQL·로컬 파일·프로세스·실행 코드로 현재 상태를 대조하고, 허용되지 않은 쓰기나 Auto 전환 없이 완료/차단 범위를 확정한다.

## 실행 환경 및 보호

- 브랜치 `develop`, 시작 커밋 `8b3338b` 확인.
- Dashboard 3100 PID 15276, API 8100 PID 5872, API health `ok` 확인. 프로세스는 재시작하지 않았다.
- PostgreSQL에는 read-only 진단 쿼리만 실행했다. 원고·Research Package·OAuth·발행 기록·운영 설정은 수정하지 않았다.
- `.local/gpt-scheduled-import`에는 실제 예약 작업이 만든 입력 파일이 없었다.
- Publication Worker 프로세스 PID 20652는 현재 실행 중인 프로세스 목록에서 확인되지 않았고, `publication-worker.py --status` 및 Dashboard DB 상태는 heartbeat `stopped/stale`로 일치했다. PID 20652의 마지막 기록 시각은 2026-10-29 15:19 KST였다. 사용자 프로세스를 종료하거나 새 Worker를 중복 시작하지 않았다.
- Research Worker heartbeat도 마지막 기록 이후 stale이며, 현재 실행 상태를 성공으로 주장하지 않는다.
- `.playwright-mcp/`의 기존 사용자 소유 untracked 데이터는 건드리지 않았다.

## 실 운영 파이프라인 수치

운영 DB `woori_blog_agent`의 `operations_dashboard.dashboard_snapshot`과 `scripts/publication-worker.py --status`를 read-only로 조회했다.

| 단계 | 실제 값 | 확인 결과 |
|---|---:|---|
| 최근 24시간 Trends 관측 | 610 | 11개 geo 관측 존재, 최근 worker heartbeat는 stale |
| 최근 24시간 이슈 그룹 | 494 | 실제 관측보다 적은 고유 그룹 수 |
| 기사 후보 | 0 | 첫 파이프라인 단절 지점 |
| 후보 제외/보류 사유 집계 | 494 | 최소 점수 미달 494, 독자 가치·분석 적합성 사람 검토 494, 독립 출처 사람 확인 미완료 494, 공식 조사 대기 493, 교차 지역 그룹 검토 72, 광범위 질의 2 |
| 최근 조사 shortlist | 최대 4 | 실제 선택 기록 4건, `official_research_executed=false` |
| 24시간 Research Package | 1 | 기존 패키지 1건. 새 자동 조사 성공으로 세지 않음 |
| 생성 Provider | 연결 안 됨 | `provider_connected=false`, `provider_status=not_configured` |
| GPT 무인 생성/예약 실행 | 0 / 0 | 검증된 run 0, 예약 claim 0 |
| 예약 파일 자동 수신 | 0 | received 0, 최근 수신 시각 없음, inbox 파일 없음 |
| 예약 Import | 0 | scheduled import total 0; 이전 수동 Codex Import는 자동 수신 실적 아님 |
| machine passed / held / failed | 1 / 27 / 13 | machine pass는 사람·출처·권리 검증 완료와 다름 |
| `auto_eligible` | 0 | 통과 원고 없음 |
| 실 Blogger Publishing Job | queued 0, due 0 | live lane 비어 있음 |
| Mock job | 1 held | 과거 `quality_held`; 신규 mock 처리 성공으로 세지 않음 |
| Publication Worker | stopped/stale | mock/live 처리 결과 없음 |
| Blogger 실제 공개 게시 | 0 | 실제 postId/URL 없음 |
| 현재 운영 정책 | manual, Auto OFF | 일일 설정 1건, 최소 간격 1440분, `operations_auto_approved=false` |

### 첫 0건의 원인

최근 24시간의 494개 이슈 그룹이 후보 평가에서 모두 `held`다. `topics.py::_assess_topic`는 현재 승인·유효한 출처 두 건, source-span 검증 사실 세 건, 독립성 검토 두 그룹, 최소 점수 70, 중복 그룹 검토 완료 등을 요구한다. reader value와 analysis fit은 별도 사람 검토 상태로 남는다. 따라서 검색어 관측만으로 기사 후보로 승격되지 않는다. 조사 shortlist 4건은 선택됐지만 공식 조사 실행은 기록되지 않았다. 이 차단을 사실·권리 검증 우회로 해결하지 않았다.

## 공식 예약 작업 경로 확인

2026-10-29 기준 공식 문서에는 ChatGPT 데스크톱 예약 작업이 로컬 프로젝트 폴더에서 실행될 수 있다고 명시되어 있다. 이 경로에는 로컬 PC가 켜져 있고 ChatGPT 데스크톱 앱이 실행되어 있어야 한다. 웹 예약 작업은 PC 폴더에 직접 접근하지 못하며, Codex CLI 자체에는 예약 작업 관리 화면이 없다. 따라서 이전의 “공식 기능에 로컬 파일 경로가 없다”는 일반화는 현재 문서와 맞지 않는다.

그러나 이 세션에서는 `woori-blog-agent` 폴더를 대상으로 한 예약 작업 생성·실행 및 `ready/` 파일 저장을 검증하지 못했다. 운영 DB의 검증된 GPT run 0, 예약 원고 자동 전달 0으로 기록한다. 공식 지원 사실과 이 사용자 계정에서의 실제 사용 가능·실행 성공은 구분한다. 예약 작업을 만들거나 폴더 권한을 부여하지 않았고, 사용량/비용 조건을 계정에서 확인하지 않았다.

- [공식 ChatGPT Work 및 Codex 안내](https://help.openai.com/en/articles/20001275-chatgpt-work-and-codex): Work 데스크톱은 권한 허용 시 로컬 파일을 사용할 수 있고, Work 웹/모바일은 직접 로컬 파일에 접근하지 못함.
- [공식 예약 작업 안내](https://learn.chatgpt.com/docs/automations?surface=app): 데스크톱 예약 작업은 로컬 프로젝트에서 동작할 수 있으며 PC와 앱이 실행 중이어야 함. 웹 예약은 로컬 폴더/작업 트리를 유지하지 않음.
- [공식 ChatGPT 예약 작업 안내](https://help.openai.com/en/articles/10291617-scheduled-tasks-in-chatgpt): 예약 가능 여부와 실행 제한은 계정·플랜·워크스페이스 설정에 따름.

## Blogger 및 운영 정책

- 운영 API 설정은 `manual`, 일일 1, 최소 간격 1440분, `operations_auto_approved=false`다.
- Publisher status에서 `auto_policy_active=false`, `live_publication_dispatch_enabled=false`, `public_publication_enabled=false`, `real_writes_enabled=false`다.
- 게시 가능한 원고 0, live queue 0, 공개 게시 0, postId/URL 0.
- Auto 정책과 실제 쓰기 경로를 활성화하지 않았다. 공개 쓰기 요청을 하지 않았다.
- 사용자가 이번 작업에서 요청한 별도 최초 운영 전환 승인은 주어지지 않았으며, AGENTS.md의 별도 Blogger 쓰기 승인·Auto 차단 규칙도 유지했다.

## 결과 판정

**PARTIAL / BLOCKED — 실제 무인 공개 게시 미완료.** Trends 수집 데이터는 있으나 후보 0건이 첫 병목이다. 공식 GPT 데스크톱 예약 작업은 문서상 로컬 폴더를 지원하지만, 이 계정·프로젝트의 실제 예약 실행과 파일 전달은 미검증이다. 생산용 생성 Provider는 연결되지 않았고, 예약 Import·auto eligibility·live queue·실제 발행은 모두 0건이다. 현재 Worker는 stale이며, Blogger live write 및 Auto 정책은 비활성이다.

### 사용자/운영자가 해야 하는 다음 단계

1. ChatGPT 데스크톱에서 Work/Codex 예약 작업을 만들 때 로컬 프로젝트 접근을 허용하고, PC와 앱을 예약 실행 시 계속 켜 둔다. 출력은 우선 기존 `.local/gpt-scheduled-import/incoming/`에 원자적으로 저장하도록 제한한다. 실제 실행 로그와 파일 hash가 확인될 때까지 예약 자동 생성 성공으로 보지 않는다.
2. 현재 자동 조사 shortlist에는 검증된 공식 근거가 없으므로 먼저 기존 허용된 출처 조사 경로에서 출처 원문·근거·권리 검토를 완료해야 한다. Research Package 상태만으로 작성/게시 승인하지 않는다.
3. Worker를 재개할 때 `scripts/status.ps1`로 PID와 heartbeat를 다시 확인하고, 실행 중인 프로세스가 없을 때만 기존 공식 start 절차를 사용한다. 이번 작업에서는 시작하지 않았다.
4. 실제 공개 게시에는 별도 최초 운영 범위 승인과 적용 정책 활성화가 필요하다. Auto OFF 상태는 유지한다.

## 변경·검증·Git

- 수정 파일: `docs/development/P5-CODEX-035.md` (진단 기록만; 운영 코드 변경 없음)
- 테스트: 코드 변경이 없어 테스트/lint/typecheck를 실행하지 않음. 실행한 검증은 API health, worker `--status`, PowerShell `status.ps1`, read-only 운영 DB snapshot, 폴더 파일 목록, 프로세스 목록뿐.
- 기존 운영 콘텐츠·OAuth·감사 로그 보존. Blogger API 쓰기 호출 0회.
- 커밋 해시: 후속 git log에 연결.
- 남은 문제: 후보 0건, Research Worker와 Publication Worker stale, GPT 예약 task 미설정/미검증, 생성 Provider 미연결, `auto_eligible` 0, Auto/live Blogger write OFF, 공개 게시 0.
