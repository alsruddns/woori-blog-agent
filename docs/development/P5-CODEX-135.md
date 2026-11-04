# P5-CODEX-135 — Google Trends 검색량 기준 작성 요청 보장

- 작업 일시: 2026-11-04 (Asia/Seoul)
- 브랜치: `develop`
- 시작 HEAD: `221b5aad43553a78627d872e024f7f176e75849a`
- 작업 시작 감사 이벤트: PostgreSQL `agent.work.started`, ID `352051`
- 목적: 설정된 Trends 검색량 하한을 넘는 현재 슬롯 후보가 일반 점수 분류에 묻히지 않고, 기존 중복·비용·시간당 실행 제한 아래 Codex 조사·작성 요청까지 전달되도록 보장한다.

## 실제 실패 추적

- P5-CODEX-125는 현재 코드에 구현되어 있었고, 해당 구현은 당시 migration 088 및 운영 반영으로 배포됐다. P5-CODEX-134가 확인한 후속 runtime commit `11853f175f46016e1f449f6c253fb0485155b16b`에도 P125 경로가 포함된다. 시작 시 API, Dashboard, Publication Worker 및 Research Worker heartbeat는 이 revision, Research Worker PID 33368 heartbeat는 fresh였다.
- 운영 schema는 P5-CODEX-134의 적용 기록상 90이다. 현 app DB role은 `schema_migrations` SELECT 권한이 없어 이번 작업에서 그 테이블을 직접 읽지 않았다. 운영 데이터와 설정 조회는 read-only였다.
- 자동 작성 검색량 하한은 5,000, automation controls revision은 22였다. 저장된 원본 `approx_traffic`은 `10000+`, 정규화 lower bound는 10,000이다. 해당 표시는 정확히 10,000건이라는 측정값이 아니라 원본 구간의 하한으로 취급한다.
- 관측: `78af214e-7038-4448-8ba2-cf070be1ce5c`; 수집 run/batch: `e56b4820-b092-44c3-b53a-dd400f7820ec`; 슬롯 2026-11-04 20:00 KST, 실제 수집 `20:00:23.104712+09` = `11:00:23.104712Z`.
- 평가: `54d254d1-9a3c-47ce-ad03-51391abf5010`, IN → Trend Journal EN (blog record `b9dc1202-8071-484a-a4f4-15d04e34a76c`) 활성 매핑이 적용됐다. 합계 65.25, news 25, analysis 15였고 최신 점수 이벤트는 `review_candidate/insufficient_context`였다. 매핑·점수·파싱이 작성 요청 미생성 원인은 아니었다.
- 같은 회차의 stage run `85d08b3a-1135-49fe-8203-b5e13d496848`는 `handoff_saved`로 끝났고 `queue.created=0`, `hourly_capacity=4`를 기록했다. 직전 19:00–20:00 KST 구간의 4개 Trends 요청이 설정된 시간당 작성 한도를 모두 사용했다. 당시 경로는 남은 capacity가 0이면 일반 점수 분류를 수행하고 종료해 임계값 후보의 작성 미실행 사유를 남기지 않았다. 생성 요청, Google Trends Codex job, Worker 처리, Import Receipt는 이 observation에 없었고, 20:30에는 이전 슬롯이 만료되어 재처리하지 않았다.
- 실제 원본 RSS 필드는 `<approx_traffic>10000+</approx_traffic>`였다. Google Trends 공식 도움말은 Trends 검색량을 선택 기간 내 구간화된 트래픽으로 설명한다. 따라서 숫자 변환은 비교용 하한만 반환한다. [Google Trends 도움말](https://support.google.com/trends/answer/3076011?hl=en-ca)

## 변경 사항

- `parse_approx_traffic`는 숫자 DB 값과 `10000`, `10K+`, `100K+`, comma, 기존 K/M/B 표기를 받아 비교 가능한 하한을 반환한다. null/미제공은 null로 남아 기존 일반 정책으로 흐른다.
- 현재 수집 슬롯에서 threshold 이상인 후보는 활성 geo/blog/language mapping 및 기존 duplicate 검사 후 일반 점수·news/analysis 점수와 독립적으로 요청한다. duplicate면 제외한다. 생성 요청은 `publication_authorized=false`이며 Blogger 발행 권한을 만들지 않는다.
- 기존 하드 시간당 Codex 한도는 유지한다. capacity가 없으면 `authoring_hourly_capacity_reached` 감사 상태로 보이고 중복 검사를 통과한 하한·슬롯·기준값을 저장한다. Research Worker는 같은 슬롯이 아직 유효할 때만 이를 재확인한다. 슬롯 종료 후 retry하지 않으며 과거 관측 회차를 재평가하지 않는다.
- 같은 요청이 이미 queued/working/imported/published면 다음 평가가 이를 duplicate로 재분류해 Worker가 건너뛰지 않도록 보호한다. 중복 제외 및 capacity 대기 사유를 Dashboard에 노출하고, job 실패에는 저장된 구체적 error code를 표시한다.
- P131/P133은 Desktop scheduled/manual Import handoff 및 Import Receipt를 위한 별도 provenance 경로다. Google Trends는 기존 `google_trends` Codex Runner → Research Worker 경로를 유지하며 publication queue/Publisher에 연결하지 않는다. Snapshot, 사실·출처 검증, Import 및 Receipt가 완료되지 않은 요청을 원고 성공으로 표시하지 않는다.
- 국가/blog 설정을 변경하지 않았다. 기존 활성 Blogger는 6개, `zh-CN` 활성은 0개, 활성 authoring geo mappings는 12개였다. 확인된 IN→EN mapping을 그대로 사용했다.

## 테스트 및 검증

- Trends editorial + parser 회귀: **75 passed** (`test_trend_editorial.py`, `test_trends.py`; 격리 basetemp, cache plugin off).
- 검증에는 threshold 10,000+/기준 5,000, news/analysis 점수와 무관한 경로, threshold 미만/null 일반 선정, `10K+`/숫자 파싱, 같은 슬롯 capacity wait/retry, 이전 슬롯 재처리 금지, 중복 및 queued request 보호, Codex dispatch/Import·실패 code와 Blogger write 0 확인이 포함된다.
- 첫 pytest 호출은 전체 assertion은 통과했지만 Windows의 기존 공용 `pytest-of-home` 정리 권한 오류로 process cleanup 단계에서 non-zero 종료했다. 저장소 내 격리 basetemp로 재실행했고 정상 종료 및 75 passed를 확인했다.
- 운영 데이터 재실행, 과거 수집 회차 수정, 테스트 Blogger 게시: 모두 0.
- 서비스 반영 전후 상태, applied revision, 다음 신규 슬롯 결과는 운영 반영 후 이 기록에 추가한다.

## 파일 및 상태

- 수정 파일: `services/api/woori/trends.py`, `services/api/woori/trend_editorial.py`, `services/api/woori/research_stages.py`, `services/api/tests/test_trends.py`, `services/api/tests/test_trend_editorial.py`, `apps/dashboard/app/sources/workspace.tsx`, 본 문서.
- 변경 전: high-volume P125 path는 존재했지만 capacity 0에 대한 사유/같은 슬롯 retry가 없어 후보가 일반 `review_candidate` 상태로 만료될 수 있었다. Worker 재평가에서 기존 queued request가 다시 duplicate로 분류될 수 있었다.
- 변경 후: 임계값 후보의 중복 검사·capacity 대기·현재 슬롯 재시도·Worker dispatch 상태를 명시적으로 유지한다. 일반 후보는 기존 점수 정책을 계속 이용한다.
- 시작 당시 tracked worktree는 clean이었으며, 기존 untracked 파일·stash·OAuth·예약 작업·게시 이력은 변경하거나 삭제하지 않았다.
- 최종 커밋, 푸시 결과, 실제 Worker 반영 및 신규 회차 검증 결과는 마감 후 아래에 연결한다.
- 남은 제한: P5-088의 기존 시간당 작성 상한은 유지된다. 상한이 수집 슬롯보다 오래 포화되면 해당 후보는 슬롯 내 대기 후 기존 만료 정책대로 종료될 수 있다. 이번 변경은 자동 과거 재처리를 금지한다. 다음 신규 슬롯에 적격 후보가 없으면 실데이터 자동 요청은 후속 회차에서 계속 관찰해야 한다.
