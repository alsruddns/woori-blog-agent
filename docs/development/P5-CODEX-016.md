# P5-CODEX-016 — Blogger 자동 게시 경로 및 로컬 운영 검증

기록 시각: 2026-10-29 (Asia/Seoul)
브랜치: `develop`
상태: **부분 완료 — 무인 공개 자동 포스팅 미완료**

## 결과

실제 Blogger 공개 게시와 Auto 운영은 활성화하지 않았다. 계정의 Google Cloud 프로젝트별 Billing·Blogger quota를 현재 Console에서 확인하지 못했고, 기존 append-only Blogger 비용 승인 범위에는 비공개 초안 생성만 있으며 공개 게시·무인 Auto는 포함되어 있지 않다. 생성 Provider도 연결되어 있지 않다. 이 조건들을 코드 설정으로 우회하지 않았다.

이번 작업에서 실제로 실행된 콘텐츠 원천 호출은 Google Trends RSS의 한국(KR) GET 1회다. HTTP 200으로 원천 항목 10건을 운영 DB에 저장했다. Google Trends는 검색 수요 신호이며, 저장된 관측값만으로 기사 사실이나 게시 자격을 만들지 않는다.

## 구현 및 로컬 검증

- `trends.schedule_tick()`를 추가하고 기존 로컬 research Worker에 연결했다. 한 지역을 한 번에 수집하고 지역별 주기는 1시간, 전체 요청 최소 간격은 10분으로 제한한다. 기존 12회/시간 provider cap과 1회/분 limiter를 계속 적용한다. 지역 선택, 간격, 중복 Worker 잠금은 격리 테스트로 확인했다.
- `operations_dashboard`는 앱 역할에 권한이 없는 `schema_migrations` 직접 조회 대신 읽을 수 있는 append-only migration audit marker에서 스키마 버전을 산출한다. 실제 운영 DB를 대상으로 `/admin/operations/dashboard` HTTP 200, schema 48, Worker `running`, Trend 10건, AI Provider `not_configured`, Auto OFF를 확인했다.
- Blogger 외부 호출 allowlist에 초안 공개 전환 endpoint의 정확한 POST 경로 형식을 추가했지만, 이 동작은 별도의 `public_post_publish` 비용 범위를 요구하도록 분리했다. 현재 승인 이벤트에 그 범위가 없으므로 외부 호출은 차단된다.
- `BloggerLivePublisher`의 idempotency ledger, 대상 블로그/쓰기 OAuth 매핑 확인, 제한된 요청 처리 코드를 추가했다. **아직 Manual/Auto publication queue 및 API route에 연결하지 않았고, 라이브 Publisher 통합 완료로 간주하지 않는다.** 공개 게시 흐름은 현재 운영에서 사용할 수 없다. 기존 `/admin/blogger/draft-previews/{id}/confirm` 초안 경로는 별도 구현이며, 이번 실행에서는 호출하지 않았다.

## 현재 실제 상태

- DB schema: 48. Migration 049 추가 및 운영 적용 없음.
- 운영 콘텐츠: `content_versions=360` 유지.
- 운영 Trend: `trend_collection_runs=1`, `trend_observations=10` (KR).
- 게시 기록: `publishing_records=0`.
- 언어별 블로그 연결은 기존 Blogger readonly OAuth 매핑. 쓰기 OAuth 2개는 별도 연결이며 계정 신원 확인 또는 블로그 매핑 변경을 수행하지 않았다.
- 전역 게시 모드 `manual`, `operations_auto_approved=false`; 블로그별 게시 제한도 비활성.
- 현재 연구 Worker는 Windows Task Scheduler `WooriBlogAgent-Worker`에서 실행 중이며 heartbeat 상태 `running` 확인. 이 Worker는 Trend 수집 스케줄을 처리한다. 원고 생성 Provider가 없어 기사 작성·게시 작업은 수행하지 않는다.
- GPT Scheduled Task의 실제 계정 설정, 파일 전달 및 한 번 이상의 예약 결과 Import는 검증하지 못했다. 공식 문서는 프로젝트에 생성된 ChatGPT 예약 작업이 프로젝트 파일을 읽지 못한다고 설명한다. 로컬 파일 접근이 필요한 실행은 데스크톱 앱과 PC 실행 상태가 필요하며, 이 저장소에 예약 결과를 실제로 보내는 공급 경로는 아직 확인되지 않았다. 현재 `woori-content-import/1.0` inbox는 준비된 JSON 파일을 가져오는 수신 경로일 뿐, ChatGPT 예약 작업이 자동으로 파일을 전달하는 연결 증거가 아니다.
- Blogger draft/publication API 호출: 0. Blogger 공개 게시: 0. 추가 유료 AI API 호출: 0. OAuth 토큰이나 비밀값은 기록하지 않았다.

## Google Cloud 사용자 확인 필요

현재 Console에서 프로젝트별 상태를 확인하지 못했다. 다음 사항을 프로젝트 소유자가 Google Cloud Console에서 확인한 후 기록해야 한다.

1. 실제 OAuth client가 속한 프로젝트에서 Blogger API가 활성화됐는지 확인.
2. 해당 프로젝트의 Blogger API Quotas & System Limits에서 현재 quota 및 사용량을 확인.
3. Billing 연결 상태와 자동 과금/예산 알림을 확인.
4. 공식 API 문서는 `posts.insert` 및 `posts.publish` 호출 형식과 OAuth scope를 정의하지만, 이 사실만으로 해당 사용자의 실제 quota/Billing 조건이나 무비용을 확정할 수 없다.

Google Cloud quota는 프로젝트별 값이므로 문서상 endpoint 지원만으로 수치 또는 비용을 추정하지 않는다. [Google Cloud quota 확인 문서](https://docs.cloud.google.com/docs/quotas/view-manage), [Blogger `posts.insert`](https://developers.google.com/blogger/docs/3.0/reference/posts/insert), [Blogger `posts.publish`](https://developers.google.com/blogger/docs/3.0/reference/posts/publish).

## 미완료 및 재개 조건

1. Google Cloud quota/Billing 확인과 별도 append-only 공개 게시 비용 승인.
2. 사용자 Google OAuth 승인 상태로 확인된 쓰기 연결을 정확한 블로그에 감사와 함께 매핑. 계정 신원은 추측하지 않는다.
3. 실 Publisher를 게시 큐와 연결하고, exact-content approval·검증·멱등성·timeout reconciliation 및 공개 페이지 재조회까지 통합 테스트.
4. 실제 원고 공급 경로. 공식 ChatGPT 예약 결과를 로컬 inbox로 전달하는 실제 파일 1건을 end-to-end로 수신·검증하거나, 사용자가 승인한 합법적 무료 Provider를 연결해야 한다. 수동 Import는 무인 자동 생성을 대체하지 않는다.
5. 원고별 사실·권리·최신성·SEO·HTML 검증을 통과한 정확한 버전이 존재해야 한다. 현재 P5-CODEX-009 평가는 검토 미완료이고 `generation_ready=false`, `publish_ready=false`다.
6. 위 선행 조건이 충족된 뒤에만 기존 운영 승인 흐름으로 첫 공개 게시 1건과 공개 URL 검증을 수행한다. 그다음 별도 승인된 블로그 범위의 제한적 Auto 실행 및 다음 예약 주기 반복을 확인한다.

**현재 결론:** 실제 RSS 수집은 성공했고 Worker heartbeat도 정상이다. 실제 AI 원고 자동 생성, Blogger 공개 게시, 다음 예약 주기의 게시 반복은 확인되지 않았다. 따라서 완전 자동 포스팅은 완료되지 않았다.
