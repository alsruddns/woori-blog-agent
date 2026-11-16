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

## 배포 전 운영 상태

- Schema 92, 설정 revision 23. `AutoMode=auto`, `AutoPolicyActive=true`, Scheduled Auto enabled, `operations_auto_approved=true`, `blogger_write_mode=public_write_approved`.
- 자동 발행 간격 15분, KST 일일 제한 100건, 승인된 활성 Blogger 6개 EN/KO/JA/DE/pt-BR/VI. zh-CN은 범위 밖이다.
- Research 진행 Job 0, Publication running/uncertain 0, scheduled-auto queued/due 0. 기존 24개 예약 Import는 전부 `awaiting_human_review`.
- Trends Job 1건은 `available_at=2026-11-06 00:00 KST`; queue row를 보존했다.
- 기존 발행 실패·차단 Job과 게시 이력은 변경하지 않았다.

## 검증

- `test_scheduled_research.py`, `test_scheduled_source_evidence.py`, `test_update_automation_authoring_recovery.py`, `test_publications.py`: **87 passed**.
- Ruff: 통과.
- Python `py_compile`: 통과.
- `git diff --check`: 통과.
- 실제 ChatGPT-auth Codex CLI 격리 검색 probe: `gpt-6-luna`, 검색 2건, BLS 원문 URL 열린 이벤트 확인. tracking query가 붙은 열린 URL과 query 없는 canonical source URL을 동일한 경로로 정규화했다. 이 probe는 조사 검증만 했고 원고·Import·Publication Job을 만들지 않았다.
- CLI fixed runner는 ChatGPT 로그인 사용, API-key fallback 비활성 상태로 실행됐다. 별도 OpenAI API 사용 없음.
- 20개 local TOML prompt 갱신 및 백업 검증 완료. 공식 Codex Desktop UI의 프롬프트 재로드 상태는 확인하지 못했다.
- 공식 `apply-verified-changes.ps1` 첫 검증은 pytest 34개 통과 후 Windows 전역 pytest temp ACL 정리에서 종료됐다. 서비스는 중지되지 않았다. 프로젝트 전용 `PYTEST_ADDOPTS=--basetemp=.runtime\\p149-official-test`로 다시 실행한 공식 검증은 34 passed; Ruff, mypy, isolated wheel, Dashboard lint/typecheck/production build도 통과했다.

## 운영 반영 및 남은 검증

- `scripts/apply-verified-changes.ps1 -Apply -Confirm:$false`가 변경 코드 검증 및 isolated Dashboard build 후 전체 4개 서비스를 정상 종료·재기동했다. 강제 종료는 없었다.
- 기존 PID → 새 PID: API 20824 → 9832, Dashboard 20028 → 15372, Research Worker 4888 → 26920, Publication Worker 4732 → 34872.
- API `/health` 및 Dashboard `/research` HTTP 200. Research/Publication Worker heartbeat fresh. 네 서비스 적용 revision 모두 `34ac9eef9d73619e90cc3a27445a5634dc54e99d`.
- 재기동 후 schema 92, revision 23, `AutoMode=auto`, `AutoPolicyActive=true`, Scheduled Auto enabled, 15분 간격, KST 100건 한도, 승인된 Blogger 6개와 `operations-scheduled-auto-and-manual-and-trends` worker mode 확인.
- 기존 24개 scheduled Import는 모두 `awaiting_human_review`, scheduled-auto Job은 과거 성공 1건, 신규 scheduled queue 0건. Trends의 기존 queued Job 1건은 그대로 유지했다.
- 재기동 이후 10분 이내 Blogger write attempt 0건. 테스트 게시/초안 0건.
- 공식 Desktop UI에서 프롬프트 재로드 및 다음 신규 예약 실행은 미검증이다. 새 Snapshot, 원고 파일, Import Receipt, 신규 Publication Queue와 LIVE 결과는 아직 없다. automation-4/14 과거 occurrence는 재실행하지 않았다.
- Source capture는 기존에 검토된 Federal Reserve/BLS/White House/NIST/ONS/Japan energy 경로와 이번에 추가한 Destatis만 허용한다. 이 목록 밖의 Vietnam/Brazil/Japan/Korea/crypto 등 출처는 추가 검토·allowlist 없이는 fail closed이며, 따라서 local prompt 20개 갱신만으로 모든 주제의 자동 LIVE를 보장하지 않는다.
- 다음 신규 공식 Desktop 예약에서 opened-source package → 원고 envelope → Import Receipt → live source capture → Scheduled Auto queue → 실제 LIVE를 단계별 확인해야 한다. 적격 자료와 기존 중복·권리·품질·한도 정책이 통과해야 게시된다.

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

- Feature commit: `30724e7`; 이 운영 결과 기록의 후속 문서 commit은 Git history에서 확인한다.
- `origin/develop` 반영 완료. 신규 예약의 실제 종단 간 결과는 Desktop 실행 후 별도 append-only follow-up으로 기록한다.

## 운영 안정화 후속 기록

- 운영자 우선순위 확인: Codex 예약 원고 작성 및 적격 원고 발행은 제품의 핵심 경로다. 이번 변경은 검색 결과만으로 evidence를 인정하던 결함과 Destatis source-capture 누락을 수정하고, 기존 Scheduled Auto lane을 실제 Worker에 반영했다.
- 최종 코드/runtime revision: `34ac9eef9d73619e90cc3a27445a5634dc54e99d`; API, Dashboard, Research Worker, Publication Worker가 모두 이 revision으로 재기동됐다. 데스크톱 PC 전체 재부팅은 필요하지 않았다.
- 현재 검증 수준: 배포와 서비스 상태는 확인했지만, 변경 후 신규 공식 Desktop 예약으로 Snapshot → 원고 → Import Receipt → Publication Queue → LIVE가 이어지는 실증은 아직 없다. 기존 24건의 review-held Import 및 과거 예약 occurrence는 보존했고 재실행하지 않았다.
- 적용 범위 한계: source capture는 기존 reviewed catalog 및 이번에 추가한 Destatis 경로만 수용한다. catalog 밖 출처는 fail-closed이므로 모든 20개 Automation의 주제에서 LIVE까지 보장됐다고 보고하지 않는다. 해당 기능 완료 판정에는 각 신규 실행의 실제 출처 패키지와 publication eligibility를 확인해야 한다.
- Blogger 테스트 게시/초안 및 별도 유료 API 호출은 0건. AutoMode, Scheduled Auto 승인, 15분 간격, KST 일일 100건 제한, 활성 Blogger 6개 설정은 유지됐다.
- 이 후속 기록은 기존 작업 로그를 덮어쓰지 않고 배포 후 확인 사항을 추가한다. 최종 문서 커밋은 Git history 및 PostgreSQL 완료 감사 이벤트에서 연결한다.
