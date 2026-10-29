# P5-CODEX-034 — 발행·자동화 운영 화면 정리

- 작업 일시: 2026-10-29 KST
- 작업 ID: `P5-CODEX-034-ui`
- 작업 브랜치: `develop`
- 변경 사유: 발행 관리가 과거 콘텐츠 버전과 테스트 원고를 최신 발행 후보와 함께 표시해 중복·혼동을 일으켰고, 자동화 메뉴가 운영자에게 과거 모델 평가 화면을 기본 노출했다.
- 기존 문제: 발행 목록 API가 최신 100개 버전 레코드를 반환했다. 운영 DB의 100행은 32개 콘텐츠 그룹, 63개 localization을 포함했고, FOMC 계보 하나에 한국어 버전 7개가 있었다. `revised`, `localized` 및 Mock 검증 원고도 현재 후보와 섞여 있었다.
- 변경 목적: 콘텐츠 버전을 삭제하지 않고 대표 원고와 상태를 일관되게 표시하고, 운영자가 수집·원고·검증·Blogger 상태를 한 화면에서 확인하도록 한다.
- 변경 전 상태: API 후보는 과거 버전 기준 최근 100행. 자동화 메뉴는 연구·모델 평가 UI를 렌더링. 게시 URL 집계는 실제 원격 확인 여부와 분리되지 않은 레코드 수를 사용할 여지가 있었다.
- 변경 후 상태: `(group_id, localization_id, active blog)`별 최신 버전으로 대표 목록을 구성한다. 최신 제목이 `revised`/`localized` 등 임시 표식이거나 명시적 Mock/Test 원고인 경우 목록에서 제외한다. 본문 hash가 같은 대표 원고는 같은 언어·블로그 안에서 한 번만 노출한다. API가 검색, 언어·블로그 필터, 상태 필터, 페이지네이션 및 상태별 전체 요약을 제공한다. 과거 콘텐츠·평가·감사 데이터는 보존된다.

## 운영 DB 판독 결과

DB는 읽기 전용으로 조회했다. 스키마 버전은 48이다.

- 당시 발행 관리 API의 최근 100행: 100개 content version, 32개 group, 63개 localization.
- 전체 고유 최신 대표 행: 244개. 그중 222개는 최신 제목이 `revised` 또는 `localized` 등 임시 제목이었고, 4개는 `MOCK pipeline verification … TEST ONLY` 표식이 있었다. 이 226개 행은 발행 후보 목록에서 숨겼으며 원본 레코드와 감사 이력은 수정·삭제하지 않았다.
- 현재 운영 발행 목록: 발행 대기 0, 검토 필요 18, 검증된 실제 게시 0, 실패·보류 작업 1(모의 작업).
- 정확히 동일한 본문 hash로 추가 억제된 항목은 0건이다. 다른 분석을 같은 사건이라는 이유만으로 합치지 않는다.
- FOMC 계보에는 기존 한국어 버전 7개가 남아 있다. 목록은 최신 버전만 대표로 표시하고 이력은 상세 화면에서 유지한다.
- 게시 적격 후보는 현재 0건이다. 실제 자동 발행 권한이나 사람 승인 상태를 변경하지 않았다.

## 변경 파일

- `services/api/woori/publications.py` — 최신 대표 선택, 임시·Mock 제목 제외, hash 중복 억제, 상태 요약·필터·페이지 API.
- `services/api/woori/operations_dashboard.py` — 원격 Blogger에서 `LIVE` 및 GET 확인된 게시만 실적에 집계, 실제 대기 작업·최근 검증 게시 URL 제공, 민감 payload 없이 최근 감사 이벤트 종류·시각 제공, 예약 Import 집계 보강.
- `services/api/tests/test_publications.py` — 동일 본문 중복 판정 테스트.
- `apps/dashboard/app/publishing/publication-manager.tsx` — 발행 대기/검토/게시 완료/실패·보류 목록, 검색·필터·페이지네이션, 간소화된 행 및 실제 확인 URL 표시.
- `apps/dashboard/app/publishing/page.tsx` — 실제 대표 목록 설명.
- `apps/dashboard/app/operations/research/page.tsx` — 기존 자동화 경로를 운영 현황 화면으로 연결.
- `apps/dashboard/app/operations/research/automation-dashboard.tsx` — 수집, 공식 자료·원고, 품질, Blogger 발행 4단계와 Worker·최근 실행 상태.
- `apps/dashboard/app/operations/page.tsx` — 개발·모델 비교 링크를 기본 운영 메뉴에서 제거하고 자동화 관리로 연결.
- `apps/dashboard/app/navigation.tsx` — 자동화 관리 링크에서 제거된 anchor fragment 정리.
- `apps/dashboard/app/style.css` — 모바일 발행 행 카드 레이아웃 및 자동화 화면 반응형.
- `docs/development/screenshots/P5-CODEX-034-*.png` — 브라우저 캡처.

