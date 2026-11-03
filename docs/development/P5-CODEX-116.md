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

실패 원고는 원격 중복 근거가 없어 명시적 새 요청의 대상이 될 수 있지만, 이 변경은 Job을 재시도·재등록하지 않았다. 현재 전역 공개 승인 상태는 비활성이고 운영 모드도 `manual`이다. 따라서 실제 공개 쓰기는 여전히 차단되어 있으며 관리자의 새 명시적 발행 요청 및 현재 승인 게이트 통과가 필요하다.

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

현재 서비스 반영 전 PID는 Dashboard 28792, API 9192, Research Worker 31708, Publication Worker 17108이며 Worker heartbeat는 fresh였다. Publication Worker는 실패 Job 외에 due/queued LIVE 작업이 0건이었다. 정상 종료를 보장하는 프로젝트의 `scripts/apply-verified-changes.ps1 -Apply`로 변경 검증과 API/Publication Worker 코드 반영을 수행한다. 강제 종료, 기존 실패 Job 자동 재실행은 하지 않는다. 반영 후 실제 PID, heartbeat, 설정 revision, queue 상태를 아래에 추가한다.

## 남은 문제 / 제한

- 과거 Job의 실제 Blogger 게시는 확인되지 않았다. 운영 공개 승인 상태가 OFF이므로 이 코드 변경만으로 게시할 수 없다.
- 여섯 블로그의 ID·연결·OAuth scope는 DB에서 확인했지만, 실제 Blogger 쓰기 권한과 공개 결과는 Mock 외부에서 검증하지 않았다.
- Dashboard가 표시하는 실패 상태는 운영자가 새 발행 요청을 하기 전까지 기존 이력으로 유지된다.

## 마무리 기록

- 최종 테스트: focused 31 passed, publication regression 132 passed
- 최종 서비스 반영: 기록 예정
- 완료 감사 이벤트: 기록 예정
- 커밋: 기록 예정 (이 문서 수정 이후 `git log`로 확인)
