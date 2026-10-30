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
- 00:20 KST 일본 원고 작업은 앞선 회차의 KR/US 요청을 재사용하지 않고 완료됐다. Codex 동시 실행은 1개였다.

## 데이터 및 보호

- 기존 schema 66을 유지했다. 이번 후속 결과-envelope 수정에는 추가 migration이 없다.
- 기존 `backups/20261030T150629Z.dump`는 schema 66 적용 직전 검증된 백업이며, 원고·Job·감사 데이터는 삭제하거나 덮어쓰지 않았다.
- 확인 시 Publishing Job은 기존 14건이며 이번 Trends 작업은 Job을 추가하지 않았다. Blogger 공개 POST는 수행하지 않았다.
- Trends 자동화는 유료 API fallback을 사용하지 않는다. 사전 확인에서 Codex CLI ChatGPT 인증, `gpt-6-luna`, API-key fallback 비활성, billable credential 이름 0건이었다.

## 검증

- 운영 read-only: 00:00, 00:10, 00:20, 00:30, 00:40 KST 슬롯 각각 11개 지역의 성공 기록 확인. 00:40 슬롯에서 연결된 지역의 상위 후보는 최신 editorial state가 `review_candidate/insufficient_context`였고 내부 분류도 확정되지 않아 Codex Job을 만들지 않았다.
- 격리 DB 집중 테스트: `test_trend_editorial.py`, `test_keyword_authoring.py`, `test_content_imports.py` — 45 passed.
- 변경 모듈 Ruff 및 mypy 통과.
- 격리 refusal 테스트는 Import ID, Content Version, ready 파일, Publishing Job이 생성되지 않고 `insufficient_evidence`로 끝나는 것을 확인한다.
- Dashboard ESLint 대상 2개 파일 통과, 격리 Production Build `.next-p5-a9beb1f` 성공.
- 실제 localhost 브라우저에서 수집 설정 10분, 전체 11개 지역 안내, Blogger-지역 다중 매핑 UI를 확인했다. 390 CSS px에서 `scrollWidth=390`으로 가로 넘침이 없었다. 원고 관리의 가져온 원고 탭에서 일본어 Import 제목을 확인했고, 제목을 눌러 `/imports` 상세 시트에서 Version 1, 사람 검토 대기, 일본어 제목·본문을 확인했다.
- 기본 원고 목록의 evaluation-manuscript API는 HTTP 503 `Evaluation manuscript list is unavailable`를 반환했지만, 별도 가져온 원고 탭의 content-imports API는 HTTP 200이며 해당 Trends Import를 표시했다. 이는 운영 evaluation 목록 경로의 별도 문제이므로 이번 범위에서 수정하지 않았다. 브라우저 콘솔의 favicon 404도 별도 기존 리소스 오류로 남았다.

## Git 및 런타임

- 1차 구현 커밋: `64a6d44e825b5ea4a4826a6fc89a6e22a3522a77` (`feat : [Trends Authoring] Connect country-ranked topics to Codex Import`).
- 근거 부족 응답 분리 및 다음 순위 후보 복구 커밋: `7d8471ff64396bf21dca10774a65dcc409c5c76c` (`fix : [Trends Authoring] Reject evidence-declined results before import`).
- 운영 안내 문구 정정 커밋: `a9beb1f` (`fix : [Trends UI] Clarify all-region collection per slot`).
- API와 Research Worker는 `7d8471f`, Dashboard는 `a9beb1f`의 코드를 실행한다. Dashboard validated build는 `.next-p5-a9beb1f`다. API health 200 및 Research Worker heartbeat fresh 확인. Publisher는 기존 PID `51580`, 모드 `scheduled-auto-and-manual`로 유지했고 재시작하지 않았다.
- 기존 validated-source가 오래된 빌드를 가리키던 문제는 atomic marker 갱신과 Dashboard 재시작으로 해결했다.

## 남은 항목

- 실제 Import 3건 중 KR/US 두 건은 근거 부족 설명문이고, JP 한 건은 출처·주장 연결이 있는 검토 대기 초안이다. 세 Import 모두 claim `unverified`; 사람 검토가 남아 있다.
- 새 result-envelope 경로는 격리 테스트까지 확인했지만 운영에서 새 거절 envelope를 반환하는 Codex 호출은 없었다. 00:30은 서비스 반영 구간이었고 00:40 후보들은 분류와 category 근거가 부족해 호출하지 않았다. 추가 모델 호출로 quota를 소진하거나 미분류 항목을 강제로 선정하지 않았다.
- 완료 범위: 실제 Trends Codex 원고 작성 및 Research Worker Import 1건, 앞선 두 근거 부족 결과의 보존, 추가 후보는 기준 미충족으로 보류. Imports는 품질 승인 상태가 아니다.
- 최신 로컬 커밋과 원격 푸시 결과는 후속 git 기록에서 확인한다.
