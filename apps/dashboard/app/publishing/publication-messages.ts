export type PublicationReasonMessage = {
  summary: string;
  nextStep: string;
};

const messages: Record<string, PublicationReasonMessage> = {
  automatic_quality_or_policy_blocked: {
    summary: "게시 전 품질 또는 운영 정책 검사에서 차단되었습니다.",
    nextStep: "아래 세부 사유를 확인하세요. 원고 수정이 필요한지, 발행 설정 확인이 필요한지 항목별 안내를 따르세요.",
  },
  source_verbatim_excerpt_present: {
    summary: "본문에 출처 원문의 문구가 그대로 포함되어 있습니다.",
    nextStep: "해당 문장을 직접 인용하지 않도록 다시 작성하고, 새 원고 버전으로 저장한 뒤 발행 가능 여부를 다시 확인하세요.",
  },
  source_excerpt_removed: {
    summary: "출처 문구가 본문에서 제거되었습니다.",
    nextStep: "정리된 문장이 자연스럽고 근거에 맞는지 원고를 확인한 뒤 다시 평가하세요.",
  },
  direct_quote_removed: {
    summary: "직접 인용한 문구가 본문에서 제거되었습니다.",
    nextStep: "인용문을 사용하지 않는 문장으로 고쳐 새 버전으로 저장한 뒤 다시 평가하세요.",
  },
  explicit_source_rights_restriction: {
    summary: "출처의 이용 조건이 본문 사용을 허용하지 않습니다.",
    nextStep: "해당 내용을 제외하고 사용 조건이 확인된 출처로 다시 작성하세요.",
  },
  known_rights_restriction: {
    summary: "권리 제한이 확인된 자료가 포함되어 있습니다.",
    nextStep: "제한된 출처의 문구와 이미지를 제거하고 이용 가능한 근거로 원고를 다시 작성하세요.",
  },
  source_rights_explicitly_restricted: {
    summary: "출처 이용이 명시적으로 제한되어 있습니다.",
    nextStep: "해당 출처에 의존하는 내용을 제외하거나 사용 허가가 확인된 자료로 대체하세요.",
  },
  source_rights_not_machine_verified: {
    summary: "출처 이용 권리를 확인하지 못했습니다.",
    nextStep: "출처의 이용 조건과 허용 범위를 확인하고, 확인되지 않으면 해당 자료를 인용하지 마세요.",
  },
  source_rights_review_missing: {
    summary: "출처 이용 권리 검토 기록이 없습니다.",
    nextStep: "출처별 이용 조건을 확인해 검토 기록을 남긴 뒤 발행을 다시 확인하세요.",
  },
  source_live_verification_missing: {
    summary: "출처 원문을 확인한 기록이 없습니다.",
    nextStep: "원문 페이지를 다시 확인해 제목·URL·게시일과 주장 근거를 기록하세요.",
  },
  source_live_verification_mismatch: {
    summary: "확인한 원문이 등록된 출처 정보와 일치하지 않습니다.",
    nextStep: "올바른 원문 URL과 출처 정보를 연결한 뒤 주장을 다시 확인하세요.",
  },
  source_live_verification_incomplete: {
    summary: "출처 원문 확인이 끝나지 않았습니다.",
    nextStep: "원문 수집과 근거 확인을 완료한 뒤 다시 평가하세요.",
  },
  source_evidence_spans_missing: {
    summary: "출처에서 주장과 연결되는 근거 구간을 찾지 못했습니다.",
    nextStep: "각 핵심 주장에 해당하는 원문 근거를 연결하세요. 근거가 없으면 주장을 삭제하거나 불확실성을 밝혀야 합니다.",
  },
  claim_source_verification_unavailable: {
    summary: "일부 주장에 확인된 출처 자료가 연결되지 않았습니다.",
    nextStep: "누락된 주장을 확인 가능한 출처에 연결하거나 본문에서 제외하세요.",
  },
  claim_span_not_found_in_live_source_evidence: {
    summary: "주장을 뒷받침하는 구절이 확인된 원문에 없습니다.",
    nextStep: "원문으로 주장을 다시 확인하고, 뒷받침되지 않으면 표현을 고치거나 삭제하세요.",
  },
  claim_evidence_incomplete: {
    summary: "일부 주장에 근거 연결 또는 검증 정보가 빠져 있습니다.",
    nextStep: "주장별 출처·근거 구절·검증 상태를 보완한 뒤 다시 평가하세요.",
  },
  claim_evidence_mismatch: {
    summary: "주장과 연결된 근거가 서로 맞지 않습니다.",
    nextStep: "근거에 맞게 주장을 수정하거나 해당 주장을 삭제하세요.",
  },
  claim_contains_unsupported_number_or_unit: {
    summary: "출처에서 확인되지 않는 숫자나 단위가 본문에 있습니다.",
    nextStep: "원문에서 수치와 단위를 다시 확인하고, 확인되지 않으면 삭제하거나 범위를 명확히 하세요.",
  },
  known_conflicting_claim: {
    summary: "원고의 주장과 상충하거나 반박하는 근거가 확인되었습니다.",
    nextStep: "상충하는 자료를 검토해 주장을 바로잡고, 해결되지 않으면 해당 주장을 제외하세요.",
  },
  semantic_claim_review_required: {
    summary: "출처 근거가 주장과 같은 의미인지 확인되지 않았습니다.",
    nextStep: "원문 맥락과 주장의 의미를 대조하고, 확인된 사실과 해석을 구분하세요.",
  },
  independent_corroboration_missing: {
    summary: "독립된 출처의 교차 확인이 부족합니다.",
    nextStep: "요구되는 경우 서로 독립된 신뢰 가능한 출처를 추가해 핵심 사실을 대조하세요.",
  },
  claims_or_sources_missing: {
    summary: "원고의 주장 또는 출처 자료가 없습니다.",
    nextStep: "검증 가능한 출처와 출처에 근거한 핵심 주장을 등록하세요.",
  },
  claims_or_sources_not_verified: {
    summary: "주장과 출처의 검증이 완료되지 않았습니다.",
    nextStep: "각 핵심 주장을 원문과 대조하고 검증 상태를 기록하세요.",
  },
  source_evidence_missing: {
    summary: "발행에 필요한 출처 근거가 부족합니다.",
    nextStep: "주요 사실을 뒷받침하는 출처와 근거 구절을 추가하세요.",
  },
  reviewed_source_missing: {
    summary: "검토가 완료된 출처가 없습니다.",
    nextStep: "신뢰할 수 있는 최신 출처를 검토해 원고의 사실을 확인하세요.",
  },
  article_quality_review_incomplete: {
    summary: "원고 품질 검토가 완료되지 않았습니다.",
    nextStep: "본문 구조·언어·중복·안전 검사를 완료하고 최신 버전을 다시 평가하세요.",
  },
  machine_quality_not_passed: {
    summary: "자동 품질 검사를 통과하지 못했습니다.",
    nextStep: "품질 평가의 미통과 항목을 확인해 원고를 수정한 뒤 다시 평가하세요.",
  },
  quality_evaluation_missing: {
    summary: "원고 품질 평가 기록이 없습니다.",
    nextStep: "현재 원고 버전으로 품질 평가를 실행하세요.",
  },
  quality_not_passed: {
    summary: "원고 품질 평가가 통과되지 않았습니다.",
    nextStep: "평가 결과의 미통과 항목을 수정하고 새 버전을 평가하세요.",
  },
  seo_check_not_passed: {
    summary: "검색 최적화 검사를 통과하지 못했습니다.",
    nextStep: "제목·검색 설명·본문 구성을 보완하고 다시 검사하세요.",
  },
  unsafe_article_format: {
    summary: "본문 형식에 게시할 수 없는 내용이 있습니다.",
    nextStep: "허용되지 않는 서식이나 삽입 요소를 제거한 뒤 본문 미리보기를 확인하세요.",
  },
  unsafe_article_html: {
    summary: "안전하지 않은 HTML이 포함되어 있습니다.",
    nextStep: "원고 편집기에서 위험한 태그와 속성을 제거하고 안전한 본문으로 다시 저장하세요.",
  },
  sanitized_blogger_html_unavailable: {
    summary: "Blogger에 전달할 안전한 본문을 만들지 못했습니다.",
    nextStep: "본문의 HTML과 서식을 확인해 저장한 뒤 다시 평가하세요.",
  },
  no_supported_body_after_sanitization: {
    summary: "안전하지 않은 내용을 정리한 뒤 게시 가능한 본문이 남지 않았습니다.",
    nextStep: "확인된 근거에 기반해 본문을 다시 작성하세요. 자동 정리 결과만으로 발행을 진행할 수 없습니다.",
  },
  publication_title_missing: {
    summary: "게시 제목이 비어 있습니다.",
    nextStep: "제목을 입력하고 원고를 다시 저장하세요.",
  },
  publication_body_missing: {
    summary: "게시 본문이 비어 있습니다.",
    nextStep: "본문을 입력하고 원고를 다시 저장하세요.",
  },
  article_title_or_body_insufficient: {
    summary: "제목이나 본문이 게시 기준에 미달합니다.",
    nextStep: "제목과 본문을 보완하고 품질 평가를 다시 실행하세요.",
  },
  blogger_labels_invalid: {
    summary: "Blogger 라벨 형식이 올바르지 않습니다.",
    nextStep: "빈 라벨이나 너무 긴 라벨을 정리한 뒤 다시 요청하세요.",
  },
  remote_duplicate_found: {
    summary: "같거나 유사한 게시물이 Blogger에서 확인되었습니다.",
    nextStep: "기존 게시물을 확인하세요. 중복 게시를 피하기 위해 이 요청은 진행하지 마세요.",
  },
  automatic_duplicate_unconfirmed_or_found: {
    summary: "Blogger 중복 여부를 확인하지 못했거나 중복 게시물이 발견되었습니다.",
    nextStep: "Blogger 원격 확인이 완료될 때까지 발행을 보류하세요. 확인되지 않은 상태에서 재시도하지 마세요.",
  },
  remote_duplicate_check_unknown: {
    summary: "Blogger에서 중복 여부를 확인하지 못했습니다.",
    nextStep: "연결 상태를 확인한 뒤 원격 중복 검사를 다시 실행하세요.",
  },
  remote_duplicate_check_required_before_request: {
    summary: "발행 요청 전에 Blogger 중복 확인이 필요합니다.",
    nextStep: "원격 게시 상태를 확인한 뒤 정확한 원고 버전으로 다시 요청하세요.",
  },
  remote_publication_already_recorded: {
    summary: "이 원고의 원격 게시 기록이 이미 있습니다.",
    nextStep: "게시 이력과 Blogger의 현재 상태를 확인하세요. 새 요청으로 중복 게시하지 마세요.",
  },
  verified_live_publication_exists: {
    summary: "같은 원고가 Blogger에 공개된 것이 확인되었습니다.",
    nextStep: "기존 게시물을 확인하세요. 재발행 요청은 하지 마세요.",
  },
  same_event_already_queued_or_published: {
    summary: "같은 사건을 다룬 원고가 이미 대기 중이거나 게시되었습니다.",
    nextStep: "기존 원고를 확인하고 같은 블로그에 중복 요청하지 마세요.",
  },
  same_event_same_blog_identical_body_already_queued_or_published: {
    summary: "같은 블로그에 동일 본문이 이미 대기 중이거나 게시되었습니다.",
    nextStep: "기존 발행 이력을 확인하세요. 다른 사건이나 실질적으로 새 원고가 아니면 요청하지 마세요.",
  },
  manual_live_job_already_exists: {
    summary: "이 원고와 블로그의 수동 발행 작업이 이미 있습니다.",
    nextStep: "기존 Job 상태를 확인하고 완료 여부가 정리될 때까지 새 요청을 만들지 마세요.",
  },
  existing_job_requires_reconciliation: {
    summary: "기존 발행 작업의 상태 확인이 필요합니다.",
    nextStep: "기존 Job과 Blogger 원격 상태를 대조한 뒤 재시도 가능 여부를 확인하세요.",
  },
  remote_publication_status_requires_review: {
    summary: "Blogger의 기존 게시 상태를 확정하지 못했습니다.",
    nextStep: "Blogger에서 해당 게시물 상태를 확인해 중복 발행 가능성을 해소하세요.",
  },
  remote_status_check_required: {
    summary: "Blogger의 현재 게시 상태를 확인해야 합니다.",
    nextStep: "원격 상태 확인이 완료될 때까지 발행을 보류하세요.",
  },
  global_minimum_interval_not_elapsed: {
    summary: "전체 블로그 발행 간격 제한이 아직 지나지 않았습니다.",
    nextStep: "표시된 다음 처리 가능 시각까지 기다리세요. 재시도해도 더 빨리 발행되지 않습니다.",
  },
  account_minimum_interval_not_elapsed: {
    summary: "Google 계정의 최소 발행 간격 제한이 아직 지나지 않았습니다.",
    nextStep: "다음 처리 가능 시각까지 기다리세요.",
  },
  blog_minimum_interval_not_elapsed: {
    summary: "대상 블로그의 최소 발행 간격 제한이 아직 지나지 않았습니다.",
    nextStep: "다음 처리 가능 시각까지 기다리세요.",
  },
  daily_publication_limit: {
    summary: "오늘 발행 한도에 도달했습니다.",
    nextStep: "KST 기준 다음 날 한도가 갱신된 뒤 다시 확인하세요.",
  },
  global_daily_live_publish_limit_reached: {
    summary: "KST 기준 전체 공개 발행 한도에 도달했습니다.",
    nextStep: "다음 날 한도가 갱신된 뒤 다시 확인하세요.",
  },
  trends_daily_publication_limit: {
    summary: "Google Trends 원고의 일일 발행 한도에 도달했습니다.",
    nextStep: "한도가 갱신된 뒤 다시 확인하세요.",
  },
  language_daily_live_publish_limit_reached: {
    summary: "이 언어의 일일 공개 발행 한도에 도달했습니다.",
    nextStep: "한도가 갱신된 뒤 다시 확인하세요.",
  },
  hourly_publication_limit: {
    summary: "시간당 발행 한도에 도달했습니다.",
    nextStep: "시간 제한이 갱신된 뒤 다시 확인하세요.",
  },
  emergency_stop_enabled: {
    summary: "긴급 발행 정지가 켜져 있습니다.",
    nextStep: "운영 관리자가 원인을 확인하고 긴급 정지를 해제해야 합니다.",
  },
  publication_emergency_stop_active: {
    summary: "긴급 발행 정지가 켜져 있습니다.",
    nextStep: "운영 관리자가 원인을 확인하고 긴급 정지를 해제해야 합니다.",
  },
  global_emergency_stop_or_policy_missing: {
    summary: "긴급 정지가 켜져 있거나 필수 발행 정책을 확인할 수 없습니다.",
    nextStep: "운영 설정과 긴급 정지 상태를 확인하세요.",
  },
  blogger_api_restricted_manual_only: {
    summary: "현재 운영 설정이 Blogger 발행을 허용하지 않습니다.",
    nextStep: "운영 관리자가 승인된 발행 모드와 블로그 범위를 확인해야 합니다.",
  },
  blogger_api_restricted: {
    summary: "Blogger API 제한 상태로 발행이 중단되었습니다.",
    nextStep: "제한 원인과 Blogger 연결 상태를 확인하세요. 제한이 풀렸다고 확인되기 전에는 재시도하지 마세요.",
  },
  blogger_external_backoff: {
    summary: "Blogger가 요청을 일시 제한해 발행을 보류했습니다.",
    nextStep: "다음 처리 가능 시각까지 기다리세요. 반복 요청이나 우회 연결을 사용하지 마세요.",
  },
  transport_error: {
    summary: "Blogger에 연결하지 못했습니다.",
    nextStep: "네트워크와 Blogger 상태를 확인하세요. 원격 게시 결과가 불확실하면 먼저 게시 여부를 조회하세요.",
  },
  timeout: {
    summary: "Blogger 응답 시간이 초과되었습니다.",
    nextStep: "게시 결과를 원격으로 확인하세요. 결과를 확인하기 전에는 중복 방지를 위해 재시도하지 마세요.",
  },
  invalid_grant: {
    summary: "Google 인증이 만료되었거나 취소되었습니다.",
    nextStep: "Blogger 연결 관리에서 인증 상태를 확인하고 필요한 경우 다시 연결하세요.",
  },
  blogger_write_oauth_not_verified: {
    summary: "Blogger 쓰기 권한을 확인하지 못했습니다.",
    nextStep: "대상 블로그에 연결된 OAuth 계정과 쓰기 권한을 확인하세요.",
  },
  write_oauth_not_mapped_to_blog: {
    summary: "쓰기 OAuth 계정이 대상 Blogger와 연결되어 있지 않습니다.",
    nextStep: "Blogger 연결 관리에서 계정과 블로그 매핑을 확인하세요.",
  },
  blog_connection_unverified: {
    summary: "대상 Blogger 연결을 확인하지 못했습니다.",
    nextStep: "등록된 블로그 ID와 연결 상태를 다시 확인하세요.",
  },
  blog_or_oauth_not_verified: {
    summary: "대상 블로그 또는 OAuth 연결이 확인되지 않았습니다.",
    nextStep: "블로그 활성 상태, ID 매핑, OAuth 권한을 확인하세요.",
  },
  blog_inactive: {
    summary: "대상 Blogger가 비활성 상태입니다.",
    nextStep: "운영 설정에서 대상 블로그가 활성화되어 있는지 확인하세요.",
  },
  language_inactive: {
    summary: "원고 언어가 비활성 상태입니다.",
    nextStep: "언어 설정과 해당 언어에 연결된 Blogger를 확인하세요.",
  },
  blog_language_mismatch: {
    summary: "원고 언어와 대상 Blogger 언어가 일치하지 않습니다.",
    nextStep: "원고 언어에 맞는 활성 블로그를 선택하세요.",
  },
  scheduled_language_blog_mismatch: {
    summary: "예약 원고의 언어와 대상 Blogger 언어가 다릅니다.",
    nextStep: "예약 설정의 언어·블로그 매핑을 바로잡고 새 실행에서 확인하세요.",
  },
  trends_target_mapping_mismatch: {
    summary: "Google Trends 원고와 대상 블로그 매핑이 일치하지 않습니다.",
    nextStep: "해당 지역과 언어에 승인된 활성 Blogger 매핑을 확인하세요.",
  },
  enabled_trend_blog_geo_mapping_required: {
    summary: "Google Trends 지역과 블로그의 활성 매핑이 없습니다.",
    nextStep: "운영 관리자가 승인된 지역·언어·블로그 매핑을 확인해야 합니다.",
  },
  stale_content_version: {
    summary: "발행 요청이 최신 원고 버전을 가리키지 않습니다.",
    nextStep: "목록을 새로고침하고 최신 원고 버전에서 다시 요청하세요.",
  },
  stale_import_version: {
    summary: "발행 요청이 최신 Import 버전과 일치하지 않습니다.",
    nextStep: "원고 상세를 새로고침하고 최신 버전으로 다시 확인하세요.",
  },
  content_version_is_not_current: {
    summary: "선택한 원고 버전이 최신 버전이 아닙니다.",
    nextStep: "최신 버전을 열어 다시 요청하세요.",
  },
  manuscript_discarded: {
    summary: "폐기 처리된 원고입니다.",
    nextStep: "원고 이력을 확인하세요. 복원이 승인되지 않은 원고는 발행할 수 없습니다.",
  },
  manuscript_discarded_restore_before_review: {
    summary: "폐기 보관 중인 원고입니다.",
    nextStep: "기록을 검토하고 승인된 복원 절차를 거친 뒤 다시 평가하세요.",
  },
  publication_policy_missing: {
    summary: "대상 블로그의 발행 정책을 찾을 수 없습니다.",
    nextStep: "운영 관리자가 해당 블로그의 발행 정책을 설정해야 합니다.",
  },
  publication_policy_inactive: {
    summary: "대상 블로그의 발행 정책이 비활성 상태입니다.",
    nextStep: "운영 관리자가 정책의 활성 상태와 적용 범위를 확인해야 합니다.",
  },
  automatic_publication_operator_approval_off: {
    summary: "자동 발행 운영 승인이 활성화되어 있지 않습니다.",
    nextStep: "운영 관리자가 승인 상태와 허용 블로그 범위를 확인해야 합니다.",
  },
  operations_auto_approved_false: {
    summary: "자동 발행 운영 승인이 꺼져 있습니다.",
    nextStep: "운영 관리자가 자동 발행 승인 설정을 확인해야 합니다.",
  },
  global_auto_publication_off: {
    summary: "전체 자동 발행이 꺼져 있습니다.",
    nextStep: "운영 관리자가 전체 자동 발행 설정을 확인해야 합니다.",
  },
  scheduled_auto_publication_off: {
    summary: "예약 원고 자동 발행이 꺼져 있습니다.",
    nextStep: "운영 관리자가 예약 자동 발행 정책을 확인해야 합니다.",
  },
  trends_auto_publication_off: {
    summary: "Google Trends 원고 자동 발행이 꺼져 있습니다.",
    nextStep: "운영 관리자가 Trends 발행 정책과 승인 범위를 확인해야 합니다.",
  },
  scheduled_auto_policy_not_approved: {
    summary: "대상 블로그에 적용되는 예약 자동 발행 승인이 없습니다.",
    nextStep: "운영 관리자가 예약 정책의 승인 블로그 범위를 확인해야 합니다.",
  },
  automatic_publication_policy_inactive: {
    summary: "자동 발행 정책이 현재 활성화되어 있지 않습니다.",
    nextStep: "운영 관리자가 자동 발행 정책의 상태와 적용 범위를 확인해야 합니다.",
  },
  automation_policy_changed: {
    summary: "작업이 대기하는 동안 자동 발행 정책이 변경되었습니다.",
    nextStep: "최신 운영 설정과 Job 상태를 다시 확인하세요.",
  },
  production_writes_disabled: {
    summary: "현재 실행 환경에서는 실제 Blogger 쓰기가 허용되지 않습니다.",
    nextStep: "운영 실행 환경과 승인된 쓰기 경로를 확인하세요.",
  },
  blogger_zero_cost_policy_required: {
    summary: "Blogger 비용·권한 운영 확인이 완료되지 않았습니다.",
    nextStep: "운영자가 기존 비용·권한 확인과 승인 기록을 확인해야 합니다.",
  },
  external_blogger_cost_policy_approval_missing: {
    summary: "Blogger 비용 정책 승인이 확인되지 않았습니다.",
    nextStep: "운영자가 기존 비용·정책 승인 기록을 확인해야 합니다.",
  },
  external_blogger_public_write_approval_missing: {
    summary: "Blogger 공개 쓰기 승인이 확인되지 않았습니다.",
    nextStep: "운영자가 승인 기록과 대상 블로그 범위를 확인해야 합니다.",
  },
  external_blogger_public_write_approval_scope_mismatch: {
    summary: "공개 쓰기 승인의 블로그 범위와 대상이 다릅니다.",
    nextStep: "운영자가 승인된 블로그 범위를 확인해야 합니다.",
  },
  daily_publication_count_unavailable: {
    summary: "오늘의 발행 건수를 확인할 수 없어 안전을 위해 발행을 보류했습니다.",
    nextStep: "운영자가 발행 집계와 데이터베이스 연결 상태를 확인하세요.",
  },
  hourly_publication_count_unavailable: {
    summary: "시간당 발행 건수를 확인할 수 없어 안전을 위해 발행을 보류했습니다.",
    nextStep: "운영자가 발행 집계 상태를 확인하세요.",
  },
  scheduled_daily_publication_limit_or_policy_unavailable: {
    summary: "예약 발행 한도 또는 관련 정책을 확인할 수 없습니다.",
    nextStep: "운영자가 예약 정책과 KST 기준 당일 발행 집계를 확인하세요.",
  },
  trends_publication_count_unavailable: {
    summary: "Google Trends 발행 건수를 확인할 수 없습니다.",
    nextStep: "운영자가 발행 집계와 Trends 정책 상태를 확인하세요.",
  },
  automatic_target_not_approved: {
    summary: "대상 블로그가 자동 발행 승인 범위에 없습니다.",
    nextStep: "운영자가 허용 블로그 목록과 해당 원고의 대상 블로그를 확인해야 합니다.",
  },
  target_uses_auto_mode: {
    summary: "대상 블로그 설정이 수동 발행 경로와 맞지 않습니다.",
    nextStep: "대상 블로그의 발행 모드와 요청 경로를 확인하세요.",
  },
  scheduled_origin_target_mismatch: {
    summary: "예약 실행에서 확인된 대상 블로그와 요청 대상이 다릅니다.",
    nextStep: "예약 설정과 실제 Blogger 매핑을 바로잡으세요.",
  },
  automatic_publication_not_completed: {
    summary: "자동 발행이 완료되지 않았습니다.",
    nextStep: "세부 실패 사유와 발행 Job 기록을 확인하세요.",
  },
  publication_worker_failed: {
    summary: "발행 Worker에서 작업을 완료하지 못했습니다.",
    nextStep: "Worker 오류 기록과 Job의 마지막 처리 단계를 확인하세요.",
  },
  publication_worker_cycle_failed: {
    summary: "발행 Worker가 이번 처리 주기를 완료하지 못했습니다.",
    nextStep: "Worker 상태와 최근 오류 기록을 확인하세요.",
  },
  live_job_stage_invalid: {
    summary: "발행 작업 단계가 예상한 순서와 다릅니다.",
    nextStep: "Job 기록과 원격 Blogger 상태를 대조한 뒤 운영자가 재처리를 결정해야 합니다.",
  },
  lease_expired_remote_reconciliation_required: {
    summary: "작업 임대가 만료되어 Blogger 반영 여부를 확인해야 합니다.",
    nextStep: "Blogger 원격 상태를 먼저 대조하세요. 확인 전 재시도하면 중복될 수 있습니다.",
  },
  published_readback_mismatch: {
    summary: "Blogger에 보낸 게시 결과와 다시 읽은 결과가 다릅니다.",
    nextStep: "Blogger 게시물과 로컬 발행 기록을 대조하세요. 자동 재시도하지 마세요.",
  },
  published_record_conflict: {
    summary: "원격 게시 기록과 내부 발행 이력이 서로 일치하지 않습니다.",
    nextStep: "Blogger 게시물과 기록을 대조한 뒤 운영자가 정리해야 합니다.",
  },
  failure_record_superseded_or_missing: {
    summary: "이 실패 기록이 최신 상태가 아니거나 원본 기록을 찾지 못했습니다.",
    nextStep: "최신 원고와 발행 이력을 새로고침해 확인하세요.",
  },
  import_version_link_missing: {
    summary: "Research Import와 원고 버전의 연결을 확인할 수 없습니다.",
    nextStep: "Import 이력과 원고 버전 연결을 운영자가 확인해야 합니다.",
  },
  global_publication_mode_mismatch: {
    summary: "현재 발행 모드가 이 자동 발행 작업을 허용하지 않습니다.",
    nextStep: "운영자가 전체 발행 모드와 원고별 발행 경로를 확인해야 합니다.",
  },
  collection_predates_policy_activation: {
    summary: "이 수집 회차는 발행 정책이 활성화되기 전에 생성되었습니다.",
    nextStep: "과거 회차는 자동 소급 처리하지 않습니다. 정책 활성화 이후의 신규 회차를 사용하세요.",
  },
  blogger_write_scope_required: {
    summary: "Blogger 공개 쓰기에 필요한 OAuth 권한이 없습니다.",
    nextStep: "승인된 Blogger 계정에 필요한 쓰기 권한이 연결되어 있는지 확인하세요.",
  },
  manual_publishing_disabled: {
    summary: "수동 발행 기능이 비활성화되어 있습니다.",
    nextStep: "운영 관리자가 수동 발행 설정과 긴급 정지 상태를 확인해야 합니다.",
  },
  exact_manual_publication_confirmation_missing: {
    summary: "선택한 정확한 원고 버전에 대한 사용자 발행 확인이 없습니다.",
    nextStep: "발행 미리보기에서 버전을 확인한 뒤 해당 버전에 대해 다시 명시적으로 요청하세요.",
  },
  manual_publication_confirmation_payload_mismatch: {
    summary: "확인한 원고와 발행 요청에 담긴 원고가 다릅니다.",
    nextStep: "최신 미리보기를 열어 원고 버전과 내용을 확인한 뒤 다시 요청하세요.",
  },
};

