# P5-CODEX-026 — 무인 자동화 종단 간 검증 및 장애 복구

- 작업 일시: 2026-10-29 (Asia/Seoul)
- 작업 브랜치: `develop`
- 작업 ID: P5-CODEX-026
- 변경 사유: 기존 운영 스케줄러는 6개 지역만 허용했고, 직접 수집 API 호출은 스케줄러의 요청 간격을 우회할 수 있었다.
- 변경 목적: 공식 Google Trends RSS 허용 지역을 11개로 확장하고, 어떤 호출 경로에서도 DB 기반 전역 간격과 시간당 한도를 지킨다.
- 변경 전 상태: 운영 DB schema 49, 24시간 Trends 실행 28회·관측 280건(6개 지역), 자동 GPT 수신 0건, Research Package 1건(사람 검토 대기), Blogger 게시 0건, Auto OFF.
- 변경 후 상태: migration 050 적용, 11개 지역이 설정·API·외부 호출 allowlist에 반영됨. 최근 24시간 11개 지역 모두 실제 수집, 33회/330관측. 실행 중인 구버전 Worker/API는 운영자가 띄운 프로세스일 수 있어 종료하지 않았다. 새 코드에서 직접 수집 간격도 DB advisory lock 안에서 검사한다.

## 현재 운영 증거

| 단계 | 실제 상태 | 증거 및 제한 |
| --- | --- | --- |
| Research Worker | 실제 heartbeat 갱신 중 | PID 46704 (부모 37512), 마지막 확인 시 PID/명령은 이 체크아웃의 `.venv`와 `python -m woori.worker`; 구버전 프로세스이므로 새 11개 지역 코드는 적용되지 않음. 프로세스 종료/재시작은 하지 않음. |
| API / Dashboard | 로컬 HTTP 200 | API `127.0.0.1:18100`, Dashboard `127.0.0.1:13100`; 프로젝트 프로세스이지만 기존 터미널을 보존. 지정 기본 포트 8100/3100에는 리스너 없음. |
| Trends | 실제 자동 실행 성공 (수집 경로) | 24시간 33회/330 관측, 11개 지역 전부 성공. 신규 AU/CA/GB/IN/PH RSS 요청 각 1회 HTTP 200·항목 10건. 신규 5개 지역 실패·429 없음. RSS 항목/트래픽 구간은 절대 검색량 순위가 아니며 기사 사실의 근거로 쓰지 않음. |
| 후보·조사 | 기사 후보 0 | 기존 운영 Dashboard read-model은 이슈 그룹을 검토/근거 부족 상태로 표시하고, 공식 조사 자동 실행은 비활성이라고 보고함. 기존 Research Package 1건은 `evidence_collected_pending_human_review`, 독립 출처 0건. |
| GPT 예약 파일 수신 | 0건 | 수신 0, 검증된 GPT 예약 실행 0, 마지막 파일 수신 없음. 기존 수동 Codex Import를 무인 실행 실적으로 계산하지 않음. |
| 기존 원고 Import | 수동 Codex 1건 | 운영 DB `generation_method=manual_codex_import`, 상태 `awaiting_human_review`; 품질 평가는 기계 통과 2건/보류 3건(버전/평가 이력 행 기준), 독립 출처 검증 0, `publish_ready=false`. |
| Publisher | 실제 공개 게시 0건 | `publishing_records` 0건, Auto OFF, 실제 쓰기 비활성. 테스트는 Mock/격리 DB만 허용. Blogger GET/POST 호출은 이 작업에서 실행하지 않음. |

실행 중인 PID를 식별했지만 소유 터미널을 특정하거나 안전한 종료를 요청할 수 없어 현재 코드를 재적용하기 위한 강제 종료를 하지 않았다. 사용자가 직접 재시작할 때는 각 기존 터미널에서 Ctrl+C로 정상 종료한 뒤, 프로젝트 루트에서 Worker는 `scripts/run-worker.ps1`, API는 `.venv\\Scripts\\python.exe -m uvicorn woori.main:app --app-dir services/api --host 127.0.0.1 --port 18100 --no-access-log`로 시작해야 한다. Dashboard Next dev는 기존 터미널에서 정상 재시작하거나 코드 reload를 확인한다. 이 문서는 실제 재시작이 수행됐다고 주장하지 않는다.

## 변경 파일

- `services/api/woori/trends.py`: 11개 geo allowlist와 5분 간격, direct collect의 DB 기반 최소 간격 차단 및 감사 이벤트.
- `services/api/woori/research_routes.py`: 하드코딩된 6개 geo literal을 중앙 allowlist 검증으로 변경.
- `services/api/woori/external_policy.py`: outbound RSS allowlist에 GB/CA/AU/IN/PH 추가.
- `scripts/050_trends_eleven_geographies.sql`: 기존 관측을 보존하고 4개 geo 제약만 확장하는 schema 50 migration.
- `scripts/migrate.py`, `scripts/provision-test-database.py`: 순차 schema 50 지원.
- `services/api/tests/test_trends.py`: 11개 지역 주기, 신규 geo 수집 모양, 직접 호출의 전역 간격 차단 검증.
- `docs/operations/research-sources.md`, `docs/operations/zero-cost-policy.md`: 지역·주기·한도 문서화.

## 검증

- 격리 테스트 DB: `scripts/provision-test-database.py`로 전용 테스트 DB/권한 확인; 운영 DB 쓰기는 거부됨.
- 운영 migration: `scripts/migrate.py`가 schema 050까지 검증/적용.
- Ruff: 변경 Python 파일 통과.
- 변경 범위 테스트: Trends, trend topics, content imports, scheduled import inbox, publication daily/jobs, Blogger live policy, Dashboard read model — **93 passed**.
- API/Dashboard local health: 각각 HTTP 200. 모바일 브라우저 확인: Playwright 320/390/768/1280px에서 가로 넘침 없음, console error 0.
- Mock/격리 테스트는 실제 GPT 예약 수신이나 Blogger 실제 게시를 증명하지 않음.

## 감사·안전 상태

P5-CODEX-026 실행 시작 이력은 `job_runs`/`audit_events`에 기록되었다. migration 050은 append-only audit 이벤트를 남겼다. 이 작업은 원고, OAuth 토큰, Blogger 기존 글을 수정·삭제하지 않았다. 유료 서비스 호출은 없고, `external_policy` 사전 검사에서 billable credential 이름이 검출되지 않았다. Auto 및 실 Blogger 쓰기는 계속 OFF/차단 상태다.

## 남은 문제

- 기존 Research Worker/API/Dashboard 코드는 구버전일 수 있으며 이 작업에서 프로세스를 재시작하지 않았다.
- 11개 geo 전부의 RSS 실응답은 요청 간격 5분 및 rolling-hour 12회 상한 안에서 추가 확인해야 한다. provider HTTP 429가 발생하면 즉시 중단한다.
- 공식 예약 실행에서 로컬 파일이 자동 전달되는지 미검증; 현재 GPT 실행 및 자동 전달 건수 0.
- 원고 생성 Provider 미연결, Research Package와 근거 검토가 pending이므로 게시 적격 원고 0.
- 실제 Blogger GET/POST, 공개 게시, Auto 운영 검증은 승인·런타임 코드 적용 전까지 수행하지 않음.

## 커밋

완료 commit SHA와 원격 푸시 결과는 완료 후 이 섹션과 `git log`에 기록한다.
