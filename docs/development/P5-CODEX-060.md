# P5-CODEX-060 — 원고 상세·발행 조회·한글 문구 장애 수정

- 작업 일시: 2026-10-30 (Asia/Seoul)
- 브랜치: `develop`
- 상태: 발행 조회 API와 Dashboard 장애 수정 완료. 실제 Blogger 공개 게시 미완료.
- 작업 커밋: 이 문서를 포함한 커밋은 `git log`에서 확인한다.

## 변경 이유와 기존 상태

실행 중인 `/publishing`은 503을 발행 정보 오류로 표시했다. 인증된 API 요청과 같은 운영 설정으로 호출한 read model에서 PostgreSQL `42703 UndefinedColumn`이 재현됐다. 현행 `external_content_imports`에는 `google_trends_based` 컬럼이 없지만, 발행 목록 두 쿼리가 이를 직접 참조하고 있었다. 다른 Import read model은 이미 이 필드를 `NULL::boolean`으로 반환하고 있었다.

원고 상세는 닫을 때 `history.back()`에 의존했고, 상세 API 요청이 진행 중일 때 닫으면 늦게 끝난 요청이 시트를 다시 열 수 있었다. 예약 Blogger 발행 영역의 일부 한국어 문자열과 발행 관리의 게시 후 보완 탭 라벨은 실제 `?`로 저장돼 브라우저에도 그대로 나타났다.

## 변경 내용

- 발행 목록과 게시 완료 목록에서 존재하지 않는 저장 컬럼 참조를 `NULL::boolean AS google_trends_based`로 교체했다. 현행 Import read model과 같은 계약을 사용하며 운영 데이터나 마이그레이션은 변경하지 않았다.
- 상세 열기 요청에 세대 토큰을 추가했다. 닫기·다른 원고 선택 후 늦게 도착한 응답은 무시한다.
- 상세 닫기는 현재 URL의 `open_import_id`와 버전 파라미터를 제거하고 현재 항목을 대체한다. `return_to`는 기존 동작대로 유지한다. 닫기 버튼, ESC, 직접 링크, 다른 원고 선택을 실제 브라우저에서 확인했다.
- 예약 Blogger 발행 영역과 게시 후 보완 탭의 깨진 문자열을 정상 UTF-8 한국어 문구로 복구했다.
- 예약 publish-first 정책의 Worker 경로는 이미 존재하여 수정하지 않았다. 일반 기계·편집 품질 플래그를 사후 보완으로 보내는 정책은 유지하고, 출처 원문/핵심 사실/권리 증거·대상 Blogger·OAuth·중복 등 필수 안전 조건은 유지했다.

## 운영 데이터·실행 상태 확인

모든 운영 조회는 읽기 전용이었다. 운영 DB에서 발행 read model은 이제 정상 반환한다. 실제 요약은 대기 0건, 검토 필요 13건, 게시 완료 0건, 실패·보류 1건이며, 전체 최신 원고 대표 13건과 본문 중복 억제 11건이 반환됐다. 과거 게시 데이터는 변경하지 않았다.

예약 원고 Import는 최초 조회 시 4건이었으며, 작업 중 신규 예약 원고가 DB에 자동 수신되어 최종 확인 시 5건이었다. 신규 Import `591866d3-8a41-4d11-a81f-aaa8d324d455`는 수신 약 9초 후 자동 증거 평가됐지만 `no_supported_body_after_sanitization`, `source_live_verification_missing`, `claim_span_not_found_in_live_source_evidence` 사유로 `held`였다. 5건 모두 `awaiting_human_review`, `generation_ready=false`, `publish_ready=false`다. 예약 Auto 정책 이벤트의 최신 action은 `enabled`, 전역 긴급 중지는 꺼져 있고 전역 모드는 `manual`이다. Publication Worker heartbeat는 실행 중, Live queue/due는 0건, 마지막 Job은 과거 Mock 수동 Job의 `quality_held`였다. 적격 예약 Publishing Job은 생성되지 않았고 Blogger 공개 게시 및 URL은 0건이다. 본문 정제 후 근거가 뒷받침하는 본문이 남지 않은 원고는 안전 조건에 따라 계속 보류했다.

## 수정 파일

- `apps/dashboard/app/imports/external-import-workspace.tsx`
- `apps/dashboard/app/publishing/publication-manager.tsx`
- `services/api/woori/publications.py`
- `services/api/tests/test_publications.py`
- `docs/development/P5-CODEX-060.md`

## 검증

- API: `pytest services/api/tests/test_publications.py services/api/tests/test_scheduled_publish_first.py -q` — 36 passed. 격리된 `woori_blog_agent_test` 사용.
- Python lint: Ruff — 통과.
- Dashboard: TypeScript typecheck, 관련 파일 ESLint, Production Build — 통과.
- Production runtime: 기존 프로젝트 스크립트로 API와 Dashboard를 정상 종료·재시작. Dashboard는 격리 dist `.next-p5-codex060b`에서 실행. API `/health`와 same-origin `/api/publications` 모두 200.
- 실제 브라우저 `http://127.0.0.1:3100/publishing`: 발행 API 오류 문구 없음, 13건 검토·0건 게시·1건 실패/보류 표시, `게시 후 보완` 탭 표시, 콘솔 page error 없음.
- 실제 브라우저 `/imports`: 상세 닫기 버튼, ESC, 다른 원고 선택, `open_import_id`가 있는 직접 링크 열기/닫기 확인. 닫은 뒤 상세 파라미터가 정리되고 시트가 재오픈되지 않았다.
- Codex 예약 원고 상세의 `다국어·발행` 탭에서 `Blogger 예약 발행` 영역과 정상 한글 상태 표시 확인. Blogger API 쓰기 호출은 하지 않았다.
- 스크린샷(작업 폴더 `.runtime`): `p5-c060-publishing-final.png`, `p5-c060-scheduled-detail.png`.
- `git diff --check` 통과.

## 남은 문제

실제 Blogger 게시 URL은 없다. 예약 원고 4건의 출처 원문·주장·권리 근거가 검증되어 적격 처리되고 Live Job이 생성되기 전까지 Worker는 게시하지 않는다. 현재 실행 중인 Research Worker 및 Publication Worker는 종료·재시작하지 않았다. 본 변경은 실제 Blogger 쓰기 권한, Auto 설정 또는 원고 검증 상태를 변경하지 않았다.
