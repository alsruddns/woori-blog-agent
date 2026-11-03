# P5-CODEX-120 — Blogger SEO 및 수동 발행 장애 수정

- 작업 ID: P5-CODEX-120
- 작업 시각: 2026-11-03 17:56–18:05 KST (구현·검증·안전 반영)
- 브랜치: `develop`
- 시작 HEAD: `a9942e28d323dd977a769cc1ae6c2f5e7c365d68`
- 변경 사유: 수동 발행의 무반응처럼 보이는 사전 검사 오류와 `manual_publication_available`/`publish_ready` 의미 혼선, 검토되지 않은 원고의 발행 요청 허용 가능성을 수정하고 Blogger SEO 적용 상태를 정직하게 표시

## 기존 문제와 변경 목적

- `manual_publication_available`은 연결된 Import가 있어 수동 검사 절차를 시작할 수 있는지 나타내는 목록 필드였고, 실제 발행 적격성을 뜻하지 않았다. 사용자가 받은 상세 응답도 `publish_ready=false`, 미검증 주장 5건 및 사람 검토 대기 상태였다. 이는 수동 POST 오류 응답이 아니었다.
- 그리드의 수동 발행 버튼은 먼저 Import 상세 GET을 완료해야 모달을 열었다. GET 실패 또는 버전/대상 불일치가 페이지 상단 상태에만 표시되어 클릭이 반응하지 않는 것처럼 보였다.
- 운영 DB에는 `global_publication_mode_mismatch` 사유의 이전 자동 사전 실패 이력이 있었지만 P120 시작 시점 기준 최근 14일 `publication.manual_request.blocked`는 0건이었다. 그러므로 제공된 응답만으로 실제 수동 POST가 실패했다고 결론낼 근거는 없었다.
- 백엔드 수동 요청 경로가 원고의 기계 품질, 검토된 출처·근거, 권리, SEO/안전 HTML, 사람 검토, 최신 버전 승인 및 `publish_ready`를 모두 통과시키는지 강화했다. 확인 모달은 적격성 검사를 대체하지 않는다.
- Blogger API v3의 Posts 리소스/insert 문서에는 게시별 검색 설명이나 게시별 로봇 태그 쓰기 필드가 없다. 검색 설명은 내부 원고에 보존하며 Blogger 편집기 수동 입력 필요로 표시한다. Blogger HTML head, robots, canonical은 조회하지 못했으므로 미확인으로 둔다.

## 변경 전 / 변경 후

- 변경 전: API 사전 검사 중 모달이 나타나지 않을 수 있었고, 화면 상단 오류만으로 요청 실패처럼 보였다. `manual_publication_available=true`를 최종 적격성과 혼동할 수 있었다.
- 변경 후: 클릭 즉시 확인 모달을 열고 최신 eligibility GET을 모달 안에서 수행한다. 불러오기 실패 시 재검사 버튼과 구체적 오류를 보이며 큐 등록은 비활성 상태다. 요청 취소는 Job/쓰기 없이 끝난다고 명시한다. 서버는 현재 버전의 필수 품질·출처·사람 검토·승인 조건을 다시 평가하며 미통과면 Job을 만들지 않는다.
- 변경 후: SEO 데이터는 내부 저장 상태, API 지원 여부, Blogger 편집기 입력 필요, 실제 HTML/robots/canonical 검증 상태를 분리해 보여준다. 일반 콘텐츠 링크의 기본 동작은 follow이며 sanitizer가 `nofollow`를 강제 삽입하지 않는다. 기존 `noopener noreferrer`는 유지한다.
- 기존 6개 활성 Blogger, 중국어 비활성 상태, 운영 승인/발행 모드, OAuth, 예약, Job 및 게시 데이터는 수정하지 않았다.

## 변경 파일

- `services/api/woori/publications.py`
- `services/api/woori/editorial_html.py`
- `services/api/woori/blogger_publication_package.py`
- `services/api/tests/test_publications.py`
- `services/api/tests/test_article_reviews.py`
- `apps/dashboard/app/publishing/publication-manager.tsx`
- `apps/dashboard/app/style.css`
- `apps/dashboard/e2e/P5-CODEX-110-grid-publish.spec.ts`
- `docs/development/P5-CODEX-120.md`

## DB·운영·검증

- 시작 전 백업: `backups/20261103T084929Z.dump` (43,785,938 bytes, 백업 카탈로그 검증 완료)
- Migration: 없음.
- 시작·완료 감사 이벤트: PostgreSQL `audit_events`에 append-only 이벤트 기록. 시작 이벤트 ID 319392.
- 시작 이후 `blogger_write_operations`, `live_publication_attempts` 신규 행 0건. `blogger.write.*`, `publication.live.*`, `publication.manual_request.*` 감사 이벤트 0건. 이 작업에서 Blogger 실제 API 쓰기는 수행하지 않았다.
- 운영 서비스는 검증 전 기존 PID로 실행 중이었다. 변경 코드는 아직 운영 런타임에 반영되지 않았다. 반영은 검증·커밋 후 저장소의 safe reflection 절차로 진행한다.
- API 모드 `manual`, 긴급 정지 OFF 및 활성 EN/KO/JA/DE/PT-BR/VI 6개 설정을 읽기 확인했다. 실제 Blogger robots 설정과 공개 페이지 head는 확인하지 못했다.

### 테스트 결과

- API 집중 테스트: `test_publications.py`, `test_article_reviews.py` — 78 passed.
- Dashboard typecheck — 통과.
- Dashboard production build — 통과.
- Playwright 그리드 수동 발행 E2E — 10 passed, 1440px desktop 및 390px mobile 포함. 요청 URL/Method/HTTP 응답과 모달 실패 경로는 Mock route로 검증했다. Mock POST 201은 큐 등록 응답이며 Blogger 게시가 아니다.
- `git diff --check` — 통과.
- CUA 브라우저 연결을 시도했으나 도구가 Chrome의 현재 탭/URL을 확인하지 못해 운영 브라우저 검사로 이어지지 않았다. 실제 운영 사용자 클릭의 POST 응답은 캡처하지 않았다.

## 남은 문제 및 한계

- 실제 운영 원고의 수동 발행 POST는 수행하지 않았다. 사용자 제공 응답에는 POST 요청/응답이 없어 실제 발생 여부·HTTP 상태는 확인 불가다.
- Blogger API는 게시별 searchDescription/custom robot 필드를 문서화하지 않는다. 실제 SEO Description 입력은 Blogger 편집기에서 별도로 해야 한다.
- 운영 Blogger 공개 HTML의 `meta description`, robots, canonical 및 계정별 로봇 설정은 미검증이다. noindex/nofollow 설정을 변경하지 않았다.
- 실제 공개 성공 건수: 0 (이번 작업에서 운영 쓰기 없음).
- P5-CODEX-121 검토 요청은 P120 종료 후 별도 사전 점검으로 이어간다.

## 관련 문서

- [Blogger API Posts resource](https://developers.google.com/blogger/docs/3.0/reference/posts)
- [Blogger API posts.insert](https://developers.google.com/blogger/docs/3.0/reference/posts/insert)
- [Blogger search description and SEO](https://support.google.com/blogger/answer/41373?hl=en)
- `docs/operations/blogger-seo-and-metadata.md`
- `AGENTS.md`

## 커밋

- 커밋 해시: 후속 Git 기록으로 연결한다.
- 결과: 구현과 격리 테스트 완료. 운영 반영은 safe reflection 완료 후 갱신한다.
