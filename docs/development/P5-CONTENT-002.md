# P5-CONTENT-002 — 실제 근거 확보 및 Research Package 완성

- 작업 일시: 2026-10-28 (KST)
- 브랜치: `develop`
- 개발 목적: 기존 Google Trends 관측값에서 특정 사건성 주제를 골라 공식 원문·사실 근거를 연결하고, 후속 Qwen3/NVIDIA Build 평가가 공유할 수 있는 버전 관리 Research Package를 생성한다.
- 운영 DB 변경: 없음. 기존 운영 DB를 읽기 전용으로 확인했으며 schema 34, `content_versions` 360, `audit_events` 1,422였다. 운영 스키마에는 트렌드 테이블이 없고 운영 마이그레이션은 실행하지 않았다.
- 시험 DB: `woori_blog_agent_test`, 로컬 loopback, `woori_test_app`; schema 40. 테스트 계정으로 운영 DB에 접속할 수 없음을 검증했다.

## 최초 상태와 근거 선택

P5-CONTENT-001에서 저장된 6개 지역 Google Trends 관측값 60건을 다시 확인했다. 이 중 대만 관측 `國 軍 加 薪` (표시용 공백을 제거한 매칭 키 `國軍加薪`)을 후보로 사용했다. 원천은 `source_rank` 및 검색어 언어를 제공하지 않았으므로 각각 `null`과 `und`로 유지한다. 원천 트래픽 표시는 검색량이나 순위로 해석하지 않는다. 해당 기존 주제의 초기 자동 점수는 58.79였고 선정 판정은 보류였다. 점수 기준은 낮추지 않았다.

## 구현

- 고정된 대만 행정원·입법원 원문 URL만 받는 `taiwan_official_documents` outbound provider를 추가했다. HTTPS/host/method/path allowlist, robots.txt 확인, 기관 재사용 고지 확인, 1 MiB/20초 응답 제한, redirect·재시도 없음, 8회/분·8회/rolling-hour 제한을 적용한다.
- rolling-hour 상한은 process 메모리 한도 외에 advisory lock으로 동기화한 append-only `external.call.started` 감사 기록을 확인하고 예약한다. 재시작으로 호출량 한도를 초기화하지 못한다.
- 각 수집 실행에 UUID run ID를 부여하고 외부 요청 시작/완료, 개별 출처 저장, 실패/완료 이벤트 및 Research Package 감사 이벤트에 연결한다.
- 실제 HTML에서 숨김 실행·내비게이션 블록을 제외하고 원문에 그대로 존재하는 문장만 사실 발췌로 저장한다. source body와 robots 응답은 SHA-256으로 연결한다. ROC 날짜는 원문은 그대로 보존하고 날짜 값으로만 변환한다.
- 각 문서 저장은 출처 revision, 자동 출처 provenance screen, immutable fact registry, trend-topic link 및 audit에 연결한다. 자동 provenance screen을 편집·의미·출처 독립성의 사람 승인으로 간주하지 않는다.
- Research Package에는 관측 원문/지역/시각, 실제 선정 신호·판정 사유, exact source spans, 수치·날짜·entity IDs, 출처·이용권 조건, 배경, 시간순 사실, 미확인 사항, 금지 주장 및 권장 개요를 보관한다. 기계상 근거 수집 상태를 기존 편집·게시 승인과 분리하기 위해 Migration 040을 추가했다. 운영 DB에는 적용하지 않았다.
- `/sources`의 기존 상세 화면은 패키지 상태를 한국어로 표시한다. 근거 수집 상태가 게시 또는 원고 생성 준비 승인을 뜻하지 않는다는 안내를 추가했다.
- Qwen3 로컬과 NVIDIA Build 평가용은 동일한 package payload를 입력 자료로 공유하도록 구성했다. NVIDIA Build 호출, Gemini, 유료 inference 및 실제 Blogger 쓰기는 수행하지 않았다.

## 실제 출처 조사와 1차 시도

후보 출처는 행정원의 군공교 처우 계획, 추가예산안 보도자료, 입법원 예산센터 평가 보고서다. 행정원 두 URL은 동일 기관 출처 그룹으로만 계산하고, 입법원은 다른 기관의 별도 검토 자료다. 기관이 다르더라도 출처 독립성은 사람 검토 전까지 자동 승인하지 않는다.

