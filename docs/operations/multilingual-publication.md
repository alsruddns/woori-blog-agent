# 국가별 원고 대상 및 추가 언어 요청

> P5-CODEX-007 integration addendum: use `/imports` for externally authored material when no approved generation provider is available. Imports enter an immutable human-review-only queue; they are not silently promoted to manuscripts or publication jobs. See [Manual external manuscript import](content-import.md) and the [versioned import contract](../schemas/woori-content-import-1.0.schema.json).

## 범위

원고 상세 화면과 발행 후보 목록은 `/manuscripts`의 동일 원고 상세로 연결됩니다. 운영자는 대상 언어와 해당 언어에 연결된 활성 Blogger 블로그를 확인한 뒤 추가 현지화 요청을 남길 수 있습니다. 요청은 원본 평가 ID·원고 버전·본문 해시·대상 언어·블로그 ID에 묶이며 append-only 감사 이벤트에 기록됩니다.

이 기능은 현지화 원고를 생성하거나 Blogger에 게시하지 않습니다. 현재 운영 생성 Provider가 연결되지 않았으므로 적격 요청도 `awaiting_provider` 상태로 남습니다. 평가 전용 자료, 출처 계보 미검증, 품질 검사 실패, 기존 대상 언어 원고는 각각 생성 차단 또는 편집 검토 상태로 유지합니다. 이미 게시된 대상 언어는 기존 Post ID와 블로그 URL을 보여주고 새 요청을 중복 생성하지 않습니다.

## 지역 추천 원칙

요청자는 선택한 언어에 대해 사건 영향 지역, 대상 독자의 배경 또는 검색 의도 등 실제 독자 가치를 설명해야 합니다. 단순 지역 코드 일치만으로 선택 사유가 충족되지 않으며, 비선택·기존 현지화·이미 게시됨·활성 블로그 매핑 부재는 구분된 감사 사유로 저장됩니다.

KR→ko, US→en, JP→ja, 중국 본토 CN→zh-CN은 지역과 언어가 직접 일치하는 참고 후보로 표시합니다. 이 제안만으로 독자 관련성이나 자동 발행 자격을 인정하지 않습니다. 대만(TW), 홍콩(HK), 싱가포르(SG)는 국가 코드만으로 중국어 간체를 선택하지 않으며, 운영자가 사건 영향 지역, 독자 필요, 검색 의도, 근거를 판단해야 합니다. 다른 지역과 활성 언어 블로그 매핑이 없는 언어는 선택 불가 사유를 표시합니다.

요청 감사 이벤트에는 원본 지역, 선택된 대상, 지역 기반 추천, 사용자가 선택하지 않은 언어, 기존 현지화·게시글로 인해 선택할 수 없는 대상, 활성 블로그 매핑이 없는 언어의 사유를 남깁니다. 누락된 Blog ID나 실제 계정 신원은 추정하지 않습니다.

## 게시 모드와 안전장치

대기 요청은 요청자 이름을 남기고 명시적으로 취소할 수 있습니다. 취소 이벤트는 append-only로 기록되며, 이전 요청을 지운 것으로 처리하지 않습니다. 취소된 뒤 새 idempotency key를 사용하면 동일 언어·블로그 대상의 새 요청을 만들 수 있습니다.

- 전체 게시 모드와 블로그별 Manual/Auto 설정은 이 요청으로 변경되지 않습니다.
- 요청별 자동 게시 의사 표시는 요청 이벤트에만 남고, 라이브 쓰기 잠금·`publish_ready`·Auto 운영 승인을 변경하지 않습니다.
- Manual은 생성 Provider 연결 후 원고 검토·품질 통과·별도 승인 흐름으로 이어져야 합니다.
- Auto는 사전에 승인되고 이미 활성화된 범위에서도 모든 품질·최신성·권리·중복·HTML 조건을 다시 만족해야 합니다. 이 기능은 그 어떤 조건도 대신 충족하지 않습니다.
- 불확실한 Blogger 응답을 재시도해 새 게시물을 만들지 않습니다. 게시 여부를 확인한 뒤 기존 멱등성 규칙을 따릅니다.

## 운영 전 완료 조건

1. 검토된 Research Package를 소비하고 원고 버전을 append-only로 저장하는 허용된 생성 Provider를 연결합니다. ChatGPT 예약 작업이나 Codex UI가 로컬 시스템에 결과를 전달한다고 가정하지 않습니다.
2. 언어별 사실·날짜·숫자·고유명사·출처·권리·최신성 검사를 수행하고 사람의 자연스러움 및 의미 검토를 유지합니다.
3. 해당 언어의 HTML·SEO·라벨 검증과 중복 콘텐츠 검토를 완료합니다.
4. 대상 블로그의 Blog ID와 기존 게시 연결을 재확인합니다.
5. Manual 승인 또는 기존에 별도 승인된 Auto 정책을 적용합니다. 요청별 선택은 전역 Auto 동의가 아닙니다.

이번 개발에서는 Blogger 쓰기, 생성 API, Auto 운영 활성화를 수행하지 않았습니다.
