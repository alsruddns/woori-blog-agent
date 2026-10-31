# P5-CODEX-097 — 원고 작성 자동화 유지 / Blogger 수동 API 전용

- 작업일: 2026-10-31 KST. 시작 develop HEAD: ed84903.
- 원인: Google Blogger 스팸/접근 제한 안내 및 실제 403 이력. 자동 Draft/공개/수정/재시도를 중단한다.
- 최종 사용자 지시: `blogger_write_mode=manual_only`; 신규 수동 요청 기본 `publish`, 선택 `draft`. 공개는 최종 확인 필수. 원고 작성과 게시를 분리한다.

## 운영 안전 조치 및 체크포인트

1. 기존 인증된 emergency-stop API로 긴급 정지 저장(HTTP 200, real_writes_enabled=false).
2. checkout 소유 Publication Worker PID 52260을 기존 stop 스크립트로 정상 종료. 강제 종료·기존 Job 삭제 없음.
3. 운영 pg_dump 백업 및 pg_restore 목록 검사 후 additive 074 적용. 최초 authoring_only 중지 감사 기록: 2026-10-31 19:10:15 KST.
4. 사용자의 최종 manual_only 지시 반영: 추가 백업 후 075 적용. 이미 적용한 074는 변경하지 않음. manual_only 전환 감사 기록: 19:13:49 KST.
5. 운영 Google 제한 플래그와 긴급 정지는 유지. 제한 해제를 추정하지 않으며 운영 Google 쓰기 테스트 없음.

## 변경 전후

- 이전: Trends/Scheduled Auto Worker가 Draft/공개 Job을 자동 실행할 수 있었음.
- 이후: 자동 enqueue/실행은 중지. 기존 정책 이벤트는 감사용 그대로 보존. 새 수동 요청만 정확한 버전·해시·블로그·모드 및 승인 이벤트에 연결한다.
- 실제 전송 직전에 영속 manual_only 정책, Google 제한, 긴급 정지, 새 수동 승인 시각, running Job, 정확한 버전/해시를 재확인한다. DB 오류·설정 누락·context 누락은 차단한다.
- 전환 이전 Job은 자동 복구하지 않는다. 이후 모드 선택 변경도 기존 Job 모드를 바꾸지 않는다.
- API 403 쓰기 응답은 제한/긴급 정지를 영속 기록하고 재시도하지 않는다. 비밀값 대신 기존 sanitized provider reason/category/status를 감사한다.
- 수동 Draft는 기존 create_draft/readback/receipt 경로, Publish는 기존 draft/publish/LIVE 경로를 재사용한다.
- 수동 UI: 기본 publish, draft 선택·사용자 선택 저장, 공개 확인창, API 제한 안내, 제목/본문/전체/SEO/HTML 복사, Blogger 관리자 링크.
- Google Trends 10분/11개 지역, Codex Runner, Import, 15개 Desktop RRULE는 변경하지 않음. Import 성공을 발행 비활성 때문에 실패 처리하지 않음.

## 데이터 보존

중지 후 실제 조회: succeeded 20 / failed 15 / queued 1 / blocked 1. 과거 기록의 상태를 성공/실패로 재작성하지 않음.

- 보존된 queued Trends Job: `7d6c8069-d456-4740-b6b2-7d6da04673c9`, Version `87ddaf53-28dd-4a74-9469-3b2fc447269c`.
- 보존된 blocked manual Job: `2f4f9c71-f67c-4a76-88d7-a7f2883fb8f4`.
- P096의 과거 5건과 현재 실제 개수는 다름. 현재 조회를 기준으로 보고하며 과거 개수로 조작하지 않음.
- Codex 이력: imported_review 26 / failed 30 / cancelled 2 (중간 운영 조회). 기존 결과 보존.

## 검증

- 전용 격리 DB schema 75, test app의 운영 DB CONNECT 거부 확인.
- 집중 pytest 최종: **34 passed, 37 deselected**. 원고 작성/Import·출력 분기 회귀, 모든 HTTP 쓰기 종류 차단/전송 0회, Worker 반복 tick/Job 불변, 새 수동 모드별 확인값, 4개 언어의 수동 요청·멱등성·모드 스냅샷·Draft receipt·공개 복구 SQL, 403 이후 추가 POST 차단 포함.
- 실제 Google로 게시하지 않는 Mock/격리 검증만 수행. 기존 공개 복구 테스트의 LIVE 응답은 모의 결과다.
- 변경 Python 7개 모듈 mypy 통과, production 모듈 Ruff 통과.
- 최종 Dashboard 빌드·브라우저·런타임 반영 결과는 후속 체크포인트에 기록한다.

## 수정 파일

