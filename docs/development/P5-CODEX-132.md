# P5-CODEX-132 — Blogger 검색 설명 자동 생성 및 반영 개선

- 작업 일시: 2026-11-04 (Asia/Seoul)
- 브랜치: `develop`
- 시작 HEAD: `58301e73e8d770a46faf8d65ecdd98f76d93ede4`
- 작업 시작 감사 이벤트: `agent.work.started`, id `347891`
- 작업 완료 이벤트와 최종 커밋 해시는 후속 감사 기록 및 Git 이력으로 연결한다.

## 기존 문제와 목적

원고·Import에는 `seo_metadata.search_description` 또는 editorial SEO 설명이 있을 수 있지만, 일부 Content Version에는 설명이 없었다. Blogger Posts API 요청은 공식적으로 확인된 필드만 포함하며 검색 설명을 전달하지 않는다. 그래서 생성/로컬 저장 상태와 Blogger 실제 적용을 분리하고, 수동·예약·Trends 발행에서 같은 설명 생성을 사용하도록 했다.

공식 Blogger API v3 Posts resource 및 `posts.insert` 문서는 게시물 필드로 title, content, labels 등을 기술하지만 `searchDescription`이나 `customMetaData`를 게시물별 필드로 문서화하지 않는다. `customMetaData`는 Blogs resource의 블로그 단위 JSON 메타데이터다. 공식 문서에 없는 필드를 발행 요청에 임의로 추가하지 않는다.

## 변경 전후

- 이전: 기존 검색 설명이 없으면 누락될 수 있었고, Blogger 전달/검증 상태 표현이 메타데이터 존재 여부와 섞여 있었다.
- 이후: 기존 설명을 우선 재사용한다. 없으면 해당 Content Version의 제목과 리드/본문에서 사실을 추가하지 않는 결정적 설명을 만들고 150자 이내로 제한한다. editorial revision이 존재하면 이전 Import 본문에 딸린 설명을 재사용하지 않는다.
- 생성 설명은 Content Version, editorial/import revision, 언어, 본문 해시와 연결해 append-only `audit_events`에 기록한다. 동일 revision 재호출은 기존 기록을 재사용한다.
- Blogger 상태는 `APPLY_PENDING`으로 표시한다. Blogger API 미지원 상태와 실제 HTML meta description 확인 여부는 별도 표시한다. 현재 테마 출력 및 Blogger 편집기 필드 반영은 검증되지 않았다.
- 발행 요청은 검색 설명을 생성/저장하지 못해도 기존 적격성·큐 정책을 따른다. 설명 생성 실패는 낮은 심각도의 보완사항으로 기록하며 정상 발행을 중단하지 않는다.
- 기존 라벨은 그대로 유지한다. Blogger Posts payload는 title/content/labels만 포함하며 검색 설명 필드를 추가하지 않는다.

## 수정 파일

- `services/api/woori/blogger_search_description.py`: revision-bound 설명 추출·생성, 길이 제한, append-only 저장/재사용.
- `services/api/woori/publications.py`: 공통 발행 스냅샷에 설명과 반영 상태 연결, stale description 방지, 보완사항 기록.
- `services/api/woori/publication_worker.py`: 수동·예약·Trends 공통 발행 처리와 재조정 경로에서 동일 설명 저장을 사용.
- `services/api/woori/blogger_publication_package.py`: 미리보기 패키지에 설명/언어/길이/상태 표시. 실제 Blogger 요청 body에는 미지원 필드를 넣지 않음.
- `apps/dashboard/app/manuscripts/workspace.tsx`, `apps/dashboard/app/manuscripts/article-preview.module.css`: 원고 발행 준비 화면에 설명, 글자 수, 언어, 로컬 저장 및 Blogger 반영 상태, 복사 동작 표시.
- `services/api/tests/test_blogger_search_description.py`: 6개 locale, 150자 제한, 기존 메타데이터 재사용, revision 변경, 저장 멱등성, 빈 본문 검증.
- `services/api/tests/test_article_reviews.py`, `services/api/tests/test_publications.py`, `services/api/tests/test_blogger_live_policy.py`: 공통 경로, 저장, 정확한 Posts payload 및 기존 라벨 회귀 검증.
- `docs/operations/blogger-seo-and-metadata.md`: 지원 API 경계와 검증되지 않은 적용 상태 문서화.

## 데이터 및 운영 보호

- DB schema 변경/Migration: 없음. 설명 기록은 기존 append-only `audit_events`를 사용한다.
- 운영 설정, OAuth, Blogger 연결, 예약 작업, 기존 게시 이력 변경: 없음.
- 실제 Blogger 게시/수정/초안 요청: 0건. Blogger 쓰기는 Mock/fake 기반 테스트만 사용했다.
- Google 검색 색인 완료나 Blogger 편집기 검색 설명 입력 성공을 보장하지 않는다.
- 테스트 및 production build는 격리된 Dashboard dist 디렉터리를 사용했다. 빌드가 생성한 `next-env.d.ts` 및 `tsconfig.json` 변경은 원래 상태로 복구했다.
- 작업 시작 시 tracked 변경은 없었다. 기존 미추적 pytest/browser 산출물은 삭제하거나 stage하지 않았다.

## 검증

- API 집중 테스트: `139 passed, 1 warning` (Blogger search description, article review, publications, Blogger live policy, Trends publication 회귀 테스트). 경고는 기존 `.pytest_cache` 쓰기 권한으로 인한 cache 경고이며 테스트 결과에는 영향을 주지 않았다.
- Ruff: 통과. 변경 API 모듈 및 테스트 파일을 검사했다.
- mypy: 변경 API 모듈 4개, 오류 없음.
- Dashboard lint: 통과.
- Dashboard typecheck: `next typegen` 및 `tsc --noEmit` 통과.
- Dashboard isolated production build는 안전 반영 스크립트에서 재검증한다.
- 운영 서비스 상태는 2026-11-04 확인 시 Dashboard/API/Research Worker/Publication Worker가 실행 중이었다. API와 Publication Worker의 기존 AppliedCommit은 `5826b59bbb1944ed4a954745ffe4e6270c256217`, Dashboard는 `6e7541524c421c23d2fcdd1011a32660474cb83b`, Research Worker는 `67e9218c1fecafffab079da4e960fbd979642dbb`였다. DB schema는 애플리케이션 기능상 migration이 없어 변경하지 않는다.
- 읽기 전용 운영 점검에서 queued/running/uncertain 발행 Job 0건, queued/running Research Job 0건, Worker heartbeat 정상, LIVE queue due 0건을 확인했다.
- 안전 반영 스크립트 적용 및 서비스별 실제 반영 상태는 완료 후 갱신한다.

## 남은 문제

- Blogger API v3 게시물별 검색 설명 쓰기는 공식 문서에서 지원이 확인되지 않았다. Blogger 편집기 수동 입력 또는 테마의 동적 meta description은 별도 검증이 필요하다.
- 본 변경은 검색 설명 생성/로컬 저장 및 Dashboard 표시를 완료하지만 Blogger 적용을 `APPLIED_VERIFIED`로 만들지 않는다.
- 실제 Blogger write는 금지되어 수행하지 않았다.

## 커밋 및 완료 상태

- 테스트 결과, 운영 반영, 완료 감사 이벤트, 최종 Git commit/push 결과는 후속 기록으로 갱신한다.
