# P5-CODEX-088 — Google Trends country authoring and Research Worker Import

- 작업 일시: 2026-10-31 (KST)
- 브랜치 / 기준 커밋: `develop` / `c9c370a9cca6e635243fda7db7005534dcfe9cb8`
- 목적: 087의 최신 Trends 회차에서 국가별 검색량 순위 후보를 기존 `google_trends` Codex Runner로 전달하고, JSON 검증 및 Research Worker Import까지 연결한다.
- 범위 제외: Trends 자동 발행 정책, Publishing Job 생성, Publication Worker 수정, Blogger 공개 게시, 예약 자동화 변경.

## 변경 및 현재 상태

- schema 66의 기존 `trend_blog_geo_authoring` 매핑과 국가 순위 큐를 재사용했다. 단일 Blogger에 여러 수집 지역을 연결할 수 있고, 처리 순서는 회차마다 순환한다. 실제 DB 기본 매핑은 Trend KO `KR`, Trend Journal EN `US`, Trend JA `JP`다. Trend ZH는 운영 블로그가 `zh-CN/CN`이지만 수집 지역 allowlist에 `CN`이 없어 임의 매핑하지 않았다. 추가 영어권·중문 지역은 운영자가 기존 Dashboard에서 명시적으로 설정해야 한다.
- 최신 10분 슬롯만 선택하고 국가별 검색량 하한 내림차순, 시작 시각 내림차순으로 후보를 정렬한다. 다른 국가의 검색량은 비교하지 않는다. 실패한 상위 후보는 재요청 대상에서 제외해 같은 회차의 다음 후보를 검토할 수 있게 했다.
- 기존 공식 Codex CLI, ChatGPT 로그인, 제한된 동시 실행, `google_trends` Job, `codex_trends_export` provenance, Pydantic Import 및 기존 원고 버전 경로를 재사용한다. Import된 claim은 `unverified`이며 이 작업에서 게시 Job을 만들지 않는다.
- 첫 두 실제 Codex 실행은 웹 검색 2회씩 수행했지만 모델이 충분한 근거를 찾지 못했다고 응답했다. 당시 출력 계약이 완성 기사만 허용해 다음 두 설명문이 실제 Import되었다. 이 데이터는 기존 불변 이력으로 보존하며 정상 기사나 품질 승인으로 취급하지 않는다.
  - KR `박현경`: Job `762db935-cc6b-40e1-bf20-14afe6f1887e`; Import `4e453392-beb9-47bb-b741-e2ae195aea0f`; Version `fbae38ff-5d0d-479e-bc95-0e5749d29623`.
  - US `brett yormark`: Job `cb40f701-cae0-4744-bcbd-2819895ae9ab`; Import `b6b479af-0fc5-4529-95a4-4af6adf3ce25`; Version `b5a3ba25-448e-4a66-ad1c-1986a1d06af4`.
- 00:20 KST 일본 `トグルホールディングス` 작업은 4회 웹 검색 후 상장 자료와 수치가 연결된 일본어 원고를 생성해 Import했다. Job `096689da-f1a4-46a1-8dbe-142cb8cf01e6`; Import `b0f2a399-4b6a-4fc3-9181-84040ad87aad`; Version `a9128097-507f-4272-bfa4-b4dba13a5ef5`. Content Version 1, 본문 1,673자, 7 claims, 4 sources다. 모든 claim은 `unverified`이며 사람의 사실·의미·권리 검토 전 초안이다. Codex가 검색 관심 상승 원인을 확정하지 않았고 본문에서도 불확실성을 구분한다. 게시 적격 또는 승인으로 취급하지 않는다.
- 후속 수정에서 Trends 실행 결과를 `article` 또는 `insufficient_evidence` envelope로 구분했다. 근거 부족 응답은 Import 파일 생성 전에 실패 상태와 사유로 기록되며, 다음 순위 후보 검토가 가능하다. 국가 원문과 Blogger 대상 국가를 프롬프트에서 구분해 명시한다.
- 00:20 KST 최신 회차도 11/11 지역 수집 성공이다. KR/US의 앞선 00:10 요청은 재사용하지 않았으며 JP 신규 후보 작업이 완료됐다. Codex 동시 실행은 1개였다.

## 데이터 및 보호

- 기존 schema 66을 유지했다. 이번 후속 결과-envelope 수정에는 추가 migration이 없다.
- 기존 `backups/20261030T150629Z.dump`는 schema 66 적용 직전 검증된 백업이며, 원고·Job·감사 데이터는 삭제하거나 덮어쓰지 않았다.
- 확인 시 Publishing Job은 기존 14건이며 이번 Trends 작업은 Job을 추가하지 않았다. Blogger 공개 POST는 수행하지 않았다.
- Trends 자동화는 유료 API fallback을 사용하지 않는다. 사전 확인에서 Codex CLI ChatGPT 인증, `gpt-6-luna`, API-key fallback 비활성, billable credential 이름 0건이었다.

## 검증

- 운영 read-only: 00:00, 00:10, 00:20 KST 슬롯 각각 11개 지역의 성공 기록 확인.
- 격리 DB 집중 테스트: `test_trend_editorial.py`, `test_keyword_authoring.py`, `test_content_imports.py` — 45 passed.
- 변경 모듈 Ruff 및 mypy 통과.
- 격리 refusal 테스트는 Import ID, Content Version, ready 파일, Publishing Job이 생성되지 않고 `insufficient_evidence`로 끝나는 것을 확인한다.
- Dashboard의 블로그-지역 매핑 UI는 기존 빌드 디렉터리 불일치가 발견되어 최신 격리 production build 반영 및 실제 브라우저 재확인이 필요하다.

## Git 및 런타임

- 1차 구현 커밋: `64a6d44e825b5ea4a4826a6fc89a6e22a3522a77` (`feat : [Trends Authoring] Connect country-ranked topics to Codex Import`).
- 근거 부족 응답 분리 및 다음 순위 후보 복구의 후속 커밋은 이 문서의 후속 기록 또는 `git log`에서 확인한다.
- API/Dashboard/Research Worker는 1차 커밋을 반영한 상태다. Publisher는 기존 PID `51580`으로 유지했고 재시작하지 않았다. 후속 코드를 반영할 때 활성 Codex Job 완료 후 해당 API/Dashboard/Research Worker만 안전하게 재시작한다.
- Dashboard의 기존 `.runtime/validated-source.json`은 1차 커밋 당시 구 빌드 디렉터리를 가리켜 실제 localhost 브라우저가 매핑 UI 이전 빌드를 서빙했다. 후속 production build와 marker 갱신 및 desktop/mobile 확인 전까지 UI 런타임 검증은 미완료다.

## 남은 항목

- 확인된 실제 Import는 3건이며 첫 2건은 근거 부족 설명문, 세 번째 JP 건은 검토 대기 원고다. 새 `insufficient_evidence` result-envelope 경로는 격리 테스트에서 검증했으며, 새 코드로 실행된 운영 Codex 결과는 아직 없다.
- Dashboard 브라우저에서 실제 다중 지역 매핑 UI를 데스크톱 및 390px에서 확인한다.
- 후속 커밋/푸시와 적용된 런타임 commit을 마지막에 기록한다.
