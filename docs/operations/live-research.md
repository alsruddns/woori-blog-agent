# 실제 수집·로컬 모델 운영

로컬 모델 API는 `.local/inference.key`의 프로젝트 전용 비밀키로 보호한다. 키 값은 프로세스 인수가 아닌 `--api-key-file`로 전달하며 로그·응답·Git에 포함하지 않는다. 시작 스크립트의 두 번째 선택 인수로 CPU threads(1–4), 세 번째 선택 인수로 `cpu` 또는 `vulkan` backend를 선택할 수 있다. 실행 중인 엔진과 DB 스레드 정책이 다르면 명확히 거부하므로 해당 프로젝트 엔진만 정상 재시작해야 한다.

확인일: 2026-10-26. 실제 무료 수집은 아래 두 공급자만 연결했다. GSC는 게시 후 성과 분석용이며 전체 웹 검색량으로 사용하지 않는다. 검색량·경쟁도·CPC는 계속 NULL/미수집이다.

| 공급자 | 실제 주소·범위 | 권리·상업적 이용 | 인증·비용·한도·갱신 |
| --- | --- | --- | --- |
| Federal Reserve Board | https://www.federalreserve.gov/feeds/press_all.xml 및 피드가 가리키는 공식 pressreleases HTML | [Disclaimer](https://www.federalreserve.gov/disclaimer.htm): 별도 표시 없는 Board 정보는 public domain, 출처 명시. 제3자 사진/자료는 제외. 공식 RSS 공개를 확인했다 | 키/과금 없음. 확인한 소개에 숫자 quota 없음. 앱 자체 1시간당 1작업·피드 최신 2건·요청 간격 1초·본문 응답 1MiB 상한. 보도자료 발생 시 갱신, 앱 기본 60분 |
| Wikidata | https://www.wikidata.org/w/api.php 의 wbsearchentities | [Licensing](https://www.wikidata.org/wiki/Wikidata:Licensing): 구조화 entity 데이터 CC0. 다른 namespace 문서는 CC BY-SA이므로 수집하지 않음 | 공개 읽기 인증/과금 없음. [API 정책](https://www.mediawiki.org/wiki/API:Etiquette)·User-Agent·maxlag=5 적용. 앱 자체 시간당 1작업·카테고리당 최대 1건·요청 간격 1초·응답 1MiB. 커뮤니티 갱신 시 변경 가능 |

금융 카테고리는 Fed 공식 보도자료로 실제 연결했다. 일곱 카테고리 모두 Wikidata 구조화 주제 후보를 수집하지만, K-pop 소속사 발표·화장품 효능·관광 시설 운영·식당 영업 정보까지 검증된 것은 아니다. 나머지 카테고리의 실제 공식 발표/운영 API 연결은 후속 과제다. Wikidata는 후보/근거 대기 상태로 저장하고 자동 사실 승인이나 자동 생성 대상으로 올리지 않는다.

Fed는 공식 feed/article 주소, 게시 시각, Board 본문 사용 조건을 확인해 출처를 자동 수용한다. 이 자동 검토는 전송 경로·자료 기준일·권리의 확인이며 의미적 사실 검증 완료가 아니다. 본문 `<div id="article">` 범위만 추출해 메뉴/정부 안내 문구를 제외한다. 원문 전체나 제3자 PDF를 복제하지 않고 1,000자 이내의 필요한 Board 본문만 근거로 저장한다. 기사 제목도 함께 기록한다. 가격/환율/통계/영업시간을 추정하지 않는다. 근거 유효 기간은 Fed 게시일+30일, Wikidata 수집일+7일이다.

리다이렉트·임의 주소 fetch·유료벽 우회를 구현하지 않는다. Fed robots 요청은 404였고 공개 RSS/허용된 공식 본문만 제한적으로 읽었다. 429는 Retry-After(숫자) 또는 보수적 대기를 적용하고, 5xx/네트워크 실패는 제한된 재시도·감사 기록으로 처리한다. robots/약관이 변경되면 해당 소스를 비활성화하고 정책을 재확인해야 한다.

## 설치·실행

```powershell
.venv/Scripts/python scripts/setup-local-ai.py
.venv/Scripts/python scripts/start-local-ai.py Qwen3-1.7B-Q8_0.gguf
.venv/Scripts/python scripts/setup-local-ai.py --with-vulkan
.venv/Scripts/python scripts/start-local-ai.py Qwen3-4B-Q4_K_M.gguf 4 vulkan
.venv/Scripts/python scripts/migrate.py
# 기존 API 8100 / Dashboard 3100 / WooriBlogAgent-Worker 사용
.venv/Scripts/python scripts/benchmark-local-ai.py
# 실제 수집된 선정 후보·일치하는 모델 설정이 있어야 실행 가능:
.venv/Scripts/python scripts/verify-live-pipeline.py --evaluation-only
```

