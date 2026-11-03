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
