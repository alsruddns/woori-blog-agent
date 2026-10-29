# P5-CODEX-029 — Korean Blogger first public post review

## 작업 기록

- 작업 시각: 2026-10-29 (Asia/Seoul)
- 브랜치: `develop`
- 실행 ID: `38c490eb-1099-4d17-9ccb-09f5c690a9c2`
- 목적: 승인된 한국어 원고 1편을 Blogger에 공개하고 실제 URL을 확인할 수 있는지 운영 차단을 점검한다.
- 결과: 실제 읽기 경로와 검토 가능한 원고 버전을 확인했다. 게시 승인과 출처·권리 검토가 충족되지 않아 어떤 Blogger 쓰기 요청도 보내지 않았다.

## 변경 전 / 후

- 변경 전: Dashboard/API 실행 포트와 Worker heartbeat, OAuth/원고/승인 상태의 현재성을 다시 확인해야 했다. 게시 적격 원고와 publication approval은 0건으로 보고되어 있었다.
- 변경 후: Dashboard 3100과 API 8100은 모두 HTTP 200, 운영 DB identity는 `woori_blog_agent` / `woori_app`, Research Worker heartbeat는 PID 13436에서 `running`으로 확인했다. 한국어 Blogger의 읽기 연결은 HTTP 200이며 기존 초안 ID `3147869148049076326`을 같은 연결로 재조회해 `DRAFT` 상태를 확인했다. 기존 초안은 수정하거나 공개하지 않았다.
- 앱 코드, DB schema, OAuth 매핑, 콘텐츠 버전은 변경하지 않았다. 새 개발 기록과 실행 감사만 추가했다.

## 원고 및 근거 검토

- Research Package: `c0b6f2b2-7a74-4b3f-a4f1-f4219c12321d`
- 상태: `evidence_collected_pending_human_review`
- 포함 자료: 공식 Federal Reserve Board FOMC 성명 1건, 확인된 fact 11건, 독립 출처 그룹 0건.
- 허용된 공식 자료 GET 결과: HTTP 200, Federal Reserve Board의 2026-10-28 FOMC 성명 페이지. 목표 금리 범위 `3-3/4 to 4 percent`, 10–2 표결, 경제활동·고용·물가 문구를 원문에서 확인했다. 검색어 및 요약문만으로 검증하지 않았다.
- 등록된 권리 설명은 Board-authored text의 공공영역 기본 원칙과 제3자 자료 제외를 적고 있으나, 이 원고에 대한 사람의 권리 검토는 완료되지 않았다.
- 원고는 미래 금리 방향을 단정하지 않으며 최신 공식 성명에 날짜가 부합한다. 다만 유일한 근거의 의미적 독립 검증은 없고, 일부 해석의 의미 검토와 편집 승인이 남아 있다.
- Content version: `38ac3a4b-2ce3-4920-86f0-e0706ff76c1d`, version 4.
- 제목: `미 연준 금리 동결, 인하 신호일까? FOMC 결정 읽기`
- 원고 SHA-256: `3127bff4b72aa8700d1b8ca5bfb2c193b39b62c2ef958ff950ee1a9eca463232`
- 저장된 기계 평가: machine checks 통과, SEO 검사에 검토/미측정 항목 존재, HTML 생성됨. 이는 사람 편집·권리·사실 승인이나 공개 자격을 의미하지 않는다.
- `publish_ready=false`; import 상태 `awaiting_human_review`; 독립 출처 확인 false; publication approval 수 0.
- 저장된 본문 마지막 단락에도 내부 `[source:...]` 표식이 포함되어 있다. 안전 HTML에서는 표식이 제거되지만 본문 수정은 새 불변 편집 버전을 만든 뒤 재검사해야 한다.

## 승인 및 게시 경로

- Blogger 연결 A는 한국어 블로그 `3321654108096579717`에 매핑되어 있고 이번 검증의 등록 blog GET은 통과했다. `users/self` 조회는 앞선 P5-CODEX-028 기록에 있다. 읽기 검증은 쓰기 권한 검증을 대체하지 않는다.
- 외부 정책은 읽기 요청을 허용했으며 `public_publish_approved=false`다. 실제 게시용 별도 승인 이벤트는 없다.
- Blogger 실제 초안 생성: 0건. Blogger 실제 공개 게시: 0건. postId/URL 신규 발행 기록: 없음.
- 실제 공개 게시를 진행하려면 먼저 Dashboard `/manuscripts`에서 위 version의 편집·출처·권리 검토를 수행하고, 필요한 수정은 새 editorial version으로 저장해야 한다. 이후 그 정확한 editorial version과 본문 SHA-256에 대해 사람의 positive editorial review 및 publication approval 이벤트가 있어야 한다. 별도 공개 게시 승인 정책 이벤트도 필요하다. 기존 초안은 이 승인 대상이 아니다.
- 게시 이후에만 Blogger 원격 GET, DB 원장 기록 및 Dashboard 게시 기록을 실제 성공으로 표시할 수 있다. 현재 단계에서 이 상태를 성공으로 가장하지 않는다.
- 운영 모드는 `manual`, Auto OFF, `daily_auto_limit=1`, `minimum_interval_minutes=1440`, Asia/Seoul이며 변경하지 않았다.

## 검증 및 감사

- `scripts/status.ps1`: Dashboard 3100 PID 43556, API 8100 PID 21720, Worker child PID 13436. 사용자가 실행한 Worker 프로세스는 재시작·종료하지 않았다.
- `http://127.0.0.1:8100/health`: HTTP 200.
- `http://127.0.0.1:3100/research`: HTTP 200.
- Blogger Korean `blogs.get`에 해당하는 연결 확인: 성공, 대상 ID 일치.
- 기존 한국어 draft GET: 성공, `DRAFT`. 기존 4개 초안 중 어떤 것도 쓰지 않았다.
- Blogger POST/PATCH/DELETE: 0회. 공개 게시: 0회.
- 기존 운영 DB에서 작업 시작 이벤트를 `audit_events`에 추가했다. 시작/완료 실행은 `job_runs`의 diagnostic 기록으로 연결한다.
- 자동화 단위 테스트는 수행하지 않았다. 이번 변경은 운영 점검 및 개발 기록이며 앱 코드는 변경하지 않았다.

## 파일·커밋

- 추가: `docs/development/P5-CODEX-029-first-post.md`
- 테스트 결과: 해당 없음(코드 변경 없음); 실제 읽기 전용 운영 검증은 위 기록 참조.
- 커밋 해시: 이 기록은 commit 뒤의 `git log`에서 확인한다(자기 참조 해시는 후속 기록으로 연결).
- 남은 문제: 독립 출처 검토 0건, 권리·편집 승인 미완료, exact-version publication approval 0건, 별도 public-publish approval 부재. 사용자가 Dashboard에서 검토·승인하기 전 공개 게시를 실행할 수 없다.
