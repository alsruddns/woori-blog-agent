# P5-CODEX-011 외부 일정 작업 템플릿과 로컬 Import

## 현재 상태

이 문서는 사용자가 ChatGPT 데스크톱의 Work에서 직접 검토해 등록할 5개 작업의 초안이다. 여기서는 계정에 예약 작업을 만들거나 활성화하지 않았다. ChatGPT 예약 실행의 실계정 권한, 결과 파일 생성, 예약 ID, 실행 이력 접근은 로컬 코드에서 확인할 수 없다. 먼저 일회성 로컬 테스트를 성공시킨 뒤 사용자가 각 반복 작업을 등록해야 한다.

OpenAI 공식 문서는 데스크톱 Work가 허용된 계정에서 사용자가 연 로컬 폴더의 파일을 사용할 수 있고, 로컬 파일이 필요한 작업은 PC와 데스크톱 앱이 실행 중이어야 한다고 안내한다. 반면 ChatGPT Project 안의 예약 작업은 프로젝트에 업로드된 파일에 접근하지 못하며, 이 애플리케이션으로의 일반 webhook/API 전달은 문서화되어 있지 않다. 따라서 이 시스템의 연결은 **사용자 권한으로 허용한 로컬 폴더에 완성 JSON을 저장한 뒤, 별도 로컬 Import 명령이 기존 API로 전달하는 파일 handoff**다. 실제 예약 결과 생성은 검증 전까지 미확인이다.

## 로컬 파일 계약

- 파일 규격: [`woori-scheduled-content-import/1.0`](../schemas/woori-scheduled-content-import-1.0.schema.json)
- 기사 `item`은 기존 [`woori-content-import/1.0`](../schemas/woori-content-import-1.0.schema.json)을 그대로 사용한다.
- 예약 정보는 별도 `scheduled_origin`에 둔다. task ID와 실행 ID는 제공자가 검증한 값이 아니라 자기 보고 메타데이터로 감사된다.
- 평가 결과를 파일에서 신뢰하지 않는다. Import는 `awaiting_human_review`, `generation_ready=false`, `publish_ready=false`다.
- 파일은 프로젝트의 `.local/gpt-scheduled-import/ready/` 아래에 `*.ready.json` 이름으로만 둔다. 먼저 `.part` 파일에 완성한 뒤 같은 디렉터리에서 원자적으로 `.ready.json`으로 바꾼다. 불완전 파일은 처리하지 않는다.
- 수신 명령은 한 번에 최대 4개 파일을 처리한다. 실패 파일은 `failed/`, 형식 오류는 `quarantine/`, 완료 파일은 `processed/`에 이동한다. 중단된 `processing/` 파일은 다음 실행 때 다시 대기열에 둔다.
- 수신기는 기존 Import API에 전달한 뒤, 예약 출처 감사 이벤트를 남기고 현재 기계 품질·SEO·HTML 평가를 한 번 실행한다. 이 평가는 출처 원문·주장 의미·권리의 독립 검증이 아니다.
- API 연결은 루프백만 허용한다. 기본 대상은 테스트 API `127.0.0.1:18100`이다. 운영 API `127.0.0.1:8100` 대상은 `--operations --confirm-operations-import`를 모두 명시해야 한다.
- Import와 예약 provenance 감사는 기존 API에서 각각 멱등 처리한다. API 장애 후 재실행해도 같은 콘텐츠는 중복 생성되지 않는다. 실제 Blogger 작업은 호출하지 않는다.

테스트 환경 명령:

```powershell
.venv/Scripts/python.exe scripts/import-scheduled-content.py
```

운영 API로의 Import는 운영 DB에 미검토 원고를 쓰므로 별도 운영 절차 승인 전 실행하지 않는다. 이 명령은 게시 작업이 아니지만 운영 콘텐츠 수신 데이터는 추가한다.

## 공통 작성 지침

아래 작업은 주제 검색부터 해당 목표 언어로 독립 작성한다. 다른 언어 기사를 번역하지 않는다. 시장 날짜와 원천 발표일을 분리한다. 지수 종가·변동률·기업 실적은 공식 거래소·기업 공시·정부 자료 또는 재배포 권리가 확인된 자료에서 대조한다. Google Trends 급상승은 검색량 순위가 아니다. 출처 수나 글 길이를 채우기 위해 근거 없는 주장을 추가하지 않는다. 거래소 휴장·조기 폐장·데이터 지연을 확인하고 해당 세션이 없거나 자료가 부족하면 파일을 만들지 않는다.

