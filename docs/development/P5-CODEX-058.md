# P5-CODEX-058 — 예약 원고 최초 공개 게시 승인 제거

- 작업 시각: 2026-10-30 (Asia/Seoul)
- 브랜치: `develop`
- 작업 상태: 예약 정책·발행 게이트 변경 및 런타임 적용; 실제 Blogger 공개 게시 미완료
- 커밋: 후속 기록은 `git log`의 P5-CODEX-058 커밋 참조

## 목적과 기존 상태

예약 Auto 정책 이벤트가 이미 네 등록 Blogger를 허용하고 있었지만, 별도 `scheduled_first_publication_events` 행이 없으면 신규 Publishing Job 생성과 실제 dispatch를 막았다. `/scheduled-auto-first-post` API/UI도 개별 첫 게시 승인을 요구했다. 이 조건은 사용자의 새 정책과 맞지 않았다.

예약 Auto의 명시적 운영 범위 활성화 이벤트를 첫 게시와 이후 게시의 운영 승인으로 사용하도록 변경했다. 과거 최초 게시 감사 행은 보존하며 신규 예약 발행에는 읽거나 쓰지 않는다. 이전 예약 Auto 정책 이벤트의 사유도 append-only 이력이므로 수정하지 않았다.

## 변경 사항

- 예약 Job 생성 및 live dispatch에서 최초 게시 이벤트 존재 검사를 제거했다. 활성 예약 Auto 정책, 대상 Blogger 범위, 긴급 정지, Blogger 쓰기 OAuth/zero-cost 외부 정책, 사실·권리 검증, 중복·멱등성 및 발행 한도 확인은 유지했다.
- 예약 상태 응답은 `first_publication_approval_required=false`, `effective_for_new_jobs`를 활성 정책 기준으로 반환한다. 최초 승인 POST는 HTTP 410으로 종료하며 감사 DB를 변경하지 않는다. 레거시 이벤트 테이블과 과거 행은 유지된다.
- 외부 Blogger 공개 쓰기는 가장 최근 예약 정책 이벤트가 `enabled`이고 대상 Blogger가 해당 이벤트 범위 안에 있을 때만 예약 Worker 컨텍스트에서 허용된다. 나중의 `disabled` 이벤트는 과거 활성 기록을 무효화한다.
- Dashboard의 예약 Auto 영역에서 최초 게시 승인 버튼/영역을 제거하고, 승인 범위가 첫 게시에도 적용됨을 안내한다. 수동 원고는 별도 명시적 Blogger 공개 게시 경로를 유지한다.
- `AGENTS.md`에 현재 예약 정책을 명시하고 과거 첫 게시 승인 규칙과 충돌하던 발행 지침을 정합화했다. `publish_ready`, 기계 검사 또는 사람 검토 결과를 임의로 통과 처리하지 않는다.

## 운영 상태 확인

- 예약 Auto 정책은 네 등록 블로그에 활성화되어 있었다. 블로그 ID: 한국어 `3321654108096579717`, 영어 `5240203250707821039`, 일본어 `7562596540375659150`, 중국어 간체 `1931836538202286191`.
- 전역 모드는 `manual`, 전역 Auto 승인은 꺼져 있고 긴급 정지는 꺼져 있다. 예약 전용 정책은 분리되어 활성이다. 예약 Worker heartbeat는 최신이며 `scheduled-auto-manual` 모드다.
- 최초 공개 승인 이벤트는 0건이어도 새 코드에서 예약 Auto Job을 막지 않는다. 예약/실제 발행 대기열은 0건이다.
- 기존 예약 원고들은 새 Job을 만들 수 있는 근거 상태가 아니었다. 특히 일본어 import `9bd1706b-5e0a-4cb4-a7fd-d4949b9ecad7`은 sanitizer 후 게시 가능한 본문이 없고, 실제 출처 확인 및 주장 연결 근거가 누락된 감사 결과가 있다. 이를 통과 처리하거나 발행 큐에 넣지 않았다. 다른 점검 원고도 게시 적격 증거가 부족했다.
- Blogger 실제 공개 게시: **0건**. postId/공개 URL 없음. 따라서 실제 첫 게시 성공으로 판정하지 않는다.

## 검증

- API 회귀 테스트 (`test_publications.py`, `test_blogger_live_policy.py`): **55 passed**. 예약 Auto 활성 + 최초 승인 없음에서 Job 생성, 최초 승인 API HTTP 410/no DB write, 비활성·범위 밖 정책 차단을 확인했다.
- Ruff: 통과
- Dashboard TypeScript: 통과
- 변경 컴포넌트 ESLint: 통과
- Dashboard production build: 통과
- `git diff --check`: 통과
- API health 및 Dashboard 경로: HTTP 200
- Worker status: heartbeat fresh, Scheduled Auto policy enabled, 예약 대기 Job 0. Worker는 재시작하지 않았다.
- 실제 Blogger POST/실제 게시: 실행하지 않음. 게시 가능한 원고가 없어 발행 작업을 만들지 않았으며, 외부 쓰기 결과를 주장하지 않는다.

## 수정 파일

- `AGENTS.md`
- `apps/dashboard/app/api/publications/[[...path]]/route.ts`
- `apps/dashboard/app/imports/external-import-workspace.tsx`
- `apps/dashboard/app/publishing/publication-manager.tsx`
- `services/api/tests/test_blogger_live_policy.py`
- `services/api/tests/test_publications.py`
- `services/api/woori/external_policy.py`
- `services/api/woori/publication_worker.py`
- `services/api/woori/publications.py`
- `docs/development/P5-CODEX-058.md`

## 남은 제한

최초 게시 승인은 더 이상 필요하지 않다. 실제 발행에는 기존 자동 검증으로 게시 가능한 본문이 있는 예약 원고가 필요하다. 현재 원고는 핵심 출처·사실 근거 조건을 충족하지 못하거나 정제 후 본문이 남지 않아 보류 상태다. 새로 Import되는 예약 원고가 사실·권리·대상 블로그·중복 검사를 통과하면 별도의 첫 게시 버튼 없이 기존 활성 예약 Auto 범위에서 Worker가 처리한다.
