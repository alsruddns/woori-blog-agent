# P5-CODEX-032 — 무인 원고·게시 자동화 운영 준비 점검

- 작업 일시: 2026-10-29 (Asia/Seoul)
- 작업 ID: P5-CODEX-032
- 브랜치: `develop`
- 변경 사유: 원고 무인 전달, 수신·검증, Blogger 자동 발행의 실제 운영 연결 상태를 입증하고 정책 차단을 분리한다.
- 기존 상태: P5-024의 로컬 inbox polling과 P5-025의 승인된 live queue는 구현돼 있으나 GPT 예약 실행 파일 전달과 Blogger 공개 게시 실적은 확인되지 않았다.
- 변경 목적: 현 운영 상태를 재검증하고, 현재 영구 정책을 바꾸지 않는 비활성 Auto 정책 초안을 제공한다.

## 현재 상태와 근거

| 단계 | 상태 | 실제 확인 |
|---|---|---|
| Dashboard/API | READY (기존 실행 상태) | 3100 Dashboard 및 8100 API health 정상. 기존 서비스는 재시작하지 않음. |
| Research Worker | PARTIAL | PID 13436 heartbeat `running`, fresh; PID 15720은 같은 worker의 부모 런처. 둘을 중복 Worker로 오인해 종료하지 않음. |
| Trends | PARTIAL (실제 수집 정상) | Dashboard의 운영 API에서 보이는 collection run 46건과 observation 300건을 확인. 최근 각 지역별 마지막 RSS 실행은 11/11 모두 HTTP 200, 각 10건이며 마지막 관측 시각은 13:01~13:52 KST. 이번 작업에서 Trends API를 호출하지 않았으며, 기사 후보·Research Package 자동화는 별도 단계. |
| Research Package | PARTIAL | 저장 패키지 1건. 이는 무인 생성 파이프라인의 이번 실행 성공으로 계산하지 않음. |
| GPT 예약 원고 | BLOCKED / 미검증 | 공식 문서상 ChatGPT 데스크톱 예약 작업은 권한이 허용된 local project의 파일을 다룰 수 있음. 하지만 현재 계정/워크스페이스 기능 사용 가능 여부 및 예약 실행은 확인하지 못함. 운영 `dispatches=0`, 실제 GPT 생성 증거 0건. |
| 로컬 JSON 수신 | PARTIAL (코드·격리 테스트) | `.local/gpt-scheduled-import` 상태 폴더들은 존재하며 현재 파일 0개. Worker는 `*.ready.json`만 원자적으로 선점하도록 구현돼 있음. |
| 자동 Import | PARTIAL (격리 테스트) | `tests/test_scheduled_import_inbox.py` 포함 수신·게시 테스트 30 passed. 이번 작업에서 실제 운영 파일을 Import하지 않음. |
| 품질/SEO/HTML | PARTIAL | 기존 machine assessment와 editorial review gates가 분리돼 있음. 현재 적격 승인 원고를 확인하지 못함. |
| 발행 큐 | BLOCKED | 운영 mode `manual`, mock job 1건은 `blocked/quality_held`; live publication record 0건. |
| Publisher Worker | NOT RUNNING | publication Worker heartbeat 없음. 실제 Blogger 쓰기·초안·공개 URL 0건. |
| Auto/정책 | BLOCKED / OFF | 현재 DB mode `manual`, 일 한도 1, 최소 간격 1,440분, `operations_auto_approved=false`, `live_auto_enabled=false`, 긴급 정지 false. 코드의 정책 초안값과 다르며 변경하지 않음. |

OAuth A/B 연결, 게시 설정, 운영 DB, 원고, 감사 기록은 수정하지 않았다. 이번 작업에서 Blogger API GET/POST 및 Trends 외부 호출은 하지 않았다. Blogger quota/billing 및 ChatGPT 계정별 추가 credit 조건은 이 실행 환경에서 확인 불가다.

## ChatGPT 예약 기능 조사

2026-10-29에 확인한 OpenAI 공식 문서에 따르면 ChatGPT 데스크톱 앱에서 예약 작업은 local project 디렉터리 또는 격리 worktree에서 실행할 수 있고, local 파일이 필요한 경우 PC와 앱을 켜 두어야 한다. Web-only 작업은 PC의 폴더에 직접 접근하지 않는다. Local project와 Work Cloud, Codex Local은 서로 다른 권한/실행 경로다. Work/Codex 사용은 계정 사용량 정책을 따르며 추가 credits가 적용될 수 있으므로 계정의 실제 잔여 사용량/추가 비용 상태를 이 저장소에서 확인할 수 없다.