setup은 공식 engine/model을 pinned SHA-256 확인 후 `.local`에만 내려받는다. 기본은 CPU build이며 `--with-vulkan`은 별도 `llama-b11889-vulkan` 디렉터리에 공식 Vulkan build를 설치한다. CPU 바이너리를 대체하거나 시스템 PATH/드라이버를 바꾸지 않는다. Qwen3 0.6B/1.7B Q8_0와 4B/8B Q4_K_M의 모델카드에서 Apache-2.0 라이선스를 확인했다. 모델·캐시·런타임 파일·바이너리는 Git 제외다. 8B 모델은 실행 전 파일 크기에 3GiB 여유를 더한 RAM이 필요하며, 한 번에 하나의 추론 서버만 실행한다. GPU layers=20은 안전한 부분 오프로딩 기본값이며 실제 GPU 엔진 counter가 수집되지 않으면 사용률은 미측정으로 남긴다. 유료 추론·클라우드 서비스 가입/호출은 하지 않는다.

이미 11435에 리스너가 있으면 시작 스크립트가 거부한다. 모델 변경 시 자신의 프로젝트 `.local/runtime.json` PID와 실제 실행 파일 경로를 먼저 확인한 뒤 그 엔진만 정상 종료하고 다시 실행한다. 다른 리스너를 자동 종료하지 않는다. API/Dashboard/Worker는 다른 프로젝트와 포트를 공유하지 않는다. 현재 CPU backend는 시작 시 threads=4다. OS 강제 자원 상한이나 GPU 가속은 구현하지 않았다.

`/research`에서 실제 수집 실행, 수집 스케줄, 모델 상태·설치 목록·실측 샘플·오류·처리 시간·CPU/RAM, 원고/근거/품질을 조회한다. 일반 자동 생성은 모델·언어 품질이 검증된 경우에만 허용한다. 현재 두 모델 모두 그 승인을 받지 않았으므로 language_verified=false를 유지한다. 명시적 평가 버튼은 해당 제한을 품질 승인으로 바꾸지 않고 quality_held로 시험한다.

수집 스케줄은 기본 비활성이다. 활성화하면 기존 Worker가 수집 작업을 영속 큐에 넣는다. auto_generate는 검증된 일반 생성 설정에만 사용해야 한다. 평가 전용 설정에서 스케줄로 실제 원고를 승인하지 않는다. 수집→생성 인계는 같은 collected 키를 재사용해 중복을 막는다. 수집 실패/임대 만료/생성 실패는 기존 작업/감사 이력에서 확인한다.

CPU·RAM은 실행 중 표본과 전체 PC 상태가 함께 영향을 받는다. 시스템 CPU peak와 해당 엔진 CPU를 구분한다. Windows GPU Engine counter를 같은 모델 PID에 한정해 읽고 실패하면 GPU 이용률은 미측정으로 표시한다. Vulkan loader가 AMD RX 570 장치를 열거하는 것만으로 추론 오프로딩이나 성능을 가정하지 않는다. 실제 재부팅 리허설과 OS 수준 hard resource cap은 미완료다.


## Phase 3.6 model evaluation (2026-10-26)

??? Ryzen 5 5600 (6??/12???), 31.91 GiB RAM, Radeon RX 570?? ????. ?? ?????????? ??? ???? ????. CPU ??? llama.cpp b11889 CPU ??, Vulkan ??? ?? b11889 Vulkan ??? GPU layers=20? ????. ?? JSON ??? ?? ?? ??? ??? ???. ??? ??, ???, SHA-256, ?? ??? `docs/development/P3-6-002.md`? DB? append-only `model_measurements`? ??.

| ??/?? | en | ja | ko | zh-CN | ?? |
| --- | --- | --- | --- | --- | --- |
| Qwen3-1.7B Q8_0 / CPU | 70.226s, 10.18 tok/s, RSS 2788 MiB | 59.786s, 13.15 tok/s, RSS 2959 MiB | JSON ?? | 50.072s, 13.14 tok/s, RSS 3383 MiB | 3/4 JSON ??, ?? ?? ?? |
| Qwen3-4B Q4_K_M / CPU | 73.861s, 8.61 tok/s, RSS 5386 MiB | JSON ?? | 93.528s, 8.85 tok/s, RSS 5895 MiB | 54.375s, 6.90 tok/s, RSS 6136 MiB | 3/4 JSON ??, ?? ?? ?? |
| Qwen3-8B Q4_K_M / CPU | 98.136s, 4.57 tok/s, RSS 9628 MiB | 130.549s, 3.95 tok/s, RSS 8992 MiB | 123.859s, 5.01 tok/s, RSS 9195 MiB | 118.320s, 4.23 tok/s, RSS 9412 MiB | 4/4 JSON ??, ?? ?? ?? |
| Qwen3-4B Q4_K_M / Vulkan 20 layers | 65.107s, 9.09 tok/s, RSS 4087 MiB, GPU max 48.72% | JSON ?? (141.504s) | 111.386s, 8.67 tok/s, RSS 4160 MiB, GPU max 50.31% | 57.182s, 9.15 tok/s, RSS 4210 MiB, GPU max 50.19% | 3/4 JSON ??, ?? ?? ?? |