첫 실제 수집에서는 robots 및 두 기관 이용조건, 문서 URL에 대한 총 7회 요청이 허용 목록을 통과했고 모두 HTTP 200을 반환했다. 두 행정원 문서의 필수 근거 표식은 검증됐으나, 입법원 자료의 내용은 같은 문장이 아니라 별도 평가 항목에 걸쳐 있었다. 첫 구현이 복수 표식을 한 문장에 요구해 `required_source_fact_span_not_found`로 중단했다. 당시에는 출처·사실 저장이 없었으며, 실패 원인과 요청 수는 시험 DB append-only 감사로 기록했다. 이 시도 때문에 해당 provider의 rolling-hour 한도는 7/8을 소비했다.

후속 실행은 이용량 한도가 다시 허용된 시점 이후에만 한다. 수정한 추출기는 각 사실 항목을 독립적인 exact source span으로 확인하며, 수집 성공 출처는 개별 트랜잭션으로 저장해 이후 항목 실패가 이미 읽은 근거를 버리지 않게 한다. 실행 전에 quota와 테스트 DB 연결을 다시 확인한다.

## 데이터·안전 상태

- 최초 조사 기준 시험 DB에는 관측 60, 주제 60, 연구 출처 0, 사실 0, 패키지 1이 있었다. Migration 040 검증으로 감사 이벤트가 1건 추가됐다.
- 별도 테스트 실행이 아닌 실제 문서 수집은 공통 outbound gate를 통해서만 요청한다. API key/비밀값은 로그나 payload에 포함하지 않는다.
- Blogger API 요청 0건, AI API/inference 호출 0건, 운영 DB 쓰기 및 운영 마이그레이션 0건.
- `generation_ready=false`, `publish_ready=false`, 사람의 편집·독립 출처 승인 미완료 상태를 유지한다.

## 검증과 남은 단계

- `scripts/provision-test-database.py`: schema 40 적용 확인 및 test app의 운영 DB `CONNECT` 거부 확인.
- 집중 회귀 테스트: 13 passed. 전체 `scripts/verify.ps1`: 228 pytest 통과, Ruff, mypy, Python wheel, Dashboard ESLint, Next.js production build, TypeScript, `git diff --check` 통과.
- 실제 원문 수집 이후 패키지 출처·사실 수·score/decision·기계 보류 사유를 `docs/development/P5-CONTENT-002-results.json`에 남기고, 비용 0원/쿼터·DB 격리 확인을 다시 기록한다.
- 사람이 확인할 항목: 출처 권리 예외, 기관 간 독립성, 정책 해석, 검색 신호와 사건의 의미적 연결, 독자 가치 및 문장 단위 사실 적합성.
- 커밋 해시 및 원격 푸시는 최종 기록에 기입한다.

출처 상세에는 review actor와 사유도 함께 전달한다. collector 계정의 자동 provenance screen은 UI에서 사람 검토 승인으로 표시하지 않고, 자동 확인과 의미·권리 사람 검토 대기를 구별한다. 주제 그룹의 사건 동일성, 출처 독립성, 지역별 재사용 예외와 분석 문장은 계속 사람 검토 대상으로 남는다.

## 실제 수집 및 완성 결과

2026-10-28 11:05 KST에 1차 실패 이후 rolling-hour 호출 창이 만료된 것을 시험 DB 감사기록에서 확인한 다음, 격리된 `woori_blog_agent_test` (`woori_test_app`, loopback, schema 40)에서 인증된 `POST /admin/research/topics/{topic_id}/discover-official-sources`를 한 번 실행했다. `國 軍 加 薪` 대만 Google Trends 관측값에 대해 행정원 2개 문서와 입법원 예산센터 1개 문서를 실제 읽고, 관련 정확한 원문 구간 8개를 `source_span_verified` 사실 원장에 연결했다. 총 문서·robots·이용조건 확인 요청 7회가 HTTP 200을 반환했다. 총 호출 창 안의 첫 수정 전 시도 7회도 HTTP 200이었지만 입법원 항목 경계 검사 오탐으로 중단되어 저장되지 않았다. 원인 수정을 후 실제 결과가 생성됐다.

