# P5-CODEX-144 — 발행 실패 원인과 조치 안내 개선

- 작업 일시: 2026-11-05 14:09 KST 시작, 종료 시각은 최종 감사 이벤트 기준
- 작업 브랜치: `develop`
- 시작 HEAD: `5e6ff180780c74838b61de655fe07ad5049be32d`
- 작업 시작 감사 이벤트: PostgreSQL `audit_events` ID `373189` (실행 전 기록으로 전달됨)
- 변경 사유: 발행 실패 화면에 `automatic_quality_or_policy_blocked` 같은 내부 코드만 표시되어 사용자가 원인과 해결 방법을 알기 어려웠음. KO Trends 원고의 수동 발행 차단 사례도 `source_verbatim_excerpt_present`를 반환했으나 문구가 사용자 조치로 번역되지 않았음.
- 변경 전: 여러 화면에서 서로 다른 짧은 코드 사전 또는 snake_case 코드가 노출됨. 자동 발행 적격성 실패는 일반 카테고리만 저장되어 세부 차단 사유를 실패 화면에서 복구할 수 없었음.
- 변경 후: 공통 한국어 원인·다음 조치 메시지를 사용하고, 기술 코드는 상세 정보로 남김. 자동 발행 차단 시 기존 실패 카테고리와 함께 실제 차단 사유 코드를 `publishing_jobs.block_reasons`에 저장하고, 모니터 API에서 이를 전달함.

## 구현

- 공통 메시지 사전은 출처·주장 근거·저작권·품질·SEO·HTML·중복·OAuth·블로그 매핑·운영 정책·발행 간격 및 한도·Worker/Blogger 오류를 사용자용 한국어 설명과 다음 조치로 안내한다.
- `automatic_quality_or_policy_blocked`는 세부 원인을 살펴보도록 안내하며, 현재 사례인 `source_verbatim_excerpt_present`는 원문 문구를 직접 사용하지 않게 다시 쓰고 새 버전으로 저장한 뒤 재평가하도록 안내한다. 안전·권리·근거 차단 조건은 완화하지 않았다.
- 발행 관리, Import 원고 상세/수동 발행, 예약 발행 상태, Publication Worker 실패 상세, 자동 발행 설정의 차단 안내를 공통 변환기로 연결했다. 여러 원인이 있으면 전체 원인과 조치를 표시한다.
- API가 내부 코드만 반환하거나 알려진 코드가 설명에 포함된 경우 한국어 안내로 바꾸고, 기술 코드와 Job 식별 정보는 상세 확인에 남긴다.
- 자동 발행이 적격성 사유로 막힌 경우 구체 사유를 Job에 보존해 이후 상태 조회에서도 표시한다.

## 변경 파일

- `apps/dashboard/app/publishing/publication-messages.ts` (신규)
- `apps/dashboard/app/publishing/publication-manager.tsx`
- `apps/dashboard/app/publishing/publication-worker-panel.tsx`
- `apps/dashboard/app/imports/external-import-workspace.tsx`
- `apps/dashboard/app/operations/automation/controls.tsx`
- `services/api/woori/automation_auto.py`
- `services/api/woori/publication_monitor.py`
- `services/api/woori/publications.py`
- `services/api/tests/test_automation_controls.py`
- `services/api/tests/test_publication_monitor.py`
- `docs/development/P5-CODEX-144.md`

## 검증

- 통과: `pytest services/api/tests/test_automation_controls.py services/api/tests/test_publication_monitor.py -q` — 40 passed. pytest cache 경고 1건은 캐시 경로 권한 문제이며 테스트는 통과함.
- 통과: Ruff 대상 파일 5개 — `All checks passed!`
- 통과: `npm run lint`
- 통과: `npm run typecheck`
- 통과: `npm run build` (Next.js production build)
- 통과: `git diff --check`
- 자동 발행 사유 영속화와 모니터 API 노출을 위한 회귀 테스트를 추가함.
- 실제 Blogger 쓰기 0건. 기존 OAuth, 게시 이력, 예약 및 Job 데이터 변경 0건.
- 서비스 재기동 및 운영 배포는 수행하지 않음. 현재 변경은 코드·테스트이며, 실행 중인 API/Worker 및 사용자 화면에는 운영 반영 전까지 적용되지 않음.

## 남은 점과 커밋

- 실행 시각의 세부 기록, 최종 HEAD/커밋, 원격 푸시 결과는 후속 커밋 및 감사 완료 이벤트와 연결한다. 자기 참조 커밋은 `git log`로 확인한다.
- 기존 실패 Job 중 과거에 세부 차단 사유를 저장하지 않은 건은 새 상태 조회에서 일반 오류만 보일 수 있음. 과거 Job이나 발행 이력은 소급 수정하지 않는다.
- 수정된 코드가 실제 운영 화면과 Publication Worker에 반영됐는지는 운영 배포·정상 재기동 뒤 별도로 확인해야 한다.
