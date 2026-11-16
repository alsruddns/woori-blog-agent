# P5-CODEX-116 — Publication Worker Allowlist 발행 차단 오류 수정

- 작업 시각: 2026-11-03 (Asia/Seoul)
- 브랜치 / 기준 HEAD: `develop` / `608dac2991fee4eb02b2766a41a89b84148ac61b`
- 변경 사유: 새 LIVE 게시 요청이 `destination or method not allowlisted`로 전송 전에 거부됨
- 작업 ID: P5-CODEX-116

## 기존 문제와 확인된 원인

오류는 Blogger 응답이 아니라 `services/api/woori/external_policy.py::_authorize()`에서 발생했다. 호스트 `www.googleapis.com`과 POST 메서드는 허용됐지만 `blogger_public_publish` 경로 규칙은 기존 Draft를 공개하는 `/blogs/{blogId}/posts/{postId}/publish`만 허용했다. `BloggerLivePublisher.create_live()`가 신규 공개 글을 생성할 때 사용하는 `/blogs/{blogId}/posts?isDraft=false`가 누락되어 외부 HTTP 요청 전에 차단된 것이 실제 원인이다.

운영에서 확인한 Job은 `cd2cf44a-98f6-47fc-8201-b801c13789e9`, Content Version은 `8c79d7de-ad97-4d29-8127-b56d992d16ec`이다. 원고는 `scheduled` 경로로 Import됐지만 게시 Job의 lane은 명시적 관리자 요청인 `manual`이다. 실패 당시 재시도 0회, `remote_post_id` 없음, 같은 Content Version·Blog 대상 Job 1건, 로컬 게시 기록 0건이었다. Blogger API 요청은 Allowlist 단계에서 차단되어 Blogger HTTP 응답은 없었다.

