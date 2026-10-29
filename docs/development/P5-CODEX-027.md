# P5-CODEX-027 — 운영 안정화 및 Auto 전환 준비

- 작업 시각: 2026-10-29 (KST)
- 브랜치: `develop`
- 변경 사유: 운영 중인 로컬 프로세스가 기본 포트 밖에서 실행되어도 중복 실행을 막고, 자동화 준비 상태·작업자 상태·중요 경고를 Dashboard에서 확인할 수 있게 한다.
- 기존 문제: 시작 스크립트는 기본 포트만 확인했고 Worker 프로세스의 단일 실행을 DB 수준에서 보장하지 않았다. Dashboard는 Auto 전환을 위한 단계별 준비 판정과 복구·백업 경고를 한곳에 보여주지 않았다.
- 변경 목적: 사용자 프로세스를 임의 종료하지 않고 오래된/다른 포트 프로세스를 찾으며, readiness를 실제 운영 상태와 구분해 보고한다. 외부 쓰기·Auto 활성화는 계속 차단한다.

## 상태 변화

- 변경 전: 상태 스크립트는 기록된 기본 포트 리스너 중심으로 표시했다. 직접 Worker 중복 시작 차단은 프로세스 내부·DB 수준에 없었다. Dashboard는 관측 모드 권고 상태를 상세 표시하지 않았다.
- 변경 후: 서비스 스크립트가 이 checkout의 프로세스와 실제 listen 포트를 보여주며, API/Dashboard/Worker 중복 실행 시 새 프로세스를 시작하지 않는다. Research/Evaluation Worker는 PostgreSQL session advisory lock으로 단일 실행을 보장한다. 운영 Dashboard에 준비 상태, 모드 A–D, worker PID/heartbeat, 경고, 코드 안전 상한을 설정된 Auto 정책과 분리해 표시한다.
- 외부 게시: 이 작업에서 Blogger API 쓰기 요청 0건, 초안 0건, 공개 게시 0건. Auto OFF, mode `manual`, 긴급 정지 OFF, 사용자 승인 상태를 바꾸지 않았다.

## 변경 파일

- `scripts/server-common.ps1`
- `scripts/start.ps1`
- `scripts/status.ps1`
- `scripts/run-worker.ps1`
- `services/api/woori/worker.py`
- `services/api/woori/operations_dashboard.py`
- `services/api/tests/test_worker_runtime.py`
- `services/api/tests/test_publications.py`
- `services/api/tests/test_dashboard_read_models.py`
- `apps/dashboard/app/page.tsx`
- `apps/dashboard/app/style.css`
- `docs/operations/runbook.md`

## 실제 운영 확인

- DB 스키마 변경 없음. 운영 DB의 콘텐츠, 원고 버전, 감사 이력, OAuth 연결은 수정/삭제하지 않았다.
- 운영 DB snapshot: readiness `READY FOR OBSERVATION ONLY`; research worker heartbeat PID `46704`, 2026-10-29 12:43 KST 시점 `running`; publication worker `not_started`.
- 운영 정책: `manual`; live Auto와 live writes 비활성. Dashboard가 표시한 내부 코드 캡은 전역 일 50, 시간당 ko/ja/zh-CN 10, en 20이며, 영어는 전체 잔여량 우선 정책을 유지한다. 실제 운영 Auto 설정은 별도이며 일 1건/최소 간격 1440분으로 조회되었다. 코드 상한을 활성화 증거로 해석하지 않는다.
- 운영 상태 경고: 백업 archive 검증 성공, 백업 나이 약 9.7시간, 디스크 여유 19.9%로 20% 경고 기준 아래. 외부 알림 채널 미설정. GPT 무인 실행 미검증, 발행 후보 0, 원격 Blogger 게시 GET 재검증은 테스트되지 않았다.
- 현재 사용자 소유 서비스는 종료하지 않았다. Dashboard PID 35616 (port 13100), API PIDs 36796/47060 (port 18100), Worker PIDs 37512/46704를 관측했다. 기본 3100/8100은 listen하지 않았다. 기존 Dashboard는 API를 기본 8100으로 요청해 API unavailable 화면을 제공했다. 현재 실행 중인 구버전 Worker는 새 advisory lock 코드를 아직 적용하지 않았다.
- Task Scheduler에서 기존 프로젝트 작업 이름을 확인하지 못했다. 이 작업은 작업을 등록하거나 시작하지 않았다. Windows 로그아웃·절전·PC 종료 중 로컬 자동 실행이 지속된다는 보장은 없다.
- Dashboard 모바일 치수(320/390/768/1280px) 확인은 이전 실행에서 overflow 0/console error 0이었으나 구 API 응답 화면이었다. 새 readiness payload는 현재 사용자 서버가 구버전이라 브라우저에서 확인되지 않았다.

## 검증

- 격리 DB 범위 테스트: `test_worker_runtime.py`, `test_publications.py`, `test_dashboard_read_models.py`, `test_publication_daily.py` — **29 passed**. 포함: worker advisory lock 격리, emergency stop 검사, 감사 이벤트, readiness/일일 한도 read model.
- Ruff: 이번 변경 Python 파일 검사 통과. 별도로 전체 명령에 포함한 기존 `test_publication_daily.py`는 import 정렬(I001) 1건을 보고했으며 해당 무관 파일은 수정하지 않았다.
- Dashboard lint, typecheck, production build: 변경 UI에서 이전 실행 기준 통과.
- 운영 스크립트 중복 실행 guard: `start.ps1 -Service api`와 `run-worker.ps1`는 각각 현재 프로젝트 PID를 발견하고 안전하게 거부했다. 기존 프로세스는 그대로 유지.
- 실제 Trends/RSS 요청, GPT 예약 실행, Blogger API 쓰기·GET, 게시, Auto 전환은 수행하지 않았다.

## 운영자 조치 및 남은 문제

새 코드 적용이 필요하면 현재 각 서비스의 원래 VS Code/PowerShell 터미널에서 API·Dashboard·Worker를 각각 `Ctrl+C`로 정상 종료하고 `scripts/status.ps1`에서 종료와 포트 해제를 확인한 뒤, 한 인스턴스만 `scripts/start.ps1 -Service api`, `scripts/start.ps1 -Service dashboard`, `scripts/run-worker.ps1`로 다시 시작한다. 터미널을 특정하지 못하면 PID를 강제 종료하지 말고 사용자가 해당 터미널에서 처리해야 한다. 기존 Dashboard/API 포트 불일치(13100/18100 대 3100/8100)와 사용자 환경 설정을 확인한 뒤 같은 origin 설정으로 시작해야 한다.

출처·권리·사람 검토, GPT 예약의 공식 로컬 전달, 실제 Blogger 읽기/쓰기 검증, 발행 승인, 원격 게시 재검증, 외부 알림, off-device 암호화 백업/키 복구 리허설은 미완료다. 따라서 판정은 **READY FOR OBSERVATION ONLY**이며 Draft/Controlled Publish/Auto가 아니다.

커밋 해시는 작성 시점 미정이며 후속 `git log`로 확인한다. 원격 push 결과도 커밋 이후 기록한다.