CPU ?? ?? ???? CPU? ??/??? ?? 30?33%??, Qwen3-4B Vulkan? 28.81?29.53%??. ?? ?? ?? ?? ???? ?? ?? ?? ?/??? ????. GPU counter ?? per-PID ?? ?? ??? GPU ??? ???? ?? GPU ???? ???? ???. ?? ????? ?? ?? ??? ???? ???. 8B? JSON ???? ???? 4.4 tok/s ???? ??? RSS ?? ? 9.6 GiB???, ????? ?? ???? ????. 4B Vulkan? CPU ?? ????? ??? ??? ??? ???.

?? ??? ????? ?? ?? ??? `quality_held`??. ??? ??? ?? ?? ??, ?? ? ???????, ?? ???? ?? ??, ?? ??, ??/???/??? ?? ????. ??? ?? ????? ??? ???? ???. ?? ??? ?? ??, ?? ?????, ?? URL? ?? ??? ???? ???? ??? ? ??? ?? ??? ?? ?? ??? ??? ???. 28? ??????? ???? ? ? ?? ?? ??? ?? ?? ??? ?? ???? ? ???? ??? 24?? `blocked_no_reviewed_source`?.


## Phase 3.8-C1 official-source article evaluation

The finance/stock evaluation path currently accepts only reviewed Federal Reserve RSS/release text and SEC submissions/XBRL records. SEC calls use `https://data.sec.gov`, a declared `SEC_USER_AGENT_CONTACT`, GET-only endpoint allowlists, bounded response sizes, and local limits of 3 requests/minute and 24/hour (stricter than SEC's fair-access ceiling). SEC filing HTML and third-party assets are not collected. Federal Reserve authored text is treated as public domain unless otherwise marked; third-party content is excluded. See the [source review](research-source-review.md).

Run the actual local Qwen evaluation only when the dedicated DB is migrated, the local model runtime identity is verified, and at least 2 GiB RAM headroom exists:

```powershell
.venv/Scripts/python scripts/evaluate_complete_articles.py
```

This command enqueues/collects the two reviewed source types, then generates drafts for active language profiles. `--skip-collection` reuses current approved, unexpired records; diagnostic `--language`/`--topic-key` runs still write new immutable evaluation records. It never calls a hosted AI service and does not publish to Blogger. Results are written to `docs/development/P3-8C1-evaluation.json` (or a unique diagnostic artifact) and `article_quality_evaluations`. Held and failed results are retained for analysis; do not edit them or mark them approved by hand. A separate run may create a later evaluation.

Official source policies and references:
- Federal Reserve [disclaimer](https://www.federalreserve.gov/disclaimer.htm): Board-authored material is public domain unless otherwise noted; attribution and third-party exclusions still apply.
- SEC [EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces): submissions and XBRL data endpoints are public and require no API key.
- SEC [Webmaster FAQ](https://www.sec.gov/about/webmaster-frequently-asked-questions): EDGAR access/reuse guidance, declared User-Agent and current request ceiling. Project limits are lower.

Machine quality checks do not verify semantic accuracy, naturalness, or all reuse rights. Human review remains required and `publish_ready` stays false.

### Rechecking saved article quality

The Phase 3.8-C2 command reads the immutable Phase 3.8-C1 evaluation batch, checks the saved versions against the current deterministic rules, and inserts new evaluation/audit rows:

```powershell
.venv/Scripts/python scripts/recheck_article_quality.py
```

It does not call the model or external sources. If an old failed attempt has no response artifact/version, it is reported as not replayable. Future local JSON/schema errors can be retried once with a different seed; the raw response excerpt is capped at 16 KiB, stored only in the local immutable DB table, and never emitted to ordinary logs.
# Bounded fact-first evaluation

Use `python scripts/run_fact_first_evaluation.py` only when the existing local llama.cpp runtime is already running the allowlisted Qwen3 4B Q4 model, at least 6 GiB RAM is available, the pipeline is not paused, and no unrelated content run is queued or running. The script evaluates the current reviewed Fed and SEC sources across active base language profiles, creates evaluation-only internal drafts, and never calls collection services or Blogger write endpoints. It reuses only its own identifiable unfinished C3 batch after interruption. Keep the configured daily limit and pipeline resource checks in force; do not force a run when they block.
