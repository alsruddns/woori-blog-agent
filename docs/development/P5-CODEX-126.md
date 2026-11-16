# P5-CODEX-126 — Google Trends 원고 작성 최소 검색량

- 작업일: 2026-11-04 KST
- 시작 브랜치/HEAD: `develop` / `640550dc9321868914d05b4a5ed4a033aced01d1`
- 요청: Google Trends 수집 자료의 원고 작성 검색량 기준을 설정 가능하게 하고 기본값을 5,000으로 둔다.

## 변경 전과 원인

`trend_editorial.queue_selected()`는 현재 수집 회차의 `source_volume_lower_bound > 0`만 확인했다. 따라서 낮은 검색량 후보도 Codex 작성 요청으로 이어질 수 있었다. 동일 주제에 여러 관측치가 있으면 선정된 관측치와 작성 요청의 관측치가 다를 수도 있었다. Google RSS `approx_traffic`은 정확한 조회수가 아닌 공급자 제공 범위의 하한이다.

## 변경 후

- Migration 086으로 `automation_controls.trends_authoring_min_volume`을 추가한다. DB 기본값은 5,000, 허용 범위는 1~1,000,000,000이다. 기존 설정, 수집 이력, 작성 요청, 발행 Job은 변경하지 않는다.
- 현재 회차의 자동 작성 후보는 공급자 제공 검색량 하한이 최신 설정값 이상인 경우만 조회한다. 값이 없는 관측치는 기준을 충족한 것으로 간주하지 않는다. 원고 작성 요청도 같은 기준을 재확인하고 선정된 관측치를 사용한다.
- Dashboard 자동화 설정의 Codex 작성 카드에서 검색량 기준을 변경한다. 기존 관리자 인증, 변경자·사유, 확인 모달, 설정 revision 및 감사 기록 경로를 재사용한다.
- 이 기준은 Google Trends 수집 주기 및 Blogger 발행 간격과 독립적이다. 검색량만으로 사건 확인, 출처 검증, 중복 검사 또는 발행 승인을 통과시키지 않는다. 이미 등록된 요청을 재실행하거나 취소하지 않는다.

## 변경 파일

- `scripts/086_trends_authoring_min_volume.sql`: 설정 컬럼, 기본값, 범위, migration 감사.
- `scripts/migrate.py`: 버전 086 적용.
- `services/api/woori/automation_controls.py`: 변경 API 검증 및 revision/audit 저장.
- `services/api/woori/trend_editorial.py`: 자동 후보 필터 및 원고 작성 직전 기준 재확인, 선정 관측치 연결.
- `apps/dashboard/app/operations/automation/controls.tsx`: 현재값·기본값·수정 입력 및 확인 표시.
- `services/api/tests/test_automation_controls.py`, `services/api/tests/test_trend_editorial.py`: 설정 독립성, 감사 및 4,999/5,000 경계 회귀.

## 검증 및 운영 반영

- 운영 DB 백업: `backups/20261103T152356Z.dump` (`pg_restore --list` 검증). 복원 리허설은 수행하지 않았다.
- Migration 086 적용 및 운영 schema version 86 확인. 첫 적용은 3초 잠금 제한에 걸려 롤백됐고 이후 정상 적용됐다.
- 격리 테스트 DB에도 Migration 086 적용. 관련 pytest 45건 통과, 실패 0건. 첫 실행의 fixture 1건은 이전 1,000 검색량 가정을 사용해 실패했으며 경계값으로 수정 후 재실행에 통과했다.
- Ruff 변경 파일 검사, mypy, Dashboard lint/typecheck 통과. 운영 DB 설정 revision은 20이며 새 기준은 5,000이다. Migration은 기존 revision과 다른 설정값을 변경하지 않았다.
- 실제 Google Trends/Codex 작성이나 Blogger 쓰기 요청은 테스트 목적으로 실행하지 않았다.

## 남은 확인

- 실제 신규 수집 회차에서 5,000 이상 후보의 사건·출처 검증 및 원고 파일 생성은 회차 발생 후 확인해야 한다.
- 최종 Git 커밋은 이 문서의 후속 커밋 또는 `git log`로 추적한다.

---

# P5-CODEX-126 추가 작업 — Blogger 우선 발행 정책 복구

- 작업 일시: 2026-11-04 KST
- 시작 브랜치/HEAD: `develop` / `591a24c51c768959d57b22219af3761722c3f53c`
- 문서 충돌: 이 파일의 앞부분은 같은 ID로 수행된 Trends 검색량 설정 이력이다. 해당 이력을 보존하고 이번 Blogger 정책 변경을 별도 절로 추가한다.
- 참고 이력: P5-CODEX-052/058의 예약 원고 발행 우선 정책, P5-CODEX-115~125의 수동 발행·Trends·운영 승인 변경. 예약 경로의 기존 핵심 사실·권리 검증을 재사용한다.

## 기존 문제와 원인

수동 발행 API의 `_manual_publication_blockers`가 기계 품질, SEO, 인간 편집, 원고 버전별 승인, 과거 `publish_ready` 플래그를 각각 필수 발행 게이트로 사용했다. Dashboard는 실제 검토가 없는데도 세 가지 검토 확인값을 `true`로 보냈다. DB CHECK와 Worker 역시 이 값을 필수로 요구했다. 예약 발행에는 이미 별도의 publish-first 평가가 있었으나 수동 경로에는 적용되지 않았다. Trends 경로는 단순 본문 길이를 차단 조건으로 사용하면서 핵심 claim 검증 함수는 실제 평가에서 사용하지 않았다.

