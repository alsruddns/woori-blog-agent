# P5-CLEANUP-001 — Qwen3 로컬 AI 실행 경로 정리

## 목적 및 기준 상태

원고 작성 Provider를 Codex/향후 예약 작업으로 전환할 준비를 위해 사용하지 않는 Qwen3·llama.cpp 실행 경로와 시작 절차를 제거했다. 저장된 모델 비교, 원고, Research Package, 품질 평가와 감사 이력은 보존한다. 이 작업은 Codex/GPT 무인 실행 또는 예약 생성 기능을 구현하지 않는다.

- 작업 경로: `C:\Users\achie\git\woori-blog-agent`
- 브랜치: `develop`
- 시작 기준 커밋: Phase 5-CODEX-006 완료 커밋 `ee88851` (origin/develop 반영)
- 운영 DB 마이그레이션 및 데이터 변경: 수행 안 함
- Blogger API 요청: 0건
- 종량제/유료 AI 요청: 0건
- 실제 모델 추론: 0회

## 조사 결과와 변경 사유

실행 Provider, 연구 Dashboard의 모델 상태 조회 및 로컬 설정 UI, Python inference/runtime 코드, 모델 설치·벤치마크·평가·프로세스 관리 스크립트, PowerShell 서비스 관리자 분기, Hugging Face/GitHub artifact 다운로드 allowlist가 실행 가능한 Qwen/llama.cpp 경로였다. 더 이상 사용하지 않는 경로는 제거했다.

기존 DB는 과거 `provider`, `engine`, `model` 값을 포함할 수 있어 마이그레이션하지 않았다. API 설정은 Mock 테스트 식별자만 허용한다. production Provider 상수가 비활성인 동안 생성 API와 Worker tick은 fail-closed이며 생성 일정과 수집 후 원고 인계는 차단된다. 과거 수집 행의 `auto_generate` 표식은 읽기 호환성을 위해 보존하며, 표식이 있는 수집 완료 시 원고 인계 차단 감사 이벤트를 남긴다.

같은 언어의 결정론적 사실 표기 및 근거 처리, 자료 수집, Research Package, 결정론적 품질 검사, HTML 변환·Sanitization, SEO 검사, 저장 원고 조회/편집, 사람 검토, 발행 승인/취소, Manual/Auto 게시 정책, Fake Publisher와 Blogger 안전 게이트는 유지했다. MockProvider는 테스트에만 사용하고 실제 콘텐츠 Provider로 표시하지 않는다.

## 제거한 실행 기능

- `services/api/woori/local_inference.py`와 `LocalProvider` 구현
- `/admin/research/local-ai` 및 Dashboard의 로컬 모델 상태/설정 UI와 프록시
- Qwen 모델 설치, 실행·종료, 성능 비교, Qwen 원고 평가 및 실제 추론 검증 스크립트
- 로컬 AI 전용 테스트와 artifact download allowlist
- API/Dashboard 관리 스크립트의 11435 llama.cpp 시작·상태·정지 경로
- 운영 문서의 현재 모델 실행 지침과 `.local/inference.key`를 런타임 secret으로 검사하던 참조

DB 마이그레이션 파일의 과거 schema enum과 기존 DB의 `provider/engine/model` 열은 이력 및 호환성을 위해 수정하지 않았다. `docs/development/`의 Qwen 비교, 전체 원고, Research Package, 평가 JSON 및 감사 기록도 삭제하지 않았다.

## 로컬 파일 조사 — 삭제하지 않음

`.local` 디렉터리에서 경로와 파일 크기만 확인했다. 모델 내용, 매니페스트의 인증자료, `.local/inference.key` 내용은 출력·열람하지 않았다. 아래는 사용자가 직접 삭제를 고려할 수 있는 파일의 현재 크기이며 이번 변경에서 아무 파일도 삭제하지 않았다.

