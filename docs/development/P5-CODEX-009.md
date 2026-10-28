# P5-CODEX-009 — 실제 원고 통합 검증

## 목적과 범위

2026-10-28 기준 미국 소비·물가 관련 공식 발표를 이용해 한국어 경제 칼럼 한 편을 작성하고, 기존 `woori-content-import/1.0` → 격리 DB Import → 결정론적 품질·SEO 검사 → 게시 HTML 미리보기 → 사람 검토 대기 → Mock 게시 흐름을 검증했다. 운영 DB·운영 원고·Blogger 게시물은 수정하지 않았고 운영 마이그레이션도 실행하지 않았다.

요청된 GPT-6 Luna 모델 식별자는 이 Codex 실행 환경에서 독립 확인할 수 없었다. 원고는 현재 Codex 대화형 세션에서 작성했으며, 모델명이 확인되지 않아 Import의 `model_name`은 `null`로 두었다. 별도 OpenAI API, Codex CLI 하위 프로세스, 추가 유료 AI 서비스는 호출하지 않았다. 따라서 “GPT-6 Luna로 작성했음”은 이 검증에서 입증하지 못한 항목이다.

## 주제 및 공식 근거

주제는 “미국 소비가 버티는데 체감경기는 왜 갈라지나”다. 검색량·순위·예상 유입은 수집하거나 만들어내지 않았다. Google Trends 기반으로 수집한 기사가 아니므로 이슈 라벨을 부여하지 않고 경제 라벨을 사용했다.

자료 기준일은 2026-10-28이다.

