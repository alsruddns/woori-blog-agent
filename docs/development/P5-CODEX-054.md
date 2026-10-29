# P5-CODEX-054 — 원고 관리·발행 관리 통합 개선

- 작업 시각: 2026-10-30 KST
- 브랜치: `develop`
- 작업 기준 HEAD: `64a8fc4` (`Fix : [scheduled-import] Add audited quarantine retry`)
- 변경 목적: 원고 생성 경로 구분, Qwen/llama 과거 평가 원고의 기본 목록 제외, 발행 목록에서 정확한 원고 상세 연결, 수동 Import의 별도 Blogger 발행 요청 경로 제공, 예약 원고 publish-first 평가에서 경미한 검사 누락을 보완 항목으로 기록
- 기존 문제: 발행 목록 행이 원고 상세를 정확히 열지 못했고, 생성 경로를 구분하기 어려웠다. 수동 Codex Import에는 예약 Auto와 구분되는 명시적 발행 요청 UI가 없었다. 예약 발행 평가의 일반 품질 준비 플래그가 증거·권리 검토와 별도로 차단 이유가 되었다.

## 변경 전후

- 기본 원고 목록에서 Qwen/llama 평가 결과를 제외하고, `include_retired_models=true`로 보관 자료를 조회할 수 있게 했다. 과거 원고와 기록은 삭제하지 않는다.
- 외부 Import와 발행 목록에 Codex 예약, 수동 Import, Google Trends, 기타/내부 원고의 생성 경로를 표시하고 필터링한다.
- 발행 목록은 Import ID 또는 evaluation ID와 정확한 content version ID를 상세 화면에 전달한다. 닫으면 안전한 내부 경로로 이전 발행 목록 상태를 복원한다.
- 수동 Codex Import 상세에 대상 Blogger, 본문 SHA-256, 서버 평가 결과를 표시하고 명시적 공개 발행 요청 UI를 연결했다. 요청은 기존 서버 승인·품질·권리·중복·쓰기 게이트를 거치며 예약 Auto 정책을 변경하지 않는다.
- 예약 publish-first 검사에서 `machine_passed`, `generation_ready`, `publish_ready`의 false/missing 값은 저장 상태를 변경하지 않고 보완 항목으로 반환한다. 정제된 usable HTML, 사실·출처·권리·중복·대상·운영 승인·쓰기 차단은 유지한다.
- `AGENTS.md`의 Phase 5 scheduled-auto 운영 규칙에 위 제한된 동작을 명시했다.

## 변경 파일

- `AGENTS.md`
- `apps/dashboard/app/api/publications/[[...path]]/route.ts`
- `apps/dashboard/app/imports/external-import-workspace.tsx`
- `apps/dashboard/app/manuscripts/workspace.tsx`
- `apps/dashboard/app/publishing/publication-manager.tsx`
- `services/api/woori/content_imports.py`
- `services/api/woori/publications.py`
- `services/api/woori/publication_worker.py`
- `services/api/woori/research_routes.py`
- `services/api/tests/test_dashboard_read_models.py`
- `services/api/tests/test_scheduled_publish_first.py`

## 검증과 운영 상태

- Python focused regression: `test_scheduled_publish_first.py`, `test_dashboard_read_models.py`, `test_publications.py`에서 38/38 통과. Dashboard read-model 테스트 fixture를 새 감사 조회에 맞게 업데이트했다.
- 별도 초기 선택 테스트 중 content import endpoint 테스트 1건은 테스트 DB의 현재 migration/capability 상태 때문에 503을 반환했다. 운영 DB에 migration을 적용하거나 데이터를 변경하지 않았다.
- Dashboard: 변경 파일 ESLint 통과, `next typegen && tsc --noEmit` 통과, `git diff --check` 통과.
- 실제 Chromium E2E: 격리 개발 서버 `127.0.0.1:13100`에서 원고 목록 필터·페이지·상세·키보드 닫기 테스트 데스크톱 1건 및 모바일 1건 통과. 격리 서버는 종료했고, 생성된 Next 설정 변경은 복구했다. 운영 3100 Dashboard는 이 작업에서 교체하거나 재시작하지 않았다.
- Production build는 현재 실행 중인 3100의 공유 build 산출물을 덮어쓸 수 있어 실행하지 않았다.
- 읽기 전용 `scripts/status.ps1` 기준: Dashboard 52112/3100, API 51500/8100, Research Worker runner/child 21700/43420, Publication Worker runner/child 37120/47188 및 heartbeat가 checkout 경로와 일치했다. Live/Mock 큐는 0, 마지막 항목은 `quality_held`, 일반 운영 모드는 `manual`, 예약 Auto 활성 상태는 false였다. 서비스는 종료하지 않았다.
- 실제 Blogger 쓰기, 승인 기록, Auto 설정 변경은 수행하지 않았다. 실제 게시 0건이며 공개 URL 없음. 최신 실제 DB 승인 상태를 변경하거나 게시를 완료한 것으로 주장하지 않는다.
- 서비스별 append-only 운영 DB 이벤트를 추가하는 작업은 수행하지 않았다. 이 개발/검증 실행은 격리 테스트와 읽기 전용 운영 상태 점검으로 제한했다.

## 남은 문제

- 제공된 `AGENTS.md`의 Phase 2는 실제 Blogger POST 경로를 명시적으로 비활성화하고, Phase 5 승인 규칙은 별도 사람 편집 승인과 운영 승인을 요구한다. 이 정책 아래서는 live request UI가 게이트를 통과할 수 있어도 공개 쓰기를 실행하지 않는다.
- 현재 관측된 런타임에서 예약 Auto는 비활성화되어 있고 발행 가능한 작업도 0건이다. 사용자가 실제 공개 발행을 원하면 운영 정책 문서/권한을 먼저 일치시킨 뒤 별도 허용된 승인 경로를 사용해야 한다.
- 단일한 기존 fixture 오류와 test DB capability 오류는 해결 범위 밖으로 남겼다.

## Git

- 커밋 해시: 본 문서 작성 이후 `git log`에 기록
- 원격 푸시: 완료 후 실제 결과를 후속 기록/작업 보고에 기재
- 관련 문서: `AGENTS.md`; 본 기록의 커밋·푸시는 `git log` 및 `origin/develop` 상태로 연결