각 작업은 `woori-scheduled-content-import/1.0` 한 건 또는 주간 작업의 경우 적격 기사별 파일을 만든다. `content_id`는 안정적으로, `event_group_id`는 사건별로 지정한다. `occurrence_id`는 실제 작업 이름·시장일·기사 순번에서 결정론적으로 만든다. `task_id`에는 아래의 안정적인 task code를 쓴다. ChatGPT UI의 내부 ID가 확인되지 않으면 이를 내부 task ID라고 주장하지 않는다. `model_name`은 실제 UI에서 확인된 경우에만 기록한다. 주장별 출처·근거가 부족하면 Import 파일을 저장하지 않는다.

저장 파일은 최상위에 `schema_version`, `submitted_by`, 기존 v1.0 `item`, `scheduled_origin`을 둔다. `item.generation_method`는 `chatgpt_scheduled_export`여야 한다. `scheduled_origin`에는 task code, 고유 occurrence ID, 실행 시각, (시장 보고서라면) 시장 날짜, 실제 대상 언어, 등록된 Blogger의 숫자 ID·URL, 자료 기준 시각을 기록한다. task code와 occurrence는 자기 보고이므로 존재하지 않는 내부 task ID를 만들지 않는다. 실제 Blogger 대상이 등록 DB와 맞지 않으면 API가 거부한다. 기계 검사 결과를 파일에서 성공이라고 선언하거나 사람이 검증한 것처럼 꾸미지 않는다.

수신 디렉터리와 파일 쓰기 권한을 ChatGPT Work에 명시적으로 허용한 뒤, 다음과 같이 완성 파일을 임시 확장자로 쓴 후 원자적으로 이름을 바꾸라고 지시한다.

```text
<content-id>.part  ->  <content-id>.ready.json
```

시스템이 이 경로에 실제 파일을 만들 수 있는지는 아직 검증되지 않았다. 파일 생성 자체가 지원되지 않으면 화면 결과를 사람이 JSON으로 내보내고 `/imports`를 사용한다.

파일을 쓰기 전에 사용자에게 확인을 요구하지 말고, **파일 생성은 게시 승인이 아니며** Import 결과는 사람 검토 대기다. 공개 게시·초안 생성·수정·삭제·Auto 활성화는 이 경로에서 수행하지 않는다.

## 예약 작업 5개 초안

| Task code | 실행 희망 시각 | 결과 언어·블로그 | 휴장/세션 처리 |
|---|---|---|---|
| `market-close-kr` | 거래일 16:30 KST | ko | 한국 거래소 공식 달력과 조기 폐장 확인 |
| `market-close-jp` | 거래일 16:30 KST | ja | 일본 거래소 공식 달력과 조기 폐장 확인 |
| `market-close-cn` | 거래일 17:00 KST | zh-CN | 상하이·선전 세션 및 중국 공휴일 확인 |
| `market-close-us` | 매일 08:30 KST, 직전 미국 거래 세션 대상 | en | 미국 동부시간, 서머타임, 휴장·조기 폐장 확인 |
| `weekly-finance` | 매주 금요일 17:30 KST | 주제별 관련 언어 | Fed·SEC 등 공식 발표일과 자료 최신성 확인 |

이는 권장 실행 창이지 거래소의 공식 일정 피드가 아니다. 계정 UI가 지정 시각 또는 반복 규칙을 제공하지 않으면 작업을 등록하지 말고 그 한계를 기록한다. 일정은 해당 거래일에만 보고서를 내도록 지시하며, 종가를 확인할 수 없으면 숫자를 추정하지 않는다.

### 1 — 한국 주식시장 마감

**Task code:** `market-close-kr` · **희망 시각:** 평일 16:30 Asia/Seoul · **언어/블로그:** 한국어 / 등록된 ko 블로그

한국 거래일의 KOSPI·KOSDAQ 종가와 등락률, 주요 업종 흐름 및 해당일의 설명 가능한 촉매를 조사한다. 한국거래소 등 공식 1차 자료와 독립적인 신뢰 자료를 대조한다. 거래가 없었거나 확정 종가가 확인되지 않으면 결과 파일을 만들지 않는다. 단순 지수 나열 대신 확인된 사실, 의미, 투자자·기업 독자의 시사점을 구분한 분석 칼럼을 작성한다. 매매 추천이나 미확인 인과관계를 쓰지 않는다.

### 2 — 일본 주식시장 마감

**Task code:** `market-close-jp` · **희망 시각:** 평일 16:30 Asia/Seoul · **언어/블로그:** 일본어 / 등록된 ja 블로그

