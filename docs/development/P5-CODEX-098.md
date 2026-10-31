# P5-CODEX-098 — Publishing 정합성 및 Qwen 원고 정리

- 일시: 2026-10-31 KST. 시작 HEAD `5232604`, develop. 사용자 명시 승인: 생성 이력이 확인된 Qwen 원고/전용 실험 데이터 Hard Delete.
- Blogger `manual_only`, Google 제한 및 긴급 정지 유지. 이 작업에서 원격 Blogger 쓰기·계정/OAuth 변경 없음.

## 변경 전 운영 진단

실제 API 건수: 발행 대기1 / 검토45 / 게시 완료17 / 실패·보류16 / 자동발행실패8. 스크린샷의 검토37과 달랐으며 실제 운영 값을 기준으로 한다.

- Jamie Carragher Import `f58c8668-fb46-4d0e-9462-eb0ec116c764`, Version `87ddaf53-28dd-4a74-9469-3b2fc447269c`, 자동 Trends Job `7d6c8069-d456-4740-b6b2-7d6da04673c9`. 원래 status queued/live_stage draft_needed, 저장 postId 없음. P097부터 실제 Worker 획득 불가였으나 조회 화면이 queued를 그대로 표시했다.
- 수정 후 원본 Job은 삭제/변조하지 않고 `auto_paused`로 표시, 실패·보류와 모니터의 ‘자동 발행 중지로 보류’에 분류한다. 실제 실행 가능한 새 수동 Job만 대기 건수에 포함한다. 제한/긴급 정지 때문에 새 수동 요청도 현재 차단된다.

## Fed 버전 및 발행 연결

- Import `7bcc3d86-d0aa-4d6c-bef4-e47726b7f818`, group `35fbb23a-ba5b-4d32-bdb0-404b29a54e69`, localization `32b9c926-4fc5-4504-ba3a-87d557496821`.
- V1 `052e090d-79b7-4b79-8492-02afd1d17ee3`: What the Fed’s October 2026 Rate Decision Says—and Leaves Open.
- V2 `a7530606-dafe-4217-bc22-dff67af86ea3`: Cook and Hammack's FOMC dissent: a preference for a higher rate.
- Job `b3d38f66-2285-4e6b-8809-b35622cc15d6`: V2, succeeded/published, EN Blogger `b9dc1202-8071-484a-a4f4-15d04e34a76c`.
- 저장 검증 postId `3006185544912270190`, LIVE 확인 2026-10-30 14:22:23 KST. URL: https://trend-journal-en.blogspot.com/2026/10/cook-and-hammacks-fomc-dissent.html
- 원인: 실패 조회가 V1에 대한 동일 Version 성공만 검사했다. V2 성공 후 V1 실패가 남았고, 상세는 최신 V2를 열었다.
- 해결: 동일 Import/그룹/지역화/대상 Blogger의 동일 또는 이후 Version에 **검증된 LIVE 기록**이 있을 때만 실패를 해결로 판단한다. 다른 Import/블로그/이전 Version/Draft/미검증 게시 기록은 해결 근거가 아니다. 목록은 현재 대표 제목·버전, 게시 당시 제목·버전은 별도 필드로 표시한다. 원본 제목/FK 변경 없음.
- 실패 감사 이벤트 179885/180869/181101/181657(V1), 181742/181964/181983/182369(V2) 모두 보존. 현재 Blogger 제목은 새로 조회하지 않았으며 저장된 게시 당시 증거와 구분한다.

## 백업 및 삭제 Dry Run