스크린샷: [발행 관리 데스크톱](screenshots/P5-CODEX-034-publishing-desktop-1366x768.png), [발행 관리 모바일](screenshots/P5-CODEX-034-publishing-mobile-390x844.png), [자동화 관리 데스크톱](screenshots/P5-CODEX-034-automation-desktop-1366x768.png), [자동화 관리 모바일](screenshots/P5-CODEX-034-automation-mobile-390x844.png).

## 검증 결과

- 변경 범위 pytest: `services/api/tests/test_dashboard_read_models.py`, `test_publications.py`, `test_publication_daily.py` — 33 passed.
- Ruff — 통과.
- Dashboard TypeScript typecheck — 통과.
- Dashboard ESLint — 통과.
- 수정 API read-only 진단: 0.26초, 대표 원고 18건 / 페이지 25 / 전체 페이지 1. 화면 API 요약은 발행 대기 0, 검토 필요 18, 게시 완료 0, 실패·보류 1.
- 운영 Dashboard snapshot read-only 진단: 캡처 시점 최근 Trends 관측 590건, Research Package 1건, 예약 GPT 실행 0건, 실제 게시 0건, 실제 대기 작업 0건. 감사 목록은 이벤트 종류·시각과 안전한 분류/제목만 반환하며 원시 payload는 노출하지 않는다.
- Playwright: 1366×768 및 390×844에서 발행 관리·자동화 관리 각각 확인. 발행 행 18개, 자동화 4단계, document 가로 overflow 없음, 페이지 JavaScript 오류 0건.
- 브라우저 캡처의 발행 목록 fetch는 수정된 읽기 전용 Python API 함수를 통해 실제 운영 데이터 snapshot을 반환하도록 Playwright 경로에서 가로챘다. 운영 API 프로세스 자체를 재시작하거나 변경하지 않았다. 자동화 화면은 실제 `/admin/operations/dashboard` read-only API 응답을 사용했다.
- 추가로 관련 `test_integration.py`를 실행했을 때 기존 기대값 불일치 1건이 확인됐다: `hourly_limit_status` 실제 `configured_internal_cap`, 테스트 기대 `not_configured`. 이번 UI 작업과 무관한 기존 계약 차이여서 수정하지 않았다.
- 실제 Blogger 게시 또는 쓰기 호출 없음. Auto OFF, 운영 모드 manual 유지.

## 프로세스 적용 상태 및 남은 문제

현재 API PID 27728은 `uvicorn woori.main:app --host 127.0.0.1 --port 8100 --no-access-log`로 실행 중이고 reload 옵션이 없다. Dashboard PID 47616은 `next start --hostname 127.0.0.1 --port 3100`으로 실행 중이다. 두 프로세스는 사용자 소유 실행 프로세스이므로 임의 종료하지 않았다. 따라서 운영 API 8100과 3100의 기존 서비스는 이 코드 변경을 아직 제공하지 않는다. 새 코드를 실제 운영 화면에 적용하려면 원래 터미널에서 API와 Dashboard를 정상 재시작해야 한다. 포트·OAuth·Auto 설정은 바꾸지 않았다.

기존 API process에서 새 API 응답을 확인하지 못했으므로 완전한 운영 런타임 적용은 미완료다. 실제 게시 가능 원고와 공개 게시 URL도 0건이다. Auto는 비활성 상태를 유지한다.

## 후속 상태

- 관련 문서: `docs/development/P5-CODEX-034-ui.md`
- 커밋 해시: 커밋 후 `git log`에서 확인
- 원격 푸시: 커밋 후 확인
- 남은 문제: 사용자 소유 API·Dashboard 프로세스의 안전한 정상 재시작 후 운영 포트에서 새 API/UI 응답을 다시 확인해야 한다.
