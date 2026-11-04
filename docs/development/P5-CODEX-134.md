# P5-CODEX-134 — Publication Worker 운영 발행 설정 정상화

- 작업 일시: 2026-11-04 (Asia/Seoul)
- 브랜치: `develop`
- 시작 HEAD: `07c7bd4133e190e3f963ffb3b684ad78d4468a2a`
- 원격 시작 HEAD: `07c7bd4133e190e3f963ffb3b684ad78d4468a2a`
- 작업 ID: `P5-CODEX-134`
- 작업 시작 감사: PostgreSQL `agent.work.started` 이벤트 기록
- 관련 기록: P5-CODEX-128~133, 특히 P5-CODEX-133 운영 후속 상태

## 기존 상태와 원인

운영 DB schema는 89였다. 전역 `automation_controls`에는 이미 `global_publish_min_interval_minutes=15`, `global_daily_live_publish_limit=100`이 저장돼 있었고 해당 row revision은 22였다. 다만 Publication Worker 상태 화면에서 보여주는 `publication_mode_settings` 글로벌 row는 `configured_mode=manual`, `daily_auto_limit=1`, `minimum_interval_minutes=1440`이었다. 예약 발행은 append-only `scheduled_publication_policy_events`의 마지막 enabled event를 별도로 읽었으며, 그 이벤트는 일일 한도 1건 및 Blogger record 4개만 승인했다.

따라서 1440/1/4는 서로 다른 운영 정책 계층의 구버전 제한에서 왔다. API 입력 검증과 PostgreSQL CHECK도 mode 한도 0~3, 간격 60분 이상, 예약 일일 한도 1~3, 승인 Blogger 최대 4개로 고정돼 있어 관리 API로 목표값을 저장할 수 없었다. 전역 제어 테이블은 이미 15/100이므로 이를 불필요하게 덮어쓰지 않는다.

작업 전 Worker 상태는 heartbeat fresh, `live_queued=0`, `live_due=0`, 예약/수동 queued·due 0이었다. 현재 `publication_mode_settings.configured_mode=manual`, emergency stop OFF, `operations_auto_approved=false`였다. 별도 `automation_controls`의 `auto_mode=publish`, auto flags 및 operator approval은 기존값을 확인했고 이번 작업에서 수정하지 않았다. Worker 상태의 `AutoPolicyActive=false` 역시 임의로 활성화하지 않는다.

## 활성 Blogger 매핑

모두 기존 DB 매핑에서 확인했으며, 아래 UUID는 Blogger record ID이고 Blog ID는 Blogger API ID다.

| 언어 | URL | Blogger Blog ID | Blogger record ID |
|---|---|---:|---|
| EN | `trend-journal-en.blogspot.com` | `5240203250707821039` | `b9dc1202-8071-484a-a4f4-15d04e34a76c` |
| KO | `trend-ko.blogspot.com` | `3321654108096579717` | `9c4c3e67-6a0c-4213-a5f6-79e6e8841eb6` |
| JA | `trend-ja.blogspot.com` | `7562596540375659150` | `769d3996-335c-4037-9216-a62f058f8638` |
| DE | `trend-journal-de.blogspot.com` | `5857406989226346280` | `ab0feab6-1afa-4f00-b3c2-498179f72e7c` |
| BR | `trend-journal-br.blogspot.com` | `2780805325207451782` | `e7626329-fc21-4420-b3c6-bd023ba3f3ad` |
| VI | `trend-journal-vn.blogspot.com` | `2392412558893856604` | `309f350b-fd4c-456c-ac1e-19f18dd6335d` |

`zh-CN` record은 DB에서 inactive로 확인했으며 새 승인 범위에 포함하지 않는다. OAuth 연결 데이터는 읽기만 했고 수정하지 않았다.

## 변경 내용

- Additive migration 090: publication mode CHECK 범위를 일일 0~100건 및 최소 15분으로 넓히고 기본값을 100/15로 설정. 예약 승인 이벤트의 Blogger 최대 범위를 6개, 일일 한도를 100으로 넓혔다. 과거 승인 이벤트 및 기존 값은 변경하지 않는다.
- `ModeSettingsInput`과 scheduled policy API 검증을 같은 범위로 확장했다. 예약 연결검증 요청도 6개 Blogger를 받는다.
- Worker status/Dashboard fallback 표시와 운영 설정 입력 기본값을 100건/15분으로 정렬했다. 예약 정책 요청의 한도값도 100으로 전달하고, 화면에 남은 “하루 1건/4개 블로그/첫 게시 개별 승인 필요” 문구를 현재 정책과 맞게 고쳤다.
- DE, pt-BR, VI는 기존 시간당 언어 제한이 미등록이라 Publisher에서 기본값 0으로 차단되고 있었다. 글로벌 15분 간격을 넘지 않도록 세 언어에 각각 시간당 4건의 내부 상한을 등록했다. EN/KO/JA의 기존 언어 상한 및 KO/JA 일일 상한은 유지했다.
- 운영 설정 데이터는 migration 안에서 직접 UPDATE하지 않았다. migration은 CHECK/기본값만 바꾸며, 실제 mode row 및 예약 승인 scope 변경은 배포된 인증 관리 API로 수행한다.
- 자동 모드, 자동 승인, 긴급 정지, global `automation_controls` row, 우선순위, Trends 설정, OAuth 연결, 원고·Job·게시 이력을 이번 수정 범위에서 변경하지 않는다.

