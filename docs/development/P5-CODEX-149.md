# P5-CODEX-149 — Codex 예약 원고 작성 및 Scheduled LIVE 연결 복구

## 작업 기록

- 작업 일시: 2026-11-05 KST
- 브랜치: `develop`
- 시작 HEAD: `592211799f30182db4bbcd19c80187d1bfe873d9`
- PostgreSQL 시작 감사: `agent.work.started`, ID `378380`
- Paid AI API / Blogger 쓰기: 0건

## 확인한 장애 원인

1. automation-4는 Resolver와 로컬 중복 사전검사 후 research stage에서 `research_evidence_unavailable`로 끝났다. 보존된 실행 결과에는 유효 출처가 없다는 사실만 남아 있어 검색 응답, 날짜 필터, URL 매칭 중 어느 하위 조건이 실패했는지는 단정하지 않는다.
2. automation-14는 두 개의 Destatis 출처를 package에 넣었지만 해당 URL은 Codex 검색 세션에서 열린 URL로 확인되지 않았다. `require_opened_sources=False`였고 선택한 출처별 open 상태도 확인하지 않았다. 패키지가 검색 결과 스니펫을 `evidence_available`로 표시했으나 Desktop은 원고 근거가 부족하다고 판단해 작성하지 않았다.
3. Research Import 뒤의 live source capture catalog는 Destatis를 허용하지 않았다. 원고가 Import되더라도 source live verification 단계에서 Destatis 근거가 막혀 Scheduled Auto Queue에 진입할 수 없었다.
4. `update-codex-automation-authoring-recovery.py`는 이전 프롬프트의 고정 종료 문구가 없으면 현재 20개 프롬프트를 갱신하지 못했다. 그래서 공통 절차 갱신이 `automation-ai`에서 중단될 수 있었다.

## 변경

- Codex research broker는 `require_opened_sources=True`를 사용하고, 선택한 URL이 검색 결과와 실제 열린 URL 양쪽에 존재해야 자료를 채택한다. 알려진 tracking query parameter는 비교 키에서 제거해 URL 추적값 차이만 허용한다.
- Research Package에는 열린 페이지에서 Codex가 보고한 원문 발췌와 `source_opened_at`을 저장한다. 발췌는 독립 검증으로 표시하지 않으며 Import Worker가 실제 원문을 다시 가져와 일치 여부를 확인해야만 발행 eligibility에 사용된다.
- 기존 zero-cost 검토가 끝난 BLS, White House, NIST, Federal Reserve의 정식 페이지에 대해 정확한 HTTPS host/path catalog를 추가했다.
- Destatis의 날짜형 EN/DE press-release 경로만 source capture에 추가했다. `external_policy`는 query, fragment, 다른 host, 다른 파일 경로를 거부하고 3/minute, 12/hour 제한을 적용한다. rights는 unknown으로 유지하며 재사용 허용으로 간주하지 않는다.
- `docs/operations/zero-cost-policy.md`에 Destatis 비용·범위·rights 제한과 공식 문서를 기록했다.
- prompt updater는 예전 고정 문구 대신 계약 marker를 경계로 삼아 현재 프롬프트도 안전하게 갱신한다. active local Automation 20개의 조사 및 Import 완료 지침을 갱신했다.
- Automation ID, 상태, RRULE, 모델, target, project path 및 기타 불변 설정은 변경하지 않았다. local TOML 백업: `C:\Users\achie\.codex\automation-backups\P5-CODEX-147-20261105T083342Z`.

## 검증

- `test_scheduled_research.py`, `test_scheduled_source_evidence.py`, `test_update_automation_authoring_recovery.py`, `test_publications.py`: **87 passed**.
- Ruff: 통과.
- Python `py_compile`: 통과.
- `git diff --check`: 통과.
- 실제 ChatGPT-auth Codex CLI 격리 검색 probe: `gpt-6-luna`, 검색 2건, BLS 원문 URL 열린 이벤트 확인. tracking query가 붙은 열린 URL과 query 없는 canonical source URL을 동일한 경로로 정규화했다. 이 probe는 조사 검증만 했고 원고·Import·Publication Job을 만들지 않았다.
- CLI fixed runner는 ChatGPT 로그인 사용, API-key fallback 비활성 상태로 실행됐다. 별도 OpenAI API 사용 없음.
- 20개 local TOML prompt 갱신 및 백업 검증 완료. 공식 Codex Desktop UI의 프롬프트 재로드 상태는 확인하지 못했다.

## 운영 결과 및 남은 검증

- 서비스 반영/재기동: 이번 기록 시점에는 미실시. 변경 코드는 아직 운영 API/Worker 런타임에 적용되지 않았다.
- 실제 새 Desktop 예약 실행: 미검증. 과거 automation-4/14 occurrence는 재실행하지 않았다.
- 실제 Research Snapshot, 원고 파일, Import Receipt, Publication Queue, Blogger LIVE: 이번 작업에서 생성·검증하지 않았다.
- 기존 AutoMode, Scheduled Auto scope, Blogger OAuth, 큐, 게시 이력은 수정하지 않았다. Blogger 테스트 게시/초안 0건.
- 다음 신규 Desktop 예약 실행에서 opened-source package → 원고 envelope → Import Receipt → live source capture → Scheduled Auto queue 및 실제 LIVE 결과를 각각 확인해야 한다. 기존 안전·중복·권리·일일 상한·간격 gate는 계속 적용된다.

## 수정 파일

- `services/api/woori/scheduled_research.py`
- `services/api/woori/scheduled_source_evidence.py`
- `services/api/woori/external_policy.py`
- `scripts/update-codex-automation-authoring-recovery.py`
- `services/api/tests/test_scheduled_research.py`
- `services/api/tests/test_scheduled_source_evidence.py`
- `services/api/tests/test_update_automation_authoring_recovery.py`
- `docs/operations/zero-cost-policy.md`
- `docs/development/P5-CODEX-149.md`

## 커밋

- Feature 및 개발 기록 커밋: `30724e7`; 문서의 커밋 자기 참조는 후속 Git 기록으로 확인.
- 운영 반영 및 다음 신규 예약의 종단 간 결과는 별도 follow-up으로 기록한다.