공식 Blogger API의 `Posts.insert`는 `/blogs/{blogId}/posts`에 POST하고 `isDraft`를 지원하며, 기존 Draft 공개는 `/blogs/{blogId}/posts/{postId}/publish`에 POST한다. 수정은 이 두 호출 형태만 허용한다. [Posts: insert](https://developers.google.com/blogger/docs/3.0/reference/posts/insert), [Posts: publish](https://developers.google.com/blogger/docs/3.0/reference/posts/publish)

## 변경 목적과 결과

- `blogger_public_publish`에 숫자 Blog ID를 사용한 정확한 신규 LIVE 삽입 경로를 추가했다. 쿼리는 단 하나의 `isDraft=false`만 허용한다.
- 기존 Draft publish 경로는 숫자 Blog ID와 post ID, query 없는 POST 조건 그대로 유지했다.
- 미등록 도메인, 임의 메서드, 비숫자 ID, 잘못된 경로, 추가 query, `isDraft=true` 공개 삽입은 차단한다.
- 별도 승인, Blogger 계정/Blog 매핑, OAuth 쓰기 scope, 비용 게이트, 운영 승인, 긴급 정지, 중복·폐기 검사 등 기존 검사와 전역 15분/일일 LIVE 100건 제한은 변경하지 않았다.
- Migration 없음. 설정·Revision·기존 Job·원고·게시 이력은 수정하지 않았다.

## 운영 실패 원고 및 Blogger 확인

실패 Job 대상 Trend Journal EN의 실제 Blog ID `5240203250707821039`를 운영 DB에서 확인했다. 승인된 Blogger 읽기 정책으로 원격 LIVE 및 Draft 목록을 각각 조회해 총 28개 게시물을 확인했고, 제목 기반 중복 검사는 `clear`를 반환했다. 이 읽기 결과는 해당 조회 시점 및 스캔한 Blogger 목록 기준이며 게시 요청은 하지 않았다. 읽기 호출은 감사 로그에 남았다.

실패 원고는 원격 중복 근거가 없어 명시적 새 요청의 대상이 될 수 있지만, 이 변경은 Job을 재시도·재등록하지 않았다. 현재 Automation revision 18의 `automatic_publication_operator_approved`는 ON이나, Blogger 공개 쓰기 별도 승인(`public_post_publish`)은 없고 운영 모드는 `manual`, `blogger_write_mode=manual_only`, 긴급 정지는 OFF이다. 따라서 allowlist 수정이 공개 쓰기 승인을 우회하지 않는다. 기존 실패 Job은 실패 상태로 남으며 새 명시적 발행 요청 및 해당 lane의 현재 승인 게이트 통과가 필요하다.

운영 DB의 Blog 설정은 EN/KO/JA/DE/PT-BR/VI 6개 활성, ZH-CN 비활성으로 확인했다. 각 활성 Blog 레코드는 연결 상태 `connected` 및 Blogger 쓰기 OAuth scope를 보유한다. 이 DB 매핑 확인은 이 작업에서 각 Blog의 실제 API 쓰기 가능성 테스트를 뜻하지 않는다. Blogger API 쓰기 권한은 Mock 외부에서 호출하지 않았다.

운영 백업은 코드 변경 및 진단 읽기 전 `backups/20261103T051845Z.dump`에 생성됐고 백업 카탈로그 검증을 통과했다. 시작 감사 이벤트 `agent.p5_codex_116.started`(event ID `315500`)는 백업 후 기록됐다. 완료 이벤트는 서비스 반영 후 추가한다.

## 수정 파일

- `services/api/woori/external_policy.py`
- `services/api/tests/test_blogger_live_policy.py`
- `docs/development/P5-CODEX-116.md`

## 검증

- `ruff check` — 통과
- `mypy --follow-imports=silent services/api/woori/external_policy.py` — 통과
- `pytest services/api/tests/test_blogger_live_policy.py` — 31 passed
- Publication 회귀 테스트 6개 파일 — 132 passed (isolated pytest temp directory)
- 테스트는 승인된 경로의 실제 allowlist 검증 및 Mock Blogger 흐름을 사용한다. 운영 Blogger POST는 0건.
- Migration 없음.

## 운영 반영 및 상태

반영 전 PID는 Dashboard 28792, API 9192, Research Worker 31708, Publication Worker 17108이며 Worker heartbeat는 fresh였다. Worker는 실패 Job 외에 due/queued LIVE 작업이 0건이고 `publishing` Job도 0건이었다. 저장소 반영 스크립트의 전체 검증은 통과했다. 첫 실행은 비대화형 PowerShell `ShouldProcess` 오류로 종료 요청 전 중단되어 아무 프로세스도 바뀌지 않았다. 두 번째 실행은 API를 graceful 종료했으나 기존 브라우저 연결로 Dashboard 종료가 거부되어 나머지 서비스를 중지하지 않았다. API는 즉시 새 코드로 시작했다. 이후 Publication Worker만 프로젝트 `stop.ps1`의 정상 종료 절차로 현재 작업 주기를 마친 뒤 종료하고, `start.ps1`로 재시작했다. 강제 종료나 실패 Job 재실행은 없었다.

반영 후 API PID `20260`, Publication Worker PID `34796`; 둘 다 적용 커밋 `b49f521b247dc7893113825c621751fbfe1aeacd`이다. Worker heartbeat는 fresh이며 Automation revision 18, runtime ack revision 18, engine `automation-controls/3`으로 일치했다. Worker queue는 live queued/due 각 0이고 기존 실패 Job 상태와 재시도 횟수 0이 유지됐다. API `/health`와 Dashboard `/`는 각각 HTTP 200이다. Dashboard PID `28792`는 기존 연결 때문에 교체하지 않았고, 이번 P116은 Dashboard 소스 변경이 없다. Research Worker PID `31708`도 유지됐다. API·Worker가 수정 코드를 사용하며 기존 UI 서비스는 계속 응답한다.

## 남은 문제 / 제한

- 과거 Job의 실제 Blogger 게시는 확인되지 않았다. 운영 공개 승인 상태가 OFF이므로 이 코드 변경만으로 게시할 수 없다.
- 여섯 블로그의 ID·연결·OAuth scope는 DB에서 확인했지만, 실제 Blogger 쓰기 권한과 공개 결과는 Mock 외부에서 검증하지 않았다.
- Dashboard가 표시하는 실패 상태는 운영자가 새 발행 요청을 하기 전까지 기존 이력으로 유지된다.

## 마무리 기록

- 최종 테스트: P116 focused 31 passed, 6개 발행 회귀 테스트 파일 132 passed, 저장소 반영 검증 API tests 41 passed; Ruff, mypy, wheel build, Dashboard lint/typecheck/build 통과. pytest 기본 캐시 폴더의 Windows 권한 경고는 있었으며 isolated `--basetemp` 재검증은 132건 정상 종료했다.
- 운영 쓰기 호출: 0. 원격 상태 확인은 Blogger 읽기 전용 목록 2회 요청, LIVE/Draft 합계 28건 스캔, 중복 상태 `clear`.
- DB 백업: `backups/20261103T051845Z.dump` (42,678,510 bytes), 카탈로그 검증됨. Migration 없음. 설정 revision 18 유지.
- 기존 실패 Job `cd2cf44a-98f6-47fc-8201-b801c13789e9`는 재시도하지 않았고, 원격 일치 없음은 조회 시점 스캔 결과다. Dashboard/Research Worker는 기존 PID 유지.
- 완료 감사 이벤트 `agent.p5_codex_116.completed`, ID `315553`.
- 구현 커밋: `b49f521b247dc7893113825c621751fbfe1aeacd`.
- 개발 기록 최종 커밋: 이 문서가 들어간 후속 커밋을 `git log`로 확인.