Research Package는 ID `de118f17-ab50-46b7-b99f-4aba51f240ce`, version 1, 상태 `evidence_collected_pending_human_review`, 사실 8건, 출처 3건으로 저장됐다. 독립 출처 수는 사람의 비교 검토 전이라 0이다. 점수 기준을 바꾸지 않았으며, 현재 주제 판정은 `held`다. `generation_ready=false`, `publish_ready=false`를 유지한다. 원천 라벨 `10000+`는 원천 제공 표시로만 보관했고 순위·검색량으로 재해석하지 않았다. 주제 점수의 관심 신호는 라벨 존재 여부만 반영한다.

자료에서 확인한 범위는 군공교 직원 처우안의 전문·직무 가산금 각 NT$2,000 및 4% 조정안, 2026-07-01로 앞당겨 제안된 가산금 적용일, 추가예산안 NT$607.6 billion 규모 및 입법원 심의 회부, 입법원 보고서의 예산 절차와 객관적 처우 조정 기준 관련 검토다. 9.98%~5.88% 수치는 행정원 문서에서 일반 행정직 예시로 한정되므로 군 처우 수치로 사용하지 않도록 금지 주장에 포함했다. 행정원은 한 기관 출처 그룹의 문서 두 건이고 입법원은 별도 기관이지만, 두 기관 자료의 독립성은 아직 사람 검토로 승인하지 않았다.

출처 재사용 고지는 robots.txt와 함께 실제 조회했고 원문 URL·출처명·발행일(원문이 날짜만 제공한 경우 시각은 미확인)·수집시각·응답 본문 및 robots 해시·접근정책·사실 근거가 DB 및 결과 JSON에 연결됐다. 제3자·특별 제한 자료 여부와 실제 이용 범위는 여전히 사람 검토 항목이다.

## Dashboard/API 및 검증

FastAPI TestClient에서 격리 DB 연결을 다시 확인하고 TW 목록 HTTP 200 (10개 관측값)과 대상 상세 HTTP 200을 받았다. 상세 결과에는 출처 3건, 사실 8건, 패키지 상태, 자동 provenance 검토자와 사유가 함께 노출되며 기계 자동 확인과 사람 검토를 구분한다. 임시 백그라운드 서버를 이용한 브라우저 검증은 자동 실행 정책에 의해 차단되어 수행하지 않았다. 이를 브라우저 E2E 완료로 보고하지 않는다.

최종 `scripts/verify.ps1`: pytest 229 passed, Ruff 통과, mypy 32개 파일 통과, Python wheel 통과, Dashboard ESLint 통과, Next.js production build 통과, TypeScript 통과, `git diff --check` 통과. 추가 집중 회귀 테스트 18 passed. 실제 브라우저 HTTP 비밀정보 검사도 실행하지 않았다. 환경 비밀정보 값은 출력하지 않았으며, 전체 테스트에 포함된 비밀정보 처리·비용 차단 회귀 검사를 통과했다.

## 운영 및 미완료

운영 DB는 migration 34, 콘텐츠 버전 360, 감사 이벤트 1,422, 트렌드 스키마 없음으로 최종 재확인했고, 테스트·운영 데이터 접속을 분리했다. 운영 DB 마이그레이션·쓰기 없음. 운영 Blogger API 호출은 이번 작업 시각 이후 0건이며, 운영 DB의 역사적 Blogger call log 152건은 보존되어 있다. 시험 DB Blogger call log 0건. AI inference, 유료 API, Blogger 쓰기 0건이다.

남은 검토: (1) 트렌드 신호가 해당 사건을 의미하는지, (2) 기관 간 독립성·사실 맥락, (3) 재사용 고지의 제3자 저작물 예외, (4) 처우·예산 문장의 정책적 맥락, (5) 독자에게 제공할 실질적 분석 가치. 이 검토가 끝날 때까지 원고 작성·발행 준비는 보류한다. 추가 자동 원문 탐색은 provider rolling-hour cap 8회를 유지하므로 한도 만료 전에는 실행하지 않는다.

세부 응답·근거·검사 결과: `docs/development/P5-CONTENT-002-results.json`.

## Git 완료

- 구현·검증 커밋: `03f0cc3bbd5488af9cb67ffb86d65d8703861023` (`Add : [Research] Capture official source facts and packages`)
- 원격 반영: `origin/develop` 푸시 성공 (`18e7d25` → `03f0cc3`).
- `main` 미변경. 미추적 `.playwright-mcp/`는 사용자 자료로 보존하고 커밋에서 제외했다.