`scripts/074_authoring_only.sql`, `075_manual_only_blogger.sql`, migration/test provisioning;
`publication_operation.py`, `publication_modes.py`, `publications.py`, `publication_worker.py`, `trends_publication.py`, `external_policy.py`, `blogger_writes.py`;
Dashboard layout/중지 안내/Trends 정책/수동 모드/복사 기능;
집중 API 테스트 및 본 기록, zero-cost 운영 문서.

## 남은 제한 및 Git

Google API 제한과 긴급 정지 때문에 운영 수동 Draft/Publish는 현재 차단된다. 계정·OAuth·프로젝트 교체나 반복 POST를 하지 않는다. 실제 제한 해제 증거와 운영 검토 없이 플래그를 해제하지 않는다.

이번 작업에서 새로운 실제 Blogger Draft 또는 LIVE 성공을 주장하지 않는다. 원고 생성 실모델 호출을 추가하지 않고 기존 작성·Import 경로의 격리 회귀와 운영 heartbeat를 확인한다.

커밋 자기 참조는 `git log --grep P5-CODEX-097` 및 후속 검증 기록으로 연결한다. main 변경 없음.

## 최종 통합 검증 및 운영 반영

- 구현 체크포인트: `63940b7`, `64d04c5`, `b16592d`. 최종 기록/브라우저 테스트 커밋은 git log로 연결.
- Dashboard ESLint·typecheck·Production Build 최종 통과. 최초 lint의 동기 effect 상태 변경을 lazy initializer로 수정. 브라우저에서 정상 Trends Import의 수동 영역이 숨겨졌던 조건도 발견하여 모든 Import 원고에 표시하도록 수정했다. 실패를 무시하지 않고 변경 후 다시 검증했다.
- 실제 Chromium: **4 passed**, desktop 1440px / mobile 390px. `/sources`, `/publishing`, `/manuscripts` 중지 안내·가로 스크롤 없음; 실제 저장 원고 상세·복사 버튼·publish 기본값·draft 선택·공개 취소 시 요청 0건·명시적 클릭 모드 전달 확인. 발행 요청은 모두 Playwright route mock으로 가로채 운영 Job/Blogger POST를 생성하지 않았다. 테스트 종료 시 진행 중 route handler를 기다리도록 수정한 뒤 종료 코드 0 확인.
- API·Dashboard·Research Worker 정상 종료 후 재시작. Publication Worker는 `operations-manual-confirmed`로 재시작. 기존 combined 모드로 시작하더라도 백엔드는 자동 lane을 실행하지 않는다.
- API `/health` HTTP 200, `/admin/publications/mode-settings` HTTP 200: `blogger_write_mode=manual_only`, `blogger_api_restricted=true`, `emergency_stopped=true`, `real_writes_enabled=false`.
- Research/Publication heartbeat running/fresh 확인. API·Worker 소스 `64d04c5`; 최종 Dashboard `b16592d` 소스 기반 `.next-p5-p097-final`. 이후 테스트/문서 변경은 실행 소스에 영향 없음.
- 중지 시각 이후 **Google Blogger external 감사 이벤트 자체가 0건**. Job 개수 succeeded20/failed15/queued1/blocked1 불변. 기존 원격 게시물 수정·삭제/계정·OAuth 교체 없음.
- 수집이 작업 시작 전 **18:57에 OFF**로 저장된 것을 마지막 점검에서 발견했다. 최신 사용자의 원고 자동화 ON 요청에 따라 기존 인증된 `PUT /admin/research/trends/settings`로 `enabled=true, interval_minutes=10` 저장(HTTP200, 다음 경계19:30 KST). 스케줄 코드·국가·작성 로직 변경 없음. 허용 11지역 AU/CA/GB/HK/IN/JP/KR/PH/SG/TW/US 유지. 기존 작성 매핑 AU/CA/GB/IN/JP/KR/PH/SG/US 활성 유지, ZH 임의 매핑 없음.
- 새 실모델 작성/새 운영 Import 완료는 이번 검증에서 주장하지 않는다. 기존 최신 Trends Import `f58c8668-fb46-4d0e-9462-eb0ec116c764`(18:25 KST) 보존; 작성 및 Import 회귀는 격리 테스트로 확인했다. 15개 Desktop 설정 파일/RRULE는 수정하지 않았다.
- Google 제한 해제/쓰기 허용 증거가 없으므로 **운영 수동 Draft/LIVE 검증은 미실행**. 관리자 승인·제한 해제·쓰기 검증을 조작하지 않았다. 계정 복구 전 버튼 비활성은 의도한 보호 동작이다.
- 기존 미추적 `.playwright-mcp/` 두 폴더는 수정·삭제·커밋하지 않았다.