- 백업: `backups/20261031T135651Z.dump`.
- SHA256: `3C237E1380A0613B93DF9CA6244E88507F760E5D785C3BE685A7BF2AF756A349`.
- `pg_restore --list` 및 `pg_restore --file=NUL`로 전체 스키마/데이터 추출을 검증(원격/운영 DB 쓰기 없음). 실제 별도 DB 전체 복원 리허설은 수행하지 않았다.
- 삭제 도구: `scripts/cleanup-qwen-p098.py`. 기본 Dry Run; 적용은 저장된 manifest와 정확한 SHA256을 요구한다. 일반 API에는 삭제 기능 없음.
- 최종 ID 목록: [manifest-v2](P5-CODEX-098-qwen-manifest-v2.json), 정규화 SHA256 `61c949c42f03b1678a91d1ea06305c3c7301cf887bb456a65e6381df499bc6b0`.
- 최초 manifest는 원문 엔진 기록이 없는 실패 응답 13개를 보수적으로 제외했다. 실제 호출 수·정확한 모델 메타데이터·고정 원고 프롬프트·명시적 재평가 lineage를 추가 확인한 뒤 v2를 확정했다. v1은 적용하지 않았다.
- 원고 근거: provider=local + 정확한 Qwen 생성 모델/실행 결과, 또는 실제 Qwen 호출과 llama.cpp 엔진을 기록한 원고 평가. 모델 이름만 언급한 비교 평가/Codex 기사는 대상이 아니다. 확인된 원고 모델은 1.7B/4B이며, 0.6B/8B의 연결 원고는 확인되지 않았다.

| 구분 | Dry Run | 실제 삭제 |
|---|---:|---:|
| 원고 그룹 | 7 | 7개 그룹의 원고 내용 제거 |
| Content Version | 23 | 23 |
| 원고 품질 Evaluation | 41 | 41 |
| 전용 실험 Evaluation | 36 | 36 |
| SEO 검사 | 27 | 27 |
| 생성 stage | 74 | 74 |
| 생성 attempt | 2 | 2 |
| 생성 result | 11 | 11 |
| 생성 target | 16 | 16 |
| 전용 생성 Job | 4 | 4 |
| Publishing Job | 0 | 0 |
| 보호 참조 충돌 | 0 | 0 |

관련 9개 테이블 총234행 삭제. 전용 실패 artifact 대상0. 공유 출처·Research Package·운영 감사·승인·실제 Publishing Job·Blogger 기록은 보존한다. 빈 그룹/지역화 identity와 과거 agent 실행 identity, 독립 모델 성능 측정 및 모델 파일은 삭제 범위가 아니다.

소유자 트랜잭션에서 테이블 잠금 후 manifest 재검증, 정확한 PK별 삭제, 건수 비교, 비대상 Version 집합/보호 테이블 건수 보존 검사를 수행했다. 해당 테이블의 deny_mutation trigger만 트랜잭션 안에서 잠시 중지하고 재활성화했으며 FK/감사 trigger는 유지했다. 불일치 시 전체 롤백. 삭제 감사 이벤트에 최종 manifest와 건수를 영구 기록했다.

보호 결과: Codex 계열 Import71(예약17/Trends36/수동18), Import-Version 연결86, Publishing LIVE17, Blogger Draft3 모두 유지. 정리 직후 남은 Content Version423개 보존. 이후 새 정상 작성 데이터 증가는 허용하며 기존 데이터를 삭제하지 않는다.

## 구현·검증 체크포인트

- 조회 로직 예상/직접 조회 결과: 대기0 / 검토40 / 게시 완료17 / 실패·보류17 / 자동발행실패7. 원격 Draft는 LIVE와 별도 표시한다.
- 필터/검색을 모든 탭 집계와 목록에 동일하게 적용하고 범위를 벗어난 페이지를 유효 페이지로 보정한다.
- 집중 격리 pytest **49 passed, 37 deselected**. Qwen Hard Delete/비교 원고 보호/manifest 변경 롤백/Job 보호/trigger 복구, 버전별 LIVE 해결 SQL, 잘못된 블로그·Import·과거 버전·Draft·미검증 기록 제외, 제목/집계/페이지 정합성, P097 쓰기0·수동 모드·Import/키워드 회귀 포함.
- Ruff 통과, 변경 모듈 mypy 통과. 실제 브라우저·최종 빌드·서비스 반영 결과는 후속 체크포인트에 추가한다.

## 수정 파일 및 Git

`publications.py`, `publication_monitor.py`, `publication_read_state.py`, `qwen_cleanup.py`, owner 전용 cleanup CLI, Publishing/Worker UI, 집중 Python/Playwright 테스트, 두 Dry Run manifest와 본 기록.

Schema75 유지, 새 Migration 불필요. main 변경 없음. 자기 참조 커밋은 `git log --grep P5-CODEX-098`와 최종 기록으로 연결한다. 기존 미추적 Playwright artifact 폴더는 보존한다.