## 백업 및 DB 변경

- 백업 대상은 `.env.migration`으로 확인한 `localhost:5432/woori_blog_agent`였다.
- `scripts/backup.py` 실행 성공. `pg_restore --list` 아카이브 검증 완료.
- 백업: `backups/20261104T091318Z.dump` (52,406,781 bytes)
- SHA-256: `4DA2F87067BA9C28F3579A7D1D58915EA5FF34F8BACF015B3F4E1884FCF9BDB5`
- 변경 전 schema 89, migration 090 적용 후 schema 90 확인.

## 운영 반영 및 검증

### 설정 반영

- `publication_mode_settings` 글로벌 row: 이전 manual / 1건 / 1440분 → 이후 manual / 100건 / 15분. emergency stop OFF 및 `operations_auto_approved=false` 유지. `updated_at=2026-11-04 18:25:16.771478 KST`. Mode row에는 별도 revision 열이 없다.
- `automation_controls`: revision 22, global interval 15, KST global LIVE cap 100. 이 값은 작업 전부터 같았으므로 이번 작업에서 수정하지 않았다.
- Scheduled Auto event: 이전 event 3, enabled / scope 4 / 1건 → 새 append-only event 4, enabled / scope 6 / 100건, `created_at=2026-11-04 18:29:00.626855 KST`. 과거 event 1~3은 그대로 보존했다.
- 마지막 event의 6개 scope는 EN, KO, JA, DE, pt-BR, VI다. 각 DB Blog ID는 위 매핑과 일치한다. 중국어 record는 inactive이며 scope에 없다.
- 실제 운영 API의 읽기 전용 연결 검증으로 6개 모두 HTTP 200, 등록 Blog ID와 원격 Blog ID 일치, `blogger_write_performed=false`를 확인했다. 첫 확인 요청은 BR record UUID 입력 오타로 DB 단계에서 404 거절됐으며 이 요청에서는 외부 API를 호출하지 않았다. DB에서 재확인한 정확한 `fc21` UUID로 다시 실행해 여섯 연결이 모두 검증됐다.
- `AutoMode`: Publication Worker status의 `configured_mode=manual`, `AutoPolicyActive=false` 유지. 별도 `automation_controls.auto_mode=publish`, auto switches/operator approval은 원래 값과 revision22를 유지했다. 자동 모드/승인 상태는 이번 작업에서 변경하지 않았다.
- Worker runtime status: `MinimumIntervalMinutes=15`, `DailyLiveCapKST=100` (공유 controls 및 global mode), `ScheduledDailyLimit=100`, `AllowedBloggerCount=6`. `LiveQueued=0`, `LiveDue=0`.
- 우선순위는 기존 Worker query대로 scheduled → manual → Trends 유지했다. 기존 KO/JA 언어별 일일 cap 등 추가 제한은 그대로 두었고, 신규 DE/pt-BR/VI 시간 제한은 글로벌 간격에 맞춘 4건/시간으로 설정했다.

### 서비스 및 테스트

- 적용 스크립트: `scripts/apply-verified-changes.ps1 -Apply -Confirm:$false`. 첫 검증 시 공용 pytest temp 경로 정리에서 WinError 5가 발생했지만 테스트 완료 및 서비스 종료 전 단계에서 멈췄다. 저장소 전용 basetemp를 지정해 재실행했다.
- 재실행 집중 테스트 84건 통과. Ruff 전체 API, 변경 모듈 mypy, API lint, dashboard lint/typecheck/production build, isolated wheel build 통과. 공용 pytest cache 권한 경고 1건은 남았지만 전용 basetemp에서 pytest 자체는 84건 모두 통과했다.
- graceful 종료 후 재기동. 강제 종료 없음. API PID 35452, HTTP 200; Dashboard PID 26296, HTTP 200; Publication Worker PID 2196, heartbeat fresh; Research Worker PID 33368, heartbeat fresh. API, Dashboard, 두 Worker의 applied revision은 `11853f175f46016e1f449f6c253fb0485155b16b`.
- Blogger write POST/PATCH/DELETE: 0건. 운영 연결 확인용 Blogger GET: 6회, 모두 200. Blogger 게시 Job이나 게시 이력은 만들거나 수정하지 않았다.

## 변경 파일

- `scripts/090_publication_worker_operational_limits.sql`
- `scripts/migrate.py`
- `services/api/woori/publication_modes.py`
- `services/api/woori/publication_daily.py`
- `services/api/woori/publications.py`
- `services/api/woori/operations_dashboard.py`
- `services/api/tests/test_publications.py`
- `apps/dashboard/app/publishing/publication-manager.tsx`
- `docs/development/P5-CODEX-134.md`

## Audit and final state

- PostgreSQL append-only audit: `agent.work.started` ID 349078 and `agent.work.completed` ID 349682. The completion event records the applied code SHA, schema 90, settings, six-blog scheduled scope, Worker heartbeat, and Blogger read/write counts.
- Code and operational reflection commit: `11853f175f46016e1f449f6c253fb0485155b16b`; pushed to `origin/develop` and confirmed running in the services.
- The follow-up documentation-only commit is recorded in Git history after this change.
- `AutoMode` and `AutoPolicyActive` were left unchanged as requested. Current Worker status is `manual` / `false`. Global settings 15/100 and scheduled scope six are separate from auto mode and approval state. Existing per-language safety limits remain under the global LIVE cap.
- Pre-existing untracked files and test artifacts were preserved; none were cleaned.