실제 ChatGPT 화면을 조작하지 않았고, 기존 예약 작업을 열람·수정·삭제하거나 새 예약을 만들지 않았다. 따라서 공식 문서의 지원 가능성은 확인했지만 사용자 계정의 권한, 실제 예약 등록 수, 실제 예약 실행 수, local 파일 쓰기, 사람 개입 없는 전달은 **미검증**이다. Cloud/worktree에서 생성한 파일은 이 checkout의 inbox로 자동 전달된 것으로 취급할 수 없다.

운영자가 실제 연결을 시험할 때는 ChatGPT 데스크톱에서 새 Work 예약을 만들고, `C:\Users\achie\git\woori-blog-agent`를 local project로 선택해야 한다. 저장 경로는 `.local/gpt-scheduled-import/incoming`에 `.part`로 쓴 뒤 완전한 JSON 검증 후 동일 볼륨의 `ready/*.ready.json`으로 원자적 rename 한다. 기존 `docs/operations/P5-CODEX-024-gpt-work-prompts.md`의 task별 지시문을 재사용한다. 첫 예약 실행 결과와 실제 파일 hash, 수신 audit, Import ID가 일치하기 전까지 자동 전달 건수는 0이다.

## 운영 정책 차이 및 안전 차단

설계 목표(사용자 지정)는 KST 전역 50/일, ko 10/일, ja 10/일, zh-CN 5/일, en 잔여 우선·20/시간, blog 5분·계정 2분이다. 실제 운영 DB는 global `manual`, daily 1, minimum interval 1,440분, operations auto approval false다. 이번 작업은 두 정책을 조정하지 않았다.

현재 AGENTS 정책은 사람의 편집/권리 검토와 별도 공개 쓰기 승인을 요구한다. 이를 대체하는 비활성 검토 초안을 `docs/operations/P5-CODEX-032-auto-publication-policy-draft.md`에 추가했다. 정책 승인 전 어떤 머신 검사도 사람 승인, `publish_ready`, Auto 설정을 대신할 수 없다.

## 검증

- `pytest -q tests/test_scheduled_import_inbox.py tests/test_publications.py`: **30 passed**, `.env.test` 격리 DB, 외부 Blogger 쓰기 없음.
- 실제 브라우저/ChatGPT 예약 작업: 미검증.
- 실제 운영 DB 직접 연결: 이번 진단 프로세스에는 DB 인증 정보가 제공되지 않아 시도한 read-only 진단은 실패. Dashboard의 동일 출처 관리자 읽기 API를 사용해 현재 상태를 확인했고, DB를 직접 수정하지 않음.
- PostgreSQL agent-run 감사 이벤트: 이번 실행의 시작/완료 이벤트는 추가하지 못함. 현재 관리자 읽기 프록시에는 일반 실행 감사 기록 경로가 없고 이 셸에는 운영 DB 접속 자격이 없어, 임의의 콘텐츠/설정 이벤트를 빌려 기록하지 않음. 운영 감사 기록 자동화를 위한 지원 경로가 남은 운영 요구사항임.
- Dashboard 모바일/UI 변경: 없음.
- 코드 변경·마이그레이션: 없음. 정책 상태를 바꾸지 않음.
- Auto 활성화, Publishing Worker 실행, Blogger API 쓰기: 없음.

## 수정 파일

- `docs/development/P5-CODEX-032.md`
- `docs/operations/P5-CODEX-032-auto-publication-policy-draft.md`

## 남은 필수 작업

1. 운영자가 ChatGPT Work/Codex의 로컬 프로젝트 권한과 추가 credits 상태를 확인하고, 별도 예약 작업을 직접 설정한다. 첫 실제 실행에서 local JSON 자동 전달과 Import를 확인한다.
2. 기존 Research Package/원고의 사실 의미, 이용권리, 최신성 및 편집을 사람 검토한다.
3. 현 AGENTS 사람 검토 요건을 유지할지, 제한된 콘텐츠 유형에 대한 대체 무인 승인 정책을 허용할지 프로젝트 소유자가 별도 승인해야 한다.
4. Blogger Cloud Billing/quota 확인, 정확한 공개 쓰기 운영 승인 및 exact-version publication approval이 필요하다.
5. Publishing Worker 부재를 운영자가 원래 터미널에서 해결하고, 승인 범위 내 안전 검증 후에만 live queue를 실행한다.
6. 현재 스케줄 정책 `manual/1/1440`은 그대로다. 정책 변경은 승인 후에만 append-only 감사 이벤트와 함께 적용한다.

작업 결과 판정: **PARTIAL / BLOCKED**. 구현·격리 검증된 수신 구성은 있으나 GPT 실제 예약 전달과 실 Blogger 자동 게시, 반복 무인 실행은 입증되지 않았다.

커밋 SHA: 후속 `git log`로 연결. `origin/develop` push 결과: 후속 기록.
