# P5-CODEX-157 — 예약 원고 검색 메타데이터 과잉 차단 수정

## 작업 기록

- 작업 일시: 2026-11-17 (Asia/Seoul)
- 작업 ID: `P5-CODEX-157`
- 브랜치: `develop`
- 시작 HEAD: `82cbfdb` (`Docs : [P5-CODEX-154] Clarify fed-sec invocation identity`)
- PostgreSQL 시작 감사: `agent.p5_codex_157.started`, ID `693298`
- PostgreSQL 설정 감사 정정: `agent.p5_codex_157.settings_audit_correction`, ID `693317`
- 변경 사유: 예약 원고 작성이 Resolver 및 중복 사전검사 뒤 research evidence 검사에서 반복 제한됨
- Blogger 실제 쓰기: 0건; 유료 API 호출: 0건

## 기존 문제 및 증거

- 2026-11-17 09:00 KST의 실제 `automation-7` 예약은 resolver와 local duplicate preflight를 통과했다 (`local_status=not_found`, `draft_import_allowed=true`, `remote_status=not_checked`).
- 생성된 불변 Research Package는 `source_validation_failed`였고 실패 이유는 `source_title_not_in_search_results` 1건과 `search_result_evidence_too_short` 2건이었다. 실행은 `evidence_unavailable`로 종료해 원고 작성·전달로 가지 않았다.
- URL이 검색 결과에 존재하고 같은 URL이 실제로 열렸더라도, 모델이 보고한 열린 페이지 제목이 검색 결과 제목과 정확히 다르면 출처 전체를 버렸다. 짧은 검색 snippet도 독립적으로 검증된 근거가 아닌데 필수 증거로 취급했다.
- 예약 원고 파일, Import Receipt, 새 scheduled publication queue는 이 occurrence에 생성되지 않았다. 과거 occurrence는 재실행하지 않았다.

## 변경 목적 및 전후 상태

- 변경 전: 검색 URL/열린 URL 외에 제목의 완전 일치와 검색 snippet 30자 이상을 요구해, 열린 페이지의 충분한 발췌가 있어도 예약 연구 패키지가 비어 있을 수 있었다.
- 변경 후: 검색 결과의 URL과 실제 열린 URL 일치, 검색 결과의 비어 있지 않은 제목, opened-page excerpt 최소 길이, publication date/freshness 검증은 유지한다. 저장 제목은 검색 이벤트에서 가져오고 모델이 보고한 열린 페이지 제목과 일치 여부를 별도 필드로 보존한다. 짧은 검색 snippet은 discovery metadata로만 저장하며 통과/실패 근거로 쓰지 않는다.
- 기존 source capture catalog, 원문 Import 검증, 의미·권리·편집 검토, 중복·LIVE·공통 wire gate는 변경하지 않았다. 연구 단계 성공만으로 Import 또는 발행 승인을 만들지 않는다.
- 작업 중 운영 DB 읽기 전용 확인: automation revision 25; 자동 원고, global auto, scheduled auto, manual publishing 및 operator approval ON; emergency stop OFF; scheduled policy 최신 이벤트 `enabled` 및 6개 승인 Blogger 범위; Research/Publication Worker 모두 revision 25 ACK. scheduled-auto queued job 0건.
- `trends_auto_publishing_enabled=true`가 저장소 AGENTS의 OFF 지시와 불일치한 사실을 확인해 관리 UI의 저장 흐름으로 Trends Auto만 OFF로 전환했다. 자동 원고/global auto/scheduled auto/manual publishing, LIVE mode, 6개 Blogger scope 및 Scheduled Auto policy는 변경하지 않았다. revision 26 저장 후 두 Worker 모두 revision 26을 확인했다. audit event ID `693317`에는 실제 actor context와 구체 사유를 append-only로 남겨 UI의 기존 일반 actor/reason 저장 이벤트(ID는 DB 이력에 보존)를 정정 설명했다.
- 최종 운영 확인: Scheduled Auto ON, Trends Auto OFF, LIVE mode, emergency stop OFF, daily cap 100, minimum spacing 15 minutes, scheduled queue 0. 자동 원고와 publication Workers의 현재 적용 revision은 26이다. 이 운영 정리는 코드 변경의 효과나 새 원고의 publication 성공을 입증하지 않는다.

## 수정 파일

- `services/api/woori/scheduled_research.py`
- `services/api/tests/test_scheduled_research.py`
- `docs/operations/zero-cost-policy.md`
- `apps/dashboard/package.json`
- `apps/dashboard/package-lock.json`
- `docs/development/P5-CODEX-157.md`

## 검증 결과

