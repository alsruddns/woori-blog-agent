# P5-CODEX-127 — EN/KO/JA 국가 정책 기본값 복구

- 작업일: 2026-11-04 KST
- 시작 브랜치/HEAD: `develop` / `33d9dc67b5562f987478424ca8383cec97a7fff1`
- 요청: EN/US, KO/KR, JA/JP 정책 필드의 미설정을 복구하고 저장 시 기본값이 빈 값으로 사라지지 않게 한다.

## 변경 전

운영 DB의 EN/US, KO/KR, JA/JP language profile 네 정책 필드가 모두 비어 있었고, 해당 세 Blogger 발행 정책은 비활성 상태였다. 수동 발행 오류에는 `publication_policy_inactive`와 별도로 품질, 출처, 근거, 권리, SEO, HTML, 편집 검토, 버전 승인 관련 차단 사유가 포함되어 있었다.

## 변경

- Migration 087은 세 국가별 프로필의 빈 필드에만 다음 기본 정책을 채운다. 비어 있지 않은 운영자 문구는 보존한다.
  - 검색 의도: 국가별 현지 독자를 위한 출처 기반 뉴스·분석
  - 생성: 검토된 출처와 기존 scheduled-export 흐름 사용, local generation adapter 미활성
  - 현지화: 등록 BCP 47 언어 사용, 해외 뉴스를 현지 뉴스로 위장 금지
  - SEO: 언어별 제목·요약·검색 의도·검증된 라벨 사용, 미검증 검사를 통과 처리하지 않음
- 동일 세 Blogger의 비활성 `publishing_policies.active`만 활성화했다. 이는 `publication_policy_inactive` 정책 조건만 해소하며, `auto_publish_allowed`는 false로 유지했다.
- `/profiles` API는 EN/US, KO/KR, JA/JP 정책이 공란으로 저장 요청된 경우 기본 문구를 복구한다. 자동발행 승인이나 콘텐츠 검토 상태를 생성하지 않는다.

## 운영 반영 및 검증

- 변경 전 DB 백업 및 archive catalog 검증 완료: `backups/20261104T001352Z.dump`.
- Migration 087 적용, 운영 schema version 87 확인.
- 운영 DB에서 세 profile 정책 문구, `publishing_policies.active=true`, `auto_publish_allowed=false` 확인.
- 감사 기록 `language.country_policy_defaults.restored` 3건 및 `blogger.country_publication_policy.activated` 3건 확인.
- Ruff 및 mypy 통과. UI 변경이 없어 Dashboard 빌드는 필요하지 않았다.
- Job 관리에서도 별도 원인을 확인했다. `GET /admin/publications/worker-jobs`는 읽기 전용 전체 이력 조회에 10.65초가 걸렸지만 Dashboard Proxy 제한은 10초여서 HTTP 503으로 변환됐다. Proxy timeout을 30초로 늘렸다.
- 초기 로딩 JSX에는 한국어가 문자열 표현식이 아닌 일반 텍스트 `Worker\\uc640 ...`로 들어 있어 escape 문자가 그대로 화면에 표시됐다. 이 문구를 정상적인 Unicode 문자열 표현식으로 바꿨다.
- Dashboard lint/typecheck 및 로컬 운영 HTTP 확인은 최종 반영 후 기록한다.

## 남은 발행 조건

수동/자동 LIVE를 무조건 가능하게 만들지는 않았다. 사용자 제시 원고의 실제 차단 조건 중 기계 품질, 검토된 출처, 사실 근거 검증, Research Package 검토, 출처 권리 검토, SEO, 정제된 본문, 사람 편집 검토, 현재 버전 승인 등은 원고별 근거와 리뷰가 필요하다. 자동 발행은 global/route 운영 설정, 운영자 승인, OAuth 쓰기 권한, 긴급 정지, 일일·간격 제한도 별도로 통과해야 한다. 확인되지 않은 검토 결과를 PASS로 바꾸거나 Blogger 쓰기 권한을 부여하지 않았다.

## 파일 및 Git

- `scripts/087_default_en_ko_ja_country_policies.sql`
- `scripts/migrate.py`
- `services/api/woori/multilingual.py`
- 자기 참조 커밋은 후속 `git log`에서 확인한다.

## Job management monitor correction (2026-11-04 KST)

- The Dashboard proxy used a 10-second abort timeout for `GET /admin/publications/worker-jobs`. A read-only request to the local API returned HTTP 200 after approximately 10.65 seconds, so the proxy converted a slow but successful response into HTTP 503. Increased only this proxy timeout to 30 seconds; no publication API behavior or write policy changed.
- The initial loading message contained literal backslash-u text in JSX. Changed it to a JavaScript Unicode string expression so Korean is rendered as text.
- Verification performed: `git diff --check`, API Ruff+mypy, Dashboard lint+typecheck, and an isolated production build passed in the preceding work. No tests were added or run in this turn. The currently running Dashboard still uses the previously validated source; the repository service-reflection script requires its full validation workflow, including tests, before restarting, so this change has not yet been reflected into the running process.
- Existing local API/worker status was inspected read-only. API PID 10172, Dashboard PID 36624, Research Worker PID 31160, and Publication Worker PID 25620 were alive; both worker heartbeats were fresh. No active queue item was reported. No Blogger write was made.
- The policy-default migration is applied at schema version 87 and the three EN/US, KO/KR, JA/JP profiles are populated. Their publication policy rows are active, while `auto_publish_allowed` remains false. Existing quality, source/evidence, rights, review, approval, OAuth, and publication gates were not marked passed or bypassed.
- Pending: reflect the committed Dashboard source through the repository's verified service workflow, then confirm the proxy returns the delayed read-only Job response without 503 in the running UI.
