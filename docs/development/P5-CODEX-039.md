# P5-CODEX-039 — Optional official sources and evidence-based draft gates

## 작업 기록

- 작업 ID: P5-CODEX-039
- 작업 일시: 2026-10-29 (Asia/Seoul)
- 브랜치: `develop`
- 변경 사유: 공식 출처가 없으면 후보·Research Package·제한적 원고 초안까지 일괄 차단되던 정책을 근거 기반으로 분리.
- 변경 전: 일부 평가 사유와 조사 지침이 공식 자료 중심이었고, 게시 외 파이프라인의 단일 비공식 출처를 제한 초안 근거로 사용할 수 없었음. SEO의 출처 링크 검사도 `official_sources`만 인정.
- 변경 후: 공식 1차 출처는 우선순위로 남기되 필수 조건에서 제거. 승인된 대체 출처는 별도 등급으로 기록하고, 단일 출처는 제한·검토 대기 초안만 허용. 출처 없음·권리 불명·근거 span 없음은 계속 보류. 게시 자격과 Blogger 쓰기 정책은 별도 유지.

## 구현 내용

- Trends 주제 분류에 `ai 안경`/`smart glasses`와 `google stock` 신호를 추가했다. 분류는 조사 후보 라우팅만 하며 사실성을 증명하지 않는다.
- 토픽 평가 이유를 `awaiting_reviewed_source_evidence`, `single_source_limits_article_scope` 등 근거 상태 중심으로 바꾸고 정책 버전을 `reviewed-source-hierarchy-v2`로 갱신했다.
- 대체 출처는 현재 버전·승인 검토·권리·접근 정책·최신성·정확한 근거 span을 확인한다. 자동 수집기의 승인 표식만 있는 대체 출처는 검토 출처로 취급하지 않는다. 공식 host 판별은 provenance 분류이며 임의 URL 수집 허가가 아니다.
- Research Package에 공식/대체 출처 수, 독립 출처 그룹, 단일 출처 제한 상태, 위험 검토 등급을 기록한다. 패키지 상태는 `generation_ready`, `publish_ready`, `auto_eligible`을 활성화하지 않는다.
- 내부 조사 파이프라인은 현재 검토된 대체 출처 1건을 제한 출처 범위로 받을 수 있다. 이 경로는 여전히 신뢰된 source review와 이용조건이 있어야 하며, 생성 Provider 가용성이나 게시 권한을 바꾸지 않는다.
- SEO metadata에 일반 `sources`를 추가하고 공식 출처 상태와 분리했다. 대체 출처 링크는 source-link 검사를 통과할 수 있지만 공식 출처 확인 상태를 통과로 표시하지 않는다.
- 발행 차단 사유 명칭을 `official_source_review_missing`에서 `reviewed_source_missing`으로 일반화했다. 기존 사실·권리·사람 검토·게시 승인·Auto OFF 게이트는 그대로 둔다.
- Codex 예약 작성 공통 지침 및 운영자 화면에서 공식 출처 선호/검토 대체 출처 허용 정책을 명시했다. 고위험 시장 수치에는 더 엄격한 날짜·단위·신선도·권리·불일치 확인을 유지했다.

## 실제 운영 후보 재평가

운영 DB(`woori_blog_agent`, 역할 `woori_app`)에서 읽기 전용으로 후보를 조사한 뒤 기존 Research Package 생성 경로를 사용했다.

| 후보 | 관측 | 기존 연결 출처/근거 | 기존 제목 일치 | 결과 |
|---|---:|---:|---:|---|
| `ai 안경` / KR | 1건, 최근 2026-10-29 14:01 KST | 출처 0, verified span 0 | 0 | Package `46ab06e2-7785-4812-99aa-0352d604bee7`, `insufficient_evidence` |
| `google stock` / SG | 3건, 최근 2026-10-29 11:04 KST | 출처 0, verified span 0 | 0 | Package `791401e7-08b5-4afe-943c-7f7da9b0c26b`, `insufficient_evidence` |