export function publicationReason(code: string): PublicationReasonMessage {
  if (messages[code]) return messages[code];
  if (/^(source|claim|evidence|research_)/.test(code)) {
    return {
      summary: "출처 또는 주장 근거 확인이 완료되지 않았습니다.",
      nextStep: "해당 주장과 원문 근거를 대조하세요. 근거가 없거나 의미가 다르면 주장을 수정하거나 제외하세요.",
    };
  }
  if (/rights|copyright/.test(code)) {
    return {
      summary: "출처의 이용 권리나 사용 조건을 확인하지 못했습니다.",
      nextStep: "이용 조건이 확인될 때까지 해당 자료를 인용하거나 게시하지 마세요.",
    };
  }
  if (/duplicate|already_(queued|published|live)|existing_job/.test(code)) {
    return {
      summary: "기존 게시물 또는 발행 작업과 중복될 가능성이 있습니다.",
      nextStep: "Blogger의 원격 상태와 기존 Job을 먼저 확인하고, 중복이 해소되기 전에는 재요청하지 마세요.",
    };
  }
  if (/interval|daily_limit|hourly_limit|backoff/.test(code)) {
    return {
      summary: "발행 간격 또는 발행 한도에 걸려 요청이 보류되었습니다.",
      nextStep: "다음 처리 가능 시각이나 한도 갱신까지 기다린 뒤 상태를 다시 확인하세요.",
    };
  }
  if (/oauth|connection|write_scope|invalid_grant/.test(code)) {
    return {
      summary: "대상 Blogger의 연결 또는 쓰기 권한을 확인하지 못했습니다.",
      nextStep: "Blogger 연결 관리에서 계정, 블로그 매핑, OAuth 쓰기 권한을 확인하세요.",
    };
  }
  if (/blog_|language_|mapping|target_/.test(code)) {
    return {
      summary: "원고의 언어·지역·대상 블로그 설정이 발행 경로와 일치하지 않습니다.",
      nextStep: "활성 언어와 블로그 매핑, 자동 발행 허용 범위를 확인하세요.",
    };
  }
  if (/policy|approval|auto_|emergency|production_writes/.test(code)) {
    return {
      summary: "현재 운영 정책이나 승인이 이 발행 요청을 허용하지 않습니다.",
      nextStep: "운영 관리자가 전체 발행 모드, 출처별 정책, 긴급 정지, 승인 블로그 범위를 확인해야 합니다.",
    };
  }
  if (/quality|seo|html|body|title|format|unsafe|verbatim|quote/.test(code)) {
    return {
      summary: "원고의 품질 또는 게시 형식을 통과하지 못했습니다.",
      nextStep: "원고 편집 화면에서 해당 항목을 수정한 뒤 새 버전으로 다시 평가하세요.",
    };
  }
  if (/blogger|transport|timeout|readback|worker|lease/.test(code)) {
    return {
      summary: "Blogger 연결 또는 발행 Worker에서 작업을 완료하지 못했습니다.",
      nextStep: "Job 세부 상태와 Blogger 원격 게시 여부를 먼저 확인하세요. 결과가 불확실하면 재시도하지 마세요.",
    };
  }
  return {
    summary: "발행을 완료하지 못했습니다.",
    nextStep: "아래 기술 코드를 운영 담당자에게 전달해 원인을 확인하세요.",
  };
}

export function publicationReasonText(code: string): string {
  const message = publicationReason(code);
  return `${message.summary} 조치: ${message.nextStep}`;
}

export function publicationReasonsText(codes: string[]): string {
  const unique = [...new Set(codes.map(code => code.trim()).filter(Boolean))];
  return unique.map(publicationReasonText).join(" · ");
}

export function publicationApiErrorText(value: string): string {
  const message = value.trim();
  if (/^[a-z][a-z0-9_]{2,}$/.test(message)) return publicationReasonText(message);
  const embeddedCode = message.match(/\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b/);
  if (embeddedCode && messages[embeddedCode[1]]) {
    return `${publicationReasonText(embeddedCode[1])} (${message})`;
  }
  return message || "\ubc1c\ud589 \uc624\ub958\uc758 \uc124\uba85\uc774 \uc5c6\uc2b5\ub2c8\ub2e4. \uc6b4\uc601 \uae30\ub85d\uc744 \ud655\uc778\ud558\uc138\uc694.";
}