| 출처 | 발표일 및 범위 | 칼럼에서 사용한 핵심 사실 |
|---|---|---|
| [Federal Reserve Beige Book](https://www.federalreserve.gov/monetarypolicy/beigebook202610-summary.htm) | 2026-10-14 발표, 현장 정보는 2026-10-05까지 | 12개 District 가운데 2곳은 보통 수준 성장, 3곳은 완만한 성장, 4곳은 소폭 성장, 3곳은 큰 변화가 없다고 보고. 대다수 지역에서 소비는 대체로 제자리였고 여러 지역에서 고소득 가구가 소비를 이끌었다는 연락처 보고가 포함됨. |
| [U.S. Census Bureau retail sales](https://www.census.gov/retail/sales.html) | 2026-10-15 발표, 2026년 9월 | 소매판매 잠정치는 7,450억 달러, 전월 대비 0.8%, 전년 동월 대비 6.3% 증가. 물가 변동을 제거하지 않은 명목 매출액이다. |
| [Bureau of Labor Statistics CPI](https://www.bls.gov/news.release/archives/cpi_10142026.htm) | 2026-10-14 발표, 2026년 9월 | CPI-U는 계절조정 전월 대비 0.6%, 12개월 기준 3.7% 상승. 휘발유는 9.1% 올라 월간 전체 상승분의 절반을 넘게 설명. 식품·에너지를 제외한 지수는 월간 0.3%, 12개월 2.6% 상승. |
| [Bureau of Economic Analysis PCE](https://www.bea.gov/news/2026/personal-income-and-outlays-august-2026) | 2026-09-30 발표, 2026년 8월 | 명목 개인소비지출은 1,908억 달러(0.9%) 증가했고 개인저축률은 4.1%. 2026년 9월 자료는 발표 예정일이 자료 기준일 다음 날인 2026-10-29로 기록됨. |

이 자료들은 각 기관의 1차 자료다. 서로 다른 통계의 범위·시점이 다르므로 하나의 동일 지표를 독립적으로 재검증한 것으로 취급하지 않았다. 원문 링크는 실제로 확인했지만 문서별 재사용·인용 권리는 별도 검토가 끝나지 않아 모두 `unknown`으로 보존했다. 별도의 사람 검토에서 권리와 주장-근거 관계를 확인해야 한다.

## 원고와 Research Package

- 한국어 전체 원고: [P5-CODEX-009-article-ko.md](P5-CODEX-009-article-ko.md)
- Research Package: [P5-CODEX-009-research-package.json](P5-CODEX-009-research-package.json)
- 최종 Import 입력 r4: [P5-CODEX-009-content-import.json](P5-CODEX-009-content-import.json)
- 패키지 식별자: `P5-CODEX-009-RP-US-20261028-01`
- 최종 Import 식별자: `p5-codex-009-us-demand-ko-20261028-r4`
- 주장·근거 묶음: 8개 주장, 4개 공식 출처
- 현지화: 한국어 원고 한 편만 작성. 다른 언어 원고는 생성하지 않음.

원고는 명목 소매판매가 가격 변동을 제거하지 않는다는 한계를 리드에서 설명하고, Census 판매액과 BEA PCE의 범위·기준월 차이, Beige Book의 정성적 현장 자료 성격, CPI 헤드라인·근원·휘발유의 차이를 연결한다. 사실과 분석을 구분하며 매출 증가만으로 실질 구매량이나 모든 가구의 소비 여력을 단정하지 않는다. 투자 조언, 수익 전망, 확인되지 않은 시장가격은 넣지 않았다.

## Import 및 격리 DB 결과

Import는 `woori_blog_agent_test`의 `woori_test_app`으로 수행했다. 서버 주소는 로컬 루프백이었다. 이 계정의 운영 DB `woori_blog_agent` CONNECT 권한이 실제로 `false`임을 확인했다. 운영 DB에는 접속하거나 쓰지 않았고 Migration 043~048도 적용하지 않았다.

초기 원고와 수정 원고는 append-only Import 행 r1~r4로 남겼다. 이전 버전·검토·감사 기록을 삭제하거나 덮어쓰지 않았다. r1에서 기계 검사가 잡은 수치·날짜와 근거 범위 문제를 보완해 r2를 만들었고, r3에서 SEO 키워드 문자열의 인코딩 손상을 검사 결과로 발견했다. 올바른 한국어 SEO 키워드가 들어간 r4를 새 revision으로 Import했다. r4에서 새로 생성한 버전은 1개이며 콘텐츠 버전 테이블과 연결됐다.

2026-10-28 검증 종료 시 테스트 DB 집계는 원고 Import 30건, Import 버전 54건, 평가 38건, Mock 게시 19건, 다국어 요청 이벤트 51건이었다. 이는 이 Phase와 기존 격리 테스트가 추가한 보존성 기록을 포함한다. 운영 DB 집계는 변경하지 않았다.

## 품질·SEO·HTML 결과

r4의 결정론적 원고 검사 `machine_passed=true`다. 수치·날짜, 고유명사, URL 형식, 문단별 출처 표식 규칙은 통과했다. 이는 의미의 정확성이나 권리 승인을 뜻하지 않는다. 독립 출처 검증, 사람 검토, generation readiness, publish readiness는 계속 미완료/false다.

SEO 상태는 다음과 같다.

- `ready`: 제목 일치, 검색 설명 존재, 주요 검색어의 자연스러운 본문 사용, 소제목 구조, 출처 링크 존재
- `review`: 출처 공식성 기록, 사실 최신성/검토 시각, Blogger 검색 설명 수동 확인, 실제 Blogger 테마 SEO 확인, 사람 편집 검토
- `not_measured`: 자유 형식 검색 의도의 정량·분류 측정, 외부 링크 응답, 문장별 의미 근거 일치, 공개 글 중복 비교, 이미지 대체 텍스트(이미지 없음), Search Console 성과

검색 설명과 제목은 준비됐지만 Blogger API v3가 게시글 검색 설명을 직접 지원하는 것으로 가정하지 않았다. 테마·관리자 화면에서 추가 확인해야 한다. Search Console 실측치는 없다.

공통 Markdown→HTML 렌더러가 Markdown 제목을 게시 본문 H1으로 중복 출력하지 않으며, source ID 표식을 최종 HTML에서 제거하도록 수정했다. API에서 다시 생성한 HTML SHA-256은 `cf467f9b097efcae717e4f09dec422e2bdec1e5c0912b8bbe46698268b4a5209`였고, 재현 확인 결과와 일치했다. 게시 화면에서 제목은 한 번만 H1로 표시되고 본문에는 H2가 유지되며, source 표식은 노출되지 않았다.

## Dashboard 브라우저 검증

임시 격리 Dashboard/API는 13100/18100에서 실행했고, 실제 3100/8100 및 llama.cpp 11435는 사용하거나 재시작하지 않았다. Playwright는 다음을 확인했다.

- `P5-CODEX-009-real-article.spec.ts`: 데스크톱 1/1, 모바일 1/1 통과
- 실제 Import JSON 등록 및 동일 원고 재전송 중복 방지
- r4의 정확한 Import 행 선택, 상세·전문 및 평가 결과 표시
- 게시 HTML 미리보기 제목·H2·주요 수치, 내부 source 표식 비노출
- Manual 사람 검토 전 실제 원고의 Mock 게시 버튼 비활성
- 일본어·중국어 간체 현지화 요청 생성 및 취소. Provider가 없어 번역 원고는 생성하지 않음.
- 320px, 390px, 768px, 1280px 폭에서 가로 overflow 없음
- 테스트 요청은 루프백 외부로 나가지 않았고 콘솔 오류 없음
- `content-import-pipeline.spec.ts`: 데스크톱 1/1, 모바일 1/1 통과. 별도 synthetic fixture만 Fake Publisher `succeeded` 결과를 남김.

스크린샷은 [assets](assets/)에 8장 저장했다: 데스크톱·모바일 각 320, 390, 768, 1280px. 실제 원고 r4에는 Mock 게시 기록이 없으며, 일반 Mock 성공 결과는 synthetic fixture에서만 확인했다. 해당 기록의 `simulation_only=true`, 외부 네트워크 호출 0, 실제 블로그 변경 `false`였다.

## 결함 수정

- 제목을 게시용 미리보기 데이터에 전달하지 않아 빈 H1이 생기던 문제를 수정했다.
- 외부 Import 목록에서 같은 제목의 revision을 정확히 선택할 수 있게 content ID를 data attribute에 노출하고 E2E에서 ID로 선택했다.
- 증거 연결에 쓰는 `[source:…]` 표식이 최종 게시 HTML에 보이던 문제를 렌더러에서 제거하고 회귀 테스트를 추가했다.
- 검색 키워드 인코딩 손상과 잘못된 날짜·수치 근거 범위를 revision 결과로 보정했다. 기존 기록은 보존했다.

## 테스트, 안전 및 미완료 항목

`scripts/verify.ps1` 최종 실행 결과: Ruff 통과, mypy 38개 소스 통과, pytest 266개 통과, wheel 빌드 통과, Dashboard ESLint 통과, Next.js production build 통과, TypeScript 검사 통과, `git diff --check` 통과. 두 Playwright spec은 총 4/4 browser project 테스트를 통과했다.

실제 Blogger API 요청은 0건, 유료 AI/API 호출은 0건, 운영 DB 쓰기와 Migration은 0건, 실제 사람 검토 이벤트는 0건, 실제 원고의 Mock 게시 기록은 0건이다. `generation_ready=false`, `publish_ready=false`, Auto 모드 비활성 상태를 유지한다.

남은 조건:

1. Codex 실행 환경이 실제 모델 ID를 공개하지 않아 GPT-6 Luna 사용 여부는 독립 증명되지 않았다.
2. 사람 검토자가 네 원문과 주장 연결, 권리, 자연스러움 및 독자 가치를 직접 확인해야 한다.
3. SEO 의도 분류, 링크 응답, 공개 글 중복, Blogger 관리자 검색 설명, 실제 네 블로그 테마 호환성은 미측정/미확인이다.
4. 생성 Provider·현지화 Provider·ChatGPT 예약 작업 자동 전달은 연결하지 않았다.
5. 게시 준비와 실제 Blogger 게시 승인은 별도 단계다.

개발 중 주요 선택·수정·평가 내역은 이 문서, Import revision, 테스트 DB의 append-only 이벤트/버전 기록으로 추적한다.