홍콩의 `google stock` 관측은 1건이며 싱가포르 이슈와의 교차 지역 통합 제안이 미검토 상태이므로 합치지 않았다. 기존 원고 제목 일치 검색은 0건이었다. 두 후보 모두 현재 프로젝트의 사전 검토·무비용 outbound allowlist에 연결된 관련 출처가 없으므로 외부 조회를 임의 실행하지 않았다.

두 Package 모두 `eligible_source_count=0`, `verified_fact_count=0`, `generation_ready=false`, `publish_ready=false`다. 따라서 신규 원고 작성 0건, ready JSON 0건, Import 0건, `auto_eligible` 0건, Publishing Job 0건, Blogger API 호출 0건이다. `.local/gpt-scheduled-import/ready/`의 `*.ready.json` 수는 0이었다. 이는 안전 보류이며 원고 생성 성공이 아니다.

작업 및 상태 이벤트는 PostgreSQL append-only 감사 기록에 추가했다. 작업 ID `b077664f-84a4-4e79-9cc9-66313c8393a7`; 기록된 이벤트: task start/completion, 후보 보류 2건, Package 생성/평가, 콘솔 표시 인코딩 정정 이벤트 1건. 운영 `content_versions`의 확인 시점 개수는 367이었다. 이번 흐름은 콘텐츠 버전을 생성하거나 기존 원고를 수정하지 않았다.

## 수정 파일

- `AGENTS.md`
- `apps/dashboard/app/manuscripts/workspace.tsx`
- `apps/dashboard/app/research/research.tsx`
- `docs/operations/P5-CODEX-024-gpt-work-prompts.md`
- `docs/operations/P5-CODEX-038-scheduled-task-catalog.md`
- `docs/operations/research-sources.md`
- `services/api/woori/topics.py`
- `services/api/woori/pipeline.py`
- `services/api/woori/editorial_seo.py`
- `services/api/woori/content_imports.py`
- `services/api/woori/research_routes.py`
- `services/api/woori/blogger_publication_package.py`
- `services/api/woori/operations_dashboard.py`
- `services/api/woori/publications.py`
- `services/api/tests/test_trend_topics.py`
- `services/api/tests/test_pipeline.py`
- `services/api/tests/test_article_reviews.py`

## 검증

- 격리 테스트 DB(`woori_blog_agent_test`) 변경 범위 테스트: 85 passed.
- Ruff: 변경 Python 파일 All checks passed.
- Python compileall: 통과.
- Dashboard ESLint(변경 파일): 통과.
- Dashboard TypeScript `tsc --noEmit`: 통과.
- `git diff --check`: 통과.
- DB schema 변경: 없음.
- 실제 Blogger 쓰기/공개 게시: 호출 없음.
- 예약 실행 원고 파일 생성: 이번 작업에서 시도하지 않음.

## 남은 문제

- 두 실운영 후보에 연결할 현재 검토된 출처·근거 span과 권리 기록이 없다. 신뢰할 대체 자료를 프로젝트 정책에 맞게 수집·검토한 뒤에만 제한 초안 작성을 재평가할 수 있다.
- Google Trends는 사실 근거가 아니며, `google stock` 지역 통합 제안은 별도 검토가 남아 있다.
- 무인 생성 Provider, 원고 Import, Blogger Auto 및 실 공개 게시 권한은 이번 작업 범위에서 연결하지 않았다.
- 운영 Auto는 계속 OFF이고 Blogger 쓰기 호출은 실행되지 않았다.

## Git 기록

- 구현 커밋 해시: 커밋 후 이 문서의 `git log -- docs/development/P5-CODEX-039.md` 이력 및 최종 보고에 기록.
- 관련 문서: `docs/operations/research-sources.md`, `docs/operations/P5-CODEX-024-gpt-work-prompts.md`, `docs/operations/P5-CODEX-038-scheduled-task-catalog.md`.
