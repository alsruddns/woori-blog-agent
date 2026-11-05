# P5-CODEX-139 — Codex 예약 Resolver 이후 원고 미작성 복구

## 작업 정보

- 작업 시작: 2026-11-05 09:02:25 KST, `agent.work.started` PostgreSQL audit ID `367484`
- 브랜치: `develop`
- 시작 HEAD / `origin/develop`: `40e4f7defc4f234109834dbf6963ba38c32612d6`
- 시작 tracked worktree: clean. 기존 stash 및 미추적 파일은 보존했다.
- 기존 기록 확인: P122, P123, P131, P133, P138 및 scheduled outage recovery 문서.
- 운영 DB: schema 92, settings revision 23.
- 작업 범위: automation-6 실제 07:00 KST 실패 증거를 확인하고 해당 자동화 prompt 실행 순서만 보강했다. Worker 코드·DB 정책·RRULE·Automation ID·주제·언어·대상 블로그는 변경하지 않았다.

## automation-6 07:00 KST 실제 세션

- 로컬 Desktop thread: `01a1a893-e2e8-76d2-8e66-0551dc34183e`; transcript는 실제 `originator=Codex Desktop`, `thread_source=automation`, project checkout으로 기록돼 있다.
- 현재 turn: `01a1a893-e535-7ea3-9543-8f951e8602c6`, trigger `automation_cron_scheduled`, Automation ID `automation-6`.
- 실제 slot `2026-11-05T07:00:00+09:00`; `executed_at=07:00:27`; project-derived occurrence `codex-slot:automation-6:20261105T0700KST`.
- Resolver는 `resolved=true`, `execution_mode=scheduled`, slot gate `ready`, authoring policy `allowed=true`, revision 23을 반환했다. 로컬 `progress/43459d249a98400fb61a34a5717a9ab5.json`는 scheduled 상태이며, execution receipt `592a7db44a072e8a45f8c1db5ba488d3f91be0727d911ef8adc37287b437cbd2.json`이 존재한다.
- 다음 `scheduled_duplicate_check.py --stage generation` 실행은 transcript에 없다. 해당 occurrence용 duplicate 결과도 없고 `incoming/`, snapshot, `ready/`, Import Receipt 및 DB Import 기록도 없다. 따라서 사실 단계는 `RESOLVER_PASSED`까지다.
- transcript에 기록된 tool call은 하나뿐이다. 한 PowerShell 호출에서 `memory.md` 전체, recovery 문서 100줄, schema 80줄, `git status`, Resolver를 순서대로 한꺼번에 실행했다. command 결과는 4.6초, 총 4,578 tokens로 tool output 4,000-token 한도 초과/잘림 경고가 있었다. Resolver JSON은 잘린 출력 끝부분에 있었고 `resolved=true`와 정책 허용이 보인다.
- Desktop turn은 07:00:27에 시작해 07:00:41에 정상 완료됐다(약 14초). task completion의 `codex_error_info=null`; 실행 기록에는 강제 종료나 usage-limit 오류가 없다. token usage는 누적 75,832 (input 75,452, output 380), model context 258,400, Codex rate limit reached type null이다. 즉 강제 시간·토큰 한도에 의한 종료가 아니다.
- 마지막 assistant 출력은 중복 검사와 원고 전달을 하지 못했다고 인정한 뒤 “memory에 기록하고 다음 실행에서 이어간다”고 끝냈다. 후속 tool call은 없다. 실제 원인은 Resolver가 중복 검사 CLI를 자동 호출하지 않는 구조와, 과대한 단일 초기 inspection call 뒤 실행을 완료/이월로 잘못 판단한 모델의 조기 정상 종료다. 코드 예외나 Resolver 실패로 원인을 추측하지 않았다.
- 실행에서 읽은 `C:\Users\achie\.codex\automations\automation-6\memory.md`는 11월 4일 기록이 마지막이며 11월 5일 07:00 중단 기록은 없다. transcript에도 memory 쓰기 도구 호출은 없었다. 따라서 이번에는 memory 완료 주장에 의존하지 않았다.

## 예약 정의와 변경

- 로컬 TOML 21개(20 ACTIVE, 1 PAUSED)를 확인했다. 20개 활성 prompt 모두 Resolver, generation-stage duplicate preflight, handoff 도구와 “highest-priority execution order” 지시를 포함한다. `next run`으로 이월하는 명시적 지침은 없었다.
- 문제 실행의 Automation ID `automation-6` prompt는 원래 32,938자였다. 사용자 홈의 기존 `automation.toml`에만 P139 실행 규칙을 앞에 추가했다. 새 규칙은 첫 도구 호출을 Resolver 단독 실행으로 제한하고, 허용 응답 다음 도구 호출을 duplicate preflight로 고정하며, 긴 문서/memory/status를 preflight 전에 출력하지 않도록 한다. Resolver 통과·memory 기록·요약만으로 종료하거나 현재 occurrence를 다음 slot으로 넘기지 말라고 명시했다. ready handoff는 여전히 기존 P131/P133 계약을 쓰고, Import/Receipt는 Research Worker의 실제 receipt로 확인하도록 했다.
- TOML은 재파싱 검증했다. Automation ID, 상태 ACTIVE, RRULE `TU,WE,TH,FR,SA 07:00 Asia/Seoul`, model, 이름 및 대상 설정은 이전과 동일하고 기존 prompt 전체를 suffix로 보존했다. 기존 prompt 32,938자 → 34,870자. SHA-256 이전 `fab0c399f8e69ffac861d04fd2ec9032c52bc4712af36738b2feb268cea8eca0`, 이후 `9b6cef5915029652eb35be013bb6023967f42b561d372bfc48c5efa23a6ee515`.
- Codex Desktop 공식 Scheduled UI는 설치된 `computer-use` skill의 UI 자동화 제한 때문에 읽거나 수정 동기화를 확인하지 않았다. 위 결과는 실제 transcript와 로컬 TOML에서 확인한 상태다. Desktop UI 목록·다음 실행 시각·prompt 동기화는 미확인이다.
- `scripts/resolve-codex-automation-run.py`는 identity/slot/authoring policy를 검증해 반환하고, 별도 `scheduled_duplicate_check.py --stage generation`가 실제 중복 사전검사를 수행한다. 07:00 실행의 Resolver 명령 자체는 성공했으며 후속 CLI 호출이 없었다. 고장 난 import/handoff 코드나 CLI 부재는 발견되지 않았다.