- 예약 조사·출처 캡처·예약 발행 검증·Scheduled Auto·자동화 제어 관련 회귀: **129 passed**.
- Ruff: 통과.
- Python `py_compile`: 통과.
- Mypy (`scheduled_research.py`): 통과.
- `git diff --check`: 통과.
- 새 회귀는 실제 예약에서 관찰한 제목 불일치 및 30자 미만 검색 snippet 상황을 재현한다. URL/열린 페이지/충분한 원문 발췌/current date가 있으면 evidence는 사용 가능 상태가 되고, 원문 Import 검증·출판 승인은 별도로 유지된다.
- 변경 검증은 mock/isolated DB 범위다. 새 공식 Desktop 예약→Research Package→원고 envelope→Import Receipt→Scheduled LIVE 종단 간 성공은 아직 관측되지 않았다.
- 운영 UI에서 Trends Auto를 OFF로 저장한 설정 변경은 테스트 글이나 Blogger write를 만들지 않았다. 사용되지 않은 두 실제 auto queue 후보는 0이었으며 저장 후 두 Worker ACK를 확인했다.
- 첫 공식 서비스 반영은 Dashboard production build에서 멈췄다. Next.js 16.4.3의 보안 차단으로 서비스는 중지되지 않았다. 공식 Next.js November 2026 Security Release의 수정 버전 16.4.5로 `next`와 `eslint-config-next`를 함께 고정했다. [Next.js November 2026 Security Release](https://nextjs.org/blog/november-2026-security-release).
- 의존성 설치가 moderate audit findings 7건과 `eslint@9.39.5` deprecated 알림을 표시했다. broad `npm audit fix`는 실행하지 않았으며, 의존성 audit 검토는 미완료다.
- 수정 버전으로 공식 반영 검증에서 API 회귀 (**19 passed**), Ruff, Mypy, isolated Python wheel, Dashboard ESLint, TypeScript 및 Next.js production build를 모두 통과했다.
- 이후 service reflection은 서비스를 멈추기 전에 안전하게 중단됐다. API PID `23592`/`24364`가 manifest 소유 runner 없이 원래 terminal에서 실행 중이어서 저장소 stop manager는 해당 터미널에서 Ctrl+C를 요구하며 프로세스를 종료하지 않았다. 어떤 서비스도 중지·재시작되지 않았다. API와 Research Worker는 `54f462ca89fe0a9bfb0863b51057a1ef50ecdd01`, Dashboard는 `8ec83ef6931801ce2bec7a6da7ec2d0c1283eab2`, Publication Worker는 `236c880204cf10182f7cb70697e2f96751a1ac6a` 적용 상태로 남았다. 수정 코드는 push됐지만 현재 실행 중인 API/Research Worker에는 아직 반영되지 않았다.

## 커밋, 원격 및 후속 확인

- 구현 커밋 `bf7d553` 및 package/build follow-up `964e75a`는 `origin/develop`에 push됐다. main 병합은 하지 않았다. PostgreSQL 완료 감사 `agent.p5_codex_157.completed`, ID `693444`는 runtime reflection 차단과 검증 결과를 기록한다.
- 실제 Desktop 예약은 current verified turn에서만 실행한다. 2026-11-17 09:00 KST의 occurrence는 완료/재실행하지 않았다.
- 다음 자연 예약에서 Resolver, evidence package, envelope handoff, Import Receipt, source capture, Scheduled Auto Queue, Worker wire result를 각 단계별로 확인해야 한다. 원문·권리·중복·LIVE gate 중 하나라도 실패하면 발행되지 않는 것이 정상 동작이다.
- 미해결: 원래 terminal에서 정상 종료한 뒤 실행 서비스에 코드 반영, 열린 Codex Desktop prompt가 최신 로컬 TOML을 읽었는지, 다음 예약의 실제 원고/Import/LIVE 결과, 7개 moderate dependency audit findings 및 ESLint deprecation 검토.

## 재기동 요청 후속 (2026-11-17)

- 사용자 요청에 따라 최신 `develop` 코드 반영을 위한 상태 확인 및 공식 정상 종료 절차를 다시 시도했다.
- 확인 당시 API PID `23592`, Dashboard PID `35260`, Research Worker PID `3180`, Publication Worker PID `29080`은 모두 실행 중이었으며 API/Dashboard/Research 적용 revision은 여전히 이전 코드였다. Publication Worker의 당시 상태는 queued/due 0건, `no_queued_job_in_enabled_lane`이었다.
- `scripts/stop.ps1 -Service api`는 API PID `23592`/`24364`가 검증된 checkout 프로세스지만 manifest 소유 runner가 아니므로 원래 API 터미널에서 Ctrl+C가 필요하다고 반환했다. 어떤 서비스도 중지되지 않았다.
- 감사: `agent.p5_codex_157.restart_started` ID `694103`; `agent.p5_codex_157.restart_blocked` ID `694104`.
- 재개 조건: 사용자가 API 원래 terminal에서 Ctrl+C로 정상 종료한 다음, 같은 develop 반영 절차를 다시 실행한다. 강제 종료하지 않는다.