직전 일본 거래 세션의 TOPIX·Nikkei 주요 지수, 업종·종목 흐름과 확인 가능한 배경을 조사한다. 일본 거래일과 발표 기준 시각을 표시하고 공식 거래소·기업 자료를 우선한다. 일본 독자를 위해 제도와 시장 배경을 자연스러운 일본어로 설명하되, 한국어 원고의 번역본은 만들지 않는다. 휴장·조기 폐장·데이터 미확정 시 추정하지 않고 파일을 만들지 않는다.

### 3 — 중국 주식시장 마감

**Task code:** `market-close-cn` · **희망 시각:** 평일 17:00 Asia/Seoul · **언어/블로그:** 중국어 간체 / 등록된 zh-CN 블로그

직전 상하이·선전 거래 세션의 공인 지수 및 업종·정책·기업 이슈를 조사한다. 중국 거래소·정부·기업의 공식 자료와 원문 시각을 구분한다. 대만·홍콩·싱가포르 자료를 자동으로 중국 본토 독자와 관련 있다고 간주하지 않는다. 중국어 간체 독자에게 주제가 직접 관련될 때만 작성한다. 세션 데이터나 권리 조건을 확인하지 못하면 게시 후보 파일을 만들지 않는다.

### 4 — 미국 주식시장 마감

**Task code:** `market-close-us` · **희망 시각:** 매일 08:30 Asia/Seoul · **언어/블로그:** 영어 / 등록된 en 블로그

가장 최근에 완료된 미국 거래 세션을 식별하고, 날짜를 미국 동부시간으로 표시한다. DST를 감안해 이 KST 실행 시각이 직전 세션 종료 후인지 확인한다. S&P 500·Nasdaq·Dow 지수, 주요 업종·기업·경제지표 자료를 공식 거래소·기업·정부 자료 중심으로 대조한다. 휴장일에는 지난 세션을 명확히 지정하고 오래된 자료를 당일 자료처럼 표현하지 않는다. 독립적으로 작성한 자연스러운 영어 분석을 만든다. 숫자와 촉매를 확인하지 못하면 파일을 만들지 않는다.

### 5 — 주간 금융자료 분석

**Task code:** `weekly-finance` · **희망 시각:** 금요일 17:30 Asia/Seoul · **언어/블로그:** 주제의 독자 관련성에 가장 맞는 단일 언어를 우선

해당 주간 Fed·SEC 등 정부·규제기관 공식 발표를 검토하고, 검색 유입만을 위해 주제를 만들지 않는다. 독자 가치, 새로움, 출처 권리, 중복 가능성을 기준으로 1~3개 주제를 고른다. 각 원고는 대상 독자의 언어로 독립 작성하며, 여러 언어로 확장할 이유가 별도 입증되지 않으면 한 사건을 기계적으로 복제하지 않는다. 근거가 불충분하거나 이미 다룬 주제이면 해당 원고를 생략한다. 시장별로 선택한 언어·등록 Blog ID·URL을 `scheduled_origin`에 기록한다.

## 선행 확인 및 운영 중지

1. 사용자가 ChatGPT 데스크톱 Work에서 로컬 폴더 권한을 직접 허용하고 일회성 예약 산출물 쓰기를 확인한다.
2. 각 작업이 스키마 유효 JSON을 원자적으로 저장하는지 확인한다. 시스템이 task ID나 실행 식별자를 보여주지 않으면 이를 검증된 값으로 기록하지 않는다.
3. `.local/gpt-scheduled-import/ready`의 내용을 API로 보내기 전에 사람이 검토한다. 테스트 API로 먼저 수신과 멱등성을 검증한다.
4. GPT 예약 작업은 원고의 사실성·출처 권리나 Blogger 게시 허가를 증명하지 않는다.
5. 실제 Blogger Auto는 현재 비활성/차단 상태다. 코드의 Auto 선호값을 저장하는 것만으로 실게시를 켤 수 없다. 운영 migration, 실제 Blogger 쓰기, Auto 첫 실행은 별도 승인과 백업·복원·멱등성·긴급 중지·공개 HTML 검증을 모두 갖춘 후에만 별도로 진행한다.

참고: [Scheduled tasks in ChatGPT](https://help.openai.com/en/articles/10291617-scheduled-tasks-in-chatgpt), [ChatGPT Work and Codex](https://help.openai.com/en/articles/20001275-chatgpt-work-and-codex), [Set up scheduled tasks](https://developers.openai.com/training/walkthroughs/scheduled-tasks).
