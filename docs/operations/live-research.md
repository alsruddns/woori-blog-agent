# 실제 수집·로컬 모델 운영

로컬 모델 API는 `.local/inference.key`의 프로젝트 전용 비밀키로 보호한다. 키 값은 프로세스 인수가 아닌 `--api-key-file`로 전달하며 로그·응답·Git에 포함하지 않는다. 시작 스크립트의 두 번째 선택 인수로 CPU threads(1–4)를 지정할 수 있다. 실행 중인 엔진과 DB 스레드 정책이 다르면 명확히 거부하므로 해당 프로젝트 엔진만 정상 재시작해야 한다.

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
.venv/Scripts/python scripts/migrate.py
# 기존 API 8100 / Dashboard 3100 / WooriBlogAgent-Worker 사용
.venv/Scripts/python scripts/benchmark-local-ai.py
# 실제 수집된 선정 후보·일치하는 모델 설정이 있어야 실행 가능:
.venv/Scripts/python scripts/verify-live-pipeline.py --evaluation-only
```

setup은 공식 engine/model을 해시 확인 후 `.local`에만 내려받는다. 모델·캐시·런타임 파일·바이너리는 Git 제외다. 현재 두 모델 합 약 2.4GB 수준이며 정확한 파일 크기는 manifest/UI에서 확인한다. 모델 라이선스는 [Qwen 0.6B](https://huggingface.co/Qwen/Qwen3-0.6B-GGUF), [Qwen 1.7B](https://huggingface.co/Qwen/Qwen3-1.7B-GGUF), 엔진은 [llama.cpp MIT](https://github.com/ggml-org/llama.cpp/blob/master/LICENSE)에서 확인했다. 유료 추론·클라우드 서비스 가입/호출은 하지 않는다.

이미 11435에 리스너가 있으면 시작 스크립트가 거부한다. 모델 변경 시 자신의 프로젝트 `.local/runtime.json` PID와 실제 실행 파일 경로를 먼저 확인한 뒤 그 엔진만 정상 종료하고 다시 실행한다. 다른 리스너를 자동 종료하지 않는다. API/Dashboard/Worker는 다른 프로젝트와 포트를 공유하지 않는다. 현재 CPU backend는 시작 시 threads=4다. OS 강제 자원 상한이나 GPU 가속은 구현하지 않았다.

`/research`에서 실제 수집 실행, 수집 스케줄, 모델 상태·설치 목록·실측 샘플·오류·처리 시간·CPU/RAM, 원고/근거/품질을 조회한다. 일반 자동 생성은 모델·언어 품질이 검증된 경우에만 허용한다. 현재 두 모델 모두 그 승인을 받지 않았으므로 language_verified=false를 유지한다. 명시적 평가 버튼은 해당 제한을 품질 승인으로 바꾸지 않고 quality_held로 시험한다.

수집 스케줄은 기본 비활성이다. 활성화하면 기존 Worker가 수집 작업을 영속 큐에 넣는다. auto_generate는 검증된 일반 생성 설정에만 사용해야 한다. 평가 전용 설정에서 스케줄로 실제 원고를 승인하지 않는다. 수집→생성 인계는 같은 collected 키를 재사용해 중복을 막는다. 수집 실패/임대 만료/생성 실패는 기존 작업/감사 이력에서 확인한다.

CPU·RAM은 실행 중 표본과 전체 PC 상태가 함께 영향을 받는다. 시스템 CPU peak와 해당 엔진 CPU를 구분한다. GPU 이용률은 취득 못한 경우 미측정으로 표시한다. CPU-only 및 GPU layers=0은 GPU 이용률 실측을 대신하지 않는다. 실제 재부팅 리허설과 OS 수준 hard resource cap은 미완료다.
