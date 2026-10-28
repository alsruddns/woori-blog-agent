# P5-CODEX-004 — 디자인 시스템 및 검색 SEO 점검 기록

- 실행일: 2026-10-28 (Asia/Seoul)
- 브랜치/기준: `develop`, 시작 HEAD `dd5290dbfcb956ec05bbfc37f1e4baaa86ce4b7c`
- 목적: P5-CODEX-003 편집 표준을 유지하면서 반복 사용 가능한 게시 렌더러·공통 디자인 토큰·SEO 메타데이터와 사전 점검을 연결한다.
- 비용/외부 쓰기: AI API 0회, Blogger API 0회, Blogger 테마 변경 0회, 운영 원고 변경 0회.

## 구현

1. `editorial-writing-standard.md`에 분석 글의 사실→의미→시사점 흐름을 추가했다. 이는 필요할 때 쓰는 논리 기준이며 고정 문단 서식이 아니다. 근거 밖 해석과 반복적 키워드 삽입을 금지하고 HTML/CSS가 원고에 없는 사실이나 주장을 보태지 않도록 명시했다.
2. 공통 Woori editorial CSS를 `apps/dashboard/public/blogger-editorial.css`에 두고 preview iframe이 해당 파일을 CSP 허용 범위에서 로드하게 했다. 기본 토큰은 본문 17px/1.8, 읽기 폭 750px, H2 25px, H3 20px이며 모바일 본문은 16px 이상이다. 4개 언어의 시스템 폰트 fallback, 카드·표·인용·이미지·URL wrap, 명암 테마를 포함한다. `docs/operations/blogger-editorial-theme.css`는 동일한 파일 사본이며 자동 설치되지 않는다.
3. 기존 Markdown renderer와 HTML sanitizer를 재사용했다. 제목은 Blogger 제목 필드에만 표시되고 일치 H1은 본문에서 제거된다. Front matter/허용되지 않은 active markup/이벤트 속성은 게시 HTML에 들어가지 않는다. 허용 목록과 `wb-*` 의미 클래스 외 임의 스타일은 만들지 않는다.
4. `editorial_seo.py`에 버전 가능한 메타데이터와 nullable Search Console 측정 자료 모델을 추가했다. 검색 의도, 지역, 주요/관련어, 제목 후보, 검색 설명, 핵심 질문·답, 카테고리·라벨, 연결 출처, 사실 확인 시각, 작성자/검토 상태를 구조화한다. Google Trends 라벨은 기존 결정론적 locale 정책을 재사용한다.
5. SEO 점검을 점수/순위 예측 없이 구체적인 준비·검토·미측정 상태로 제공한다. 대상 제목 일치, 설명 유무, 핵심 표현 존재(자연스러움은 사람 확인), 제목/소제목 구조, 출처 링크, 출처 공식성, alt, 문장-근거 의미 검토, 링크 도달성, 중복 콘텐츠, 사실 최신성, Blogger 관리자 검색 설명 및 테마 SEO 설정을 구분한다. Search Console 연결 전 수치는 null/미측정이다.
6. 편집 상세의 SEO 점검 화면에 실제 저장된 값과 알 수 없는 값을 표시했다. 기존 편집 revision에 `seo_metadata`를 추가로 보존하는 additive Migration 041을 만들고 migration runner에 등록했다. 출처의 신원은 저장된 사실 자료에서 가져오며, 편집 요청이 공식 출처라고 자체 주장해도 시스템은 미검증으로 저장한다.

## Blogger 지원 범위 및 제약

2026-10-28 Google 공식 문서 기준 Blogger API v3 Posts 리소스는 제목, HTML 콘텐츠, 라벨 등 문서화된 필드를 포함하지만 검색 설명 또는 custom permalink 필드를 노출하지 않는다. Blogger 도움말은 관리자 UI에서 검색 설명, 사용자 지정 퍼머링크, alt 텍스트, 검색 노출/robots 설정을 관리하는 절차를 설명한다. 그래서 SEO 설명은 로컬 revision에 보존하고 수동 Blogger 편집 필요로 표시한다. canonical, robots, Open Graph, Article JSON-LD와 sitemap은 테마/사이트 수준에서 조사해야 하며 이번 renderer는 이를 삽입하지 않는다. 현재 네 실제 테마는 저장소에 없어 호환성이 미검증이다. 상세는 `docs/operations/blogger-seo-and-metadata.md` 참조.

## 검사 및 결과

- `scripts/verify.ps1`: 최종 실행 성공. Ruff, mypy, pytest 251개, isolated wheel, ESLint, Next production build, TypeScript, `git diff --check` 모두 통과.
- `test_article_reviews.py`: 마지막 변경 이후 26개 통과.
- Playwright `Blogger article preview` desktop/mobile 2개 통과. 320, 390, 430, 768, 1280px viewport에서 수평 넘침 없음; CSS가 sandboxed preview에서 적용되고 dark media 설정에서도 글자색을 확인했다. API 응답은 Mock route이며 운영 콘텐츠를 읽거나 쓰지 않았다.
- 전체 검증의 첫 실행은 test DB 스키마 40 때문에 revision SQL이 `seo_metadata` 컬럼 누락으로 2개 실패했다. DB와 역할을 명시적으로 확인한 뒤 `woori_blog_agent_test`/`woori_test_owner`에만 041을 적용하고 재실행해 모두 통과했다. 운영 DB에는 마이그레이션을 적용하지 않았다.
- API/Post preview는 비영구 렌더링이며 게시 수행값은 false다. 본문 중복 H1, 안전한 HTML, 다국어 evaluation article 렌더 회귀를 추가했다.

## 검토가 남은 사항

- 운영 Dashboard revision 편집은 Migration 041 적용 후에만 새 SEO metadata 저장을 지원한다. 이 단계에서 운영 DB는 변경하지 않았다.
- 네 Blogger 실테마의 CSS 선택자/구조화 데이터/canonical/robots/OG/sitemap, 게시글 검색 설명 적용, custom permalink 동작은 수동 테마·관리자 검토 전까지 미검증이다.
- 링크 실제 응답 확인, 기존 공개 글과 중복 비교, Search Console 계정/성과 수집은 구현하지 않았고 미측정으로 표시한다.
- CSS 변경이 실제 Blogger 표시와 완전히 같다고 주장하지 않는다. 이미지 표시, 폰트 로딩, 전역 CSS, 위젯, Blogger HTML 정규화 차이가 남는다.

수정 전에는 공통 preview CSS가 컴포넌트 문자열에 내장되고 디자인 변수가 중복됐으며 SEO 준비 상태가 preview UI에서 표시되지 않았다. 수정 후 CSS 토큰/renderer/SEO checks가 버전과 결과 hash로 추적되며, 원본 Markdown/SEO metadata/게시 HTML은 분리된다. SEO/표시 개선은 검색 순위 상승을 의미하지 않는다.

커밋 해시는 작업 완료 후 이 문서와 JSON 결과에 기록한다.
