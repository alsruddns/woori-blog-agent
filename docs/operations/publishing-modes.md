# Manual / Auto 게시 모드 운영 안내

## 현재 동작

게시 모드는 전체 기본값과 언어별·블로그별 오버라이드로 저장합니다. 해석 우선순위는 블로그 → 언어 → 전체이며, 기본값은 Manual입니다. 설정 저장은 `publication.mode.changed` 감사 이벤트를 추가합니다. Migration 042를 적용하지 않은 DB에서는 설정을 읽기 전용 기본값으로 보여주며 변경 요청은 거부합니다.

Auto settings are stored as policy preferences only. `auto_eligible` is evaluated independently from human editorial review, publication approval events, and `publish_ready`; it requires every structured source, factual, semantic, rights, language, SEO, HTML, freshness, duplicate, and mapping gate to be positively verified. Unknown evidence fails closed. Dispatch additionally requires separate policy activation, no emergency stop, and live Blogger writes enabled. Current runtime keeps all three off.

## Manual 흐름

원고는 `/research`에서 품질 및 편집 검토를 거칩니다. 편집 검토와 발행 승인은 서로 다른 append-only 이벤트이며 발행 승인은 정확한 최신 원고 버전과 본문 해시에 묶입니다. `/publishing`의 Manual 요청 기록은 승인·품질·블로그 연결 상태를 확인하고도 실제 게시가 잠겨 있으므로 현재는 차단 상태의 요청/시뮬레이션만 만듭니다. Fake ID는 실제 Blogger Post ID가 아닙니다.

## Auto 설정 및 중지

Auto preferences require an explicit category allowlist and are audited. Saving a preference does not activate unattended dispatch and does not create per-article human approval records. The current policy limits remain the configured values in the database; this document does not change operational settings. Candidates with unverifiable semantic fact support, rights, language quality, freshness, or blog-wide duplication remain held.

`긴급 자동 게시 중지`는 전역 설정을 true로 변경하고 별도 감사 이벤트를 추가합니다. Dashboard에서는 중지를 해제할 수 없습니다. 재개 기능이 제공되지 않는 것은 실수로 Auto가 살아나는 것을 방지하기 위한 현재 운영 잠금입니다. 향후 별도 운영 승인과 변경 검토가 필요합니다.

## 실제 운영 활성화 전 체크리스트

Live Blogger writes and Auto dispatch remain disabled until the separate initial operating transition is explicitly confirmed and the live API path, account permissions, policy checks, and recovery controls are verified. This implementation does not set `publish_ready`, fabricate human reviews, or publish content.

## Migration

`scripts/042_publication_modes.sql`은 새 설정 테이블을 추가하고 Manual 전역 기본값을 시드합니다. `publishing_policies.auto_publish_allowed`의 기존 false 제약을 변경하지 않습니다. Migration runner는 042를 순차적으로 인식하지만 이 작업에서는 운영 DB에 migration을 적용하지 않습니다. 적용 전 테스트 DB에서 별도로 실행하십시오.