| 삭제 후보(사용자 관리) | 크기 |
|---|---:|
| `.local/Qwen3-0.6B-Q8_0.gguf` | 639,446,688 bytes (0.596 GiB) |
| `.local/Qwen3-1.7B-Q8_0.gguf` | 1,834,426,016 bytes (1.708 GiB) |
| `.local/Qwen3-4B-Q4_K_M.gguf` | 2,497,280,256 bytes (2.326 GiB) |
| `.local/Qwen3-8B-Q4_K_M.gguf` | 5,027,783,488 bytes (4.682 GiB) |
| `.local/Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf` | 2,497,280,736 bytes (2.326 GiB) |
| **GGUF 합계** | **12,496,217,184 bytes (11.638 GiB)** |
| `.local/llama-b11889/` 전체 | 62,467,869 bytes (0.058 GiB) |
| `.local/llama-b11889-vulkan/` 전체 | 104,058,653 bytes (0.097 GiB) |
| `.local/llama-b11889-bin-win-cpu-x64.zip` | 24,226,875 bytes (0.023 GiB) |
| `.local/llama-b11889-bin-win-vulkan-x64.zip` | 37,049,027 bytes (0.035 GiB) |

GGUF 외 실행 폴더와 압축 파일까지 모두 사용자가 추후 직접 정리할 경우 추가로 약 0.190 GiB를 확보할 수 있다. 총 후보는 약 11.829 GiB다. 이 합계는 파일 간 중복 여부를 확인하지 않은 단순 합산이다. 공유 llama.cpp 실행 파일이나 개인 모델 파일 삭제는 이 기록에서 제안만 했으며 실행하지 않았다.

`.local/inference.key`는 64 bytes로 존재하지만 읽지 않았고 삭제하지 않았다. 저장소 실행 코드에서는 참조가 더 이상 없다. 사용자가 필요 시 별도 보안 절차로 검토해야 한다.

## 검증 결과

- `scripts/verify.ps1`: 성공
  - Python Ruff: 통과
  - Python mypy: 35 source files, 오류 없음
  - pytest: 248 passed (격리 테스트 DB 및 롤백 fixture)
  - Python wheel: 성공, SHA-256 `c33fb0e07067491df75a699b7b5b55f58c22f8a1d05888d89c3037014d54fca2`
  - Dashboard ESLint: 통과
  - Next.js production build: 통과
  - TypeScript typecheck: 통과
  - `git diff --check`: 통과
- 추가 회귀 테스트: writer 비설정 상태의 생성 API/Worker 차단, 생성 일정/collection auto-generation 차단
- `scripts/verify-secrets.py` HTTP scan: passed. The project API and Dashboard were started using the managed scripts for this check. The script checked `/`, `/research` (compatibility route resolves to `/manuscripts`), `/blogger`, `/api/research/state`, and `/api/blogger/status`; no secret was exposed.
- Temporary server cleanup: API and Dashboard were gracefully stopped with the managed stop script, and ports 3100/8100 were confirmed stopped. Dashboard shutdown was retried only after the active TCP connections drained; no force termination was used.
- Follow-up scope was limited to the HTTP secret scan and server lifecycle. Full tests and production build were not rerun.
- 실제 브라우저 검증: 미실행
- DB 마이그레이션, 운영 DB 조회/수정: 미실행
- Blogger 및 외부 AI/API 호출: 0건

## 상태와 제한

HTML 변환, SEO, 수집/근거, 수동 편집·검토, 발행 준비 및 Fake Publisher 흐름은 Provider가 없어도 유지된다. 신규 AI 원고 생성과 교차 언어 AI 현지화는 실행할 수 없으며 품질 보류 상태로 남는다. Codex/GPT 예약·무인 생성 구현은 별도 미완료 항목이다.

`.local` 모델/엔진 파일과 inference key 보존 여부는 사용자 소유의 PC 정리 결정에 따른다. 이 커밋에서는 삭제하지 않는다.

## Git

?? ?? `20b8ea0` (`Remove : [AI] Retire Qwen3 local inference runtime`)? `origin/develop`? ????. ?? JSON? ??/?? ??? ???? ?? ?? ?? ?? ??? ????. `main`? ???? ???.