## 격리 검증

- Resolver, scheduled/manual authoring contract, generation duplicate CLI/progress, exclusive ready handoff, scheduled inbox Import/Receipt, scheduled publication policy/priority: **199 passed** (`.local/p5-codex-139-pytest-tmp`). 테스트는 격리 fixture/DB/API 및 mock transport를 사용했다.
- Google Trends authoring/publication 회귀: **88 passed** (`test_keyword_authoring.py`, `test_trends_post_edit.py`, `test_trends_publication.py`, `test_trends.py`; `.local/p5-codex-139-trends-pytest-tmp`).
- 이 테스트는 Resolver/preflight/handoff/import 단계별 scheduled fixture를 검증하지만, 실제 Desktop 세션이 수행한 최신 web research 또는 단일 live service E2E를 대체하지 않는다. 테스트 Blogger HTTP write: 0. Paid AI/API calls: 0.
- 실제 automation-6 07:00 occurrence를 재생하지 않았고, 새 예약/Run now를 UI에서 시작하지 않았다. 새 원고, Snapshot, Import Receipt 또는 queue entry를 테스트용으로 만들지 않았다.

## 운영 상태 확인

- 현재 설정 revision 23: `AutoMode=auto`, `AutoPolicyActive=true`, minimum interval 15분, KST daily LIVE cap 100, Scheduled Auto ON. 활성 Blogger 6개 EN/KO/JA/DE/pt-BR/VI; zh-CN 비활성. 운영 설정 수정 없음.
- 기존 24개 scheduled Import는 전부 `awaiting_human_review`; 가장 최근 Import는 11월 4일 07:09 KST로 P136 자동 발행 활성화보다 오래됐다. 과거 Import 재등록/상태 변경 없음. `scheduled_auto` queue에는 이전 성공 1건, 신규 대기 job 0건이었다.
- Research Worker PID 26460, Publication Worker PID 37292 heartbeat 정상; API PID 27168, Dashboard PID 30216. API `/health`와 Dashboard `/research` 모두 HTTP 200. Worker revision `170f17e`. 재기동은 하지 않았다.
- Google Trends 보호 검증: 수집 enabled, 30분, 최근 24시간 `google_trends_rss` 성공 672회/14개 지역, 최신 09:00:22 KST.
- 이 작업 중 Publication Worker가 기존 운영 Trends LIVE Job `5672d054-b3da-4655-ad06-687d7772e25d`를 09:04:01 KST에 발행 완료했다. 이는 P139 테스트가 만든 게시물이 아니며, P139 테스트 Blogger 쓰기는 0건이다. 예약 원고 E2E 증거로 계산하지 않았다.
- 현재 상태 재확인 때 LIVE queued/due 0, scheduled-auto queued 0. 예약 활성화 후의 신규 scheduled Import/Receipt/Publication Queue 연결은 입력이 없어 검증되지 않았다.

## 최종 판단

- 확인된 미작성 원인: Resolver 정상 반환 후 orchestration을 맡은 Desktop 모델 turn이 다음 CLI를 호출하지 않고 정상 종료했으며, 대용량 inspection 호출과 부정확한 “다음 실행에서 이어감” 결론이 그 판단을 동반했다. 시간/usage quota 초과나 코드 실행 실패 증거는 없다.
- 수정: automation-6 로컬 prompt의 실행 순서만 보강. Backend/Worker code 및 DB 설정 변경 없음.
- 격리 회귀 검증: 199 + 88 tests 통과.
- 실제 새 Desktop scheduled execution 및 원고/Receipt/Publication Queue: **미검증**. `computer-use` 제한 때문에 공식 UI Run now/예약 조작은 하지 않았다.
- 서비스 재기동: 없음. Google Trends, 자동발행 승인, OAuth, 기존 게시·예약 기록 보호.
- 변경 파일: `C:\Users\achie\.codex\automations\automation-6\automation.toml` (Git 외부 prompt), `docs/development/P5-CODEX-139.md`.
- 최종 Git commit/push: 개발 기록 커밋 이후 Git 이력 참조.
- 남은 문제: 새로운 공식 Desktop 예약 실행에서 수정 prompt가 반영됐는지와 duplicate → snapshot → ready → Worker Receipt → eligible queue를 실제로 확인해야 운영 복구 완료로 판정할 수 있다.