## 변경 전후

- 수동: 별도 편집 확인값을 UI에서 제거했다. 정확한 원고 버전과 LIVE/Draft 모드를 지정한 발행 클릭은 발행 의사로 저장한다. 구형 클라이언트가 검토 확인값을 보내더라도 신규 이벤트에는 검토 사실을 거짓으로 기록하지 않는다. 일반 품질·SEO·편집·과거 `publish_ready` 미달은 기존 발행 후 보완사항 원장에 기록한다. 현재 원고의 출처 원문 증명, 주장 근거, 명시적 권리 제한, 유효하고 정제된 본문, 대상·권한·정책·중복·전역 제한은 유지한다.
- 자동 예약: 기존 P052/058의 publish-first 평가와 검증된 주장만 남기는 제한적 정제 경로를 유지한다. 개별 원고 승인 추가 없이 기존 운영 승인과 블로그 범위가 적용된다.
- Trends: 보통의 제목/분량 경고는 보완사항으로 남기고, 근거가 없는 핵심 claim은 차단한다. LIVE Job에 사전 보완사항을 멱등 키로 기록한다.
- 상태: 품질 결과는 변경하지 않고, 발행 요청 이벤트와 실제 Blogger 게시 결과를 별도로 유지한다. 원고·Content Version·기존 게시물과 감사 이력은 덮어쓰지 않는다.

## 변경 파일

- `services/api/woori/publications.py`: 수동 의사 기록, 독립 사실·권리 검증, 보완사항 분리.
- `services/api/woori/publication_worker.py`: 구형 검토 확인값 필수 조건 제거. 해시·대상·발행 정책 검사 유지.
- `services/api/woori/scheduled_auto_verification.py`: 기존 예약 증명 평가를 수동 Import에도 재사용할 수 있도록 생성 경로 인자를 추가.
- `services/api/woori/trends_publication.py`: 일반 품질 경고와 근거 없는 핵심 사실 차단 분리, 보완사항 저장.
- `scripts/089_manual_publication_intent.sql`, `scripts/migrate.py`, `scripts/provision-test-database.py`: additive 스키마 변경 및 격리 테스트 DB 버전 연결.
- `apps/dashboard/app/imports/external-import-workspace.tsx`, `apps/dashboard/app/publishing/publication-manager.tsx`: 거짓 검토 확인 제거, 큐 접수와 실제 게시 결과 구별, 보완 건수 표시.
- `services/api/tests/test_publications.py`, `test_post_publication_reviews.py`, `test_scheduled_publish_first.py`, `test_trends_publication.py`, `test_trends_post_edit.py`, `apps/dashboard/e2e/P5-CODEX-078-publishing.spec.ts`, `P5-CODEX-110-grid-publish.spec.ts`: 정책 회귀 및 UI 계약 검증.

## 검증과 운영 반영

- 격리 DB에 Migration 089를 적용하여 기존 행 보존 상태에서 수동 의사 레코드와 Trigger 경로를 테스트했다. 최초 시험에서 PostgreSQL의 63바이트 제약 이름 절단을 확인해 Migration의 DROP 이름을 바로잡았다. 운영 DB에는 적용하지 않았다.
- 변경 범위 발행 관련 pytest 최종 224 통과, 0 실패. 최초 확장 회귀에서 기존 Trends 테스트의 미검증 claim 게시 가정 7건이 실패했으며, 검증된 사실 fixture와 미검증 차단 테스트로 수정 후 재실행해 모두 통과했다.
- Ruff, mypy(변경 Python 모듈 4개), Dashboard typecheck, lint, 독립 production build 통과. Playwright 그리드 12 통과(1440px/390px).
- 테스트와 개발 과정의 실제 Blogger 쓰기 호출: 0건. 운영 서비스와 설정은 변경하지 않았다. 운영 DB schema 88 및 실행 서비스는 기존 revision 상태이므로 이번 코드는 운영 미반영이다. 실제 LIVE 게시 성공도 미검증이다.
- 기존 OAuth, Blogger ID, 예약 정의, 게시 기록, stash를 변경하지 않았다. 활성 블로그·zh-CN 중단, Trends 14개 지역/30분, 글로벌 15분, KST LIVE 100건, 예약→수동→Trends 순서, 운영 승인 게이트는 코드에서 유지했다.

## 남은 문제

- Codex CLI를 이용한 새로운 의미적 자동 재작성·재조사 Worker는 구현하지 않았다. 이미 있던 예약 원고의 제한적 결정적 정제와 수동 HTML sanitizer만 적용된다. 중요한 사실·권리 근거가 부족한 원고는 여전히 안전 보류된다.
- 운영 DB 백업→Migration 089→API/Dashboard/Publication Worker 안전 교체 및 heartbeat/실제 발행 검증이 남았다. 개발 중 실제 Blogger 게시 금지 지시에 따라 운영 자동 발행을 촉발할 수 있는 서비스 교체는 수행하지 않았다.
- 이번 변경 커밋은 이 문서 다음의 `git log`에서 추적한다.
