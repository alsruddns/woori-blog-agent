# P5-CODEX-145 — 중복 검토 목록의 두 과거 원고 제외

- 작업 일시: 2026-11-05 14:37–14:38 KST
- 브랜치: `develop`
- 시작 HEAD: `fa9dd99fe61746e883cd78a11009dd034124c25a`
- 작업 시작 감사: `agent.work.started`, ID `374262`
- 변경 사유: 사용자가 폐기해도 검토 필요 목록에서 남아 있는 두 과거 원고를 제거해 달라고 요청함.

## 조사 및 원인

대상 원고는 Trend Journal EN의 두 `manual_codex_import` 콘텐츠 버전이다.

| Version ID | 원고 제목 | Import ID |
|---|---|---|
| `9b023ae4-b4a2-4d34-9f0b-d33ce96f483f` | Official Agency policy change and reporting calendar | `438d8b3a-39c8-48bb-a8b1-56154f488739` |
| `86cae11d-f851-40e1-b8cb-a073e45f1d5a` | Official Agency policy change and reporting schedule | `b78c4925-4bc1-403d-a5c4-57741afda0a1` |

작업 전 읽기 전용 확인에서 두 버전의 `manuscript_discards` 기록은 없었다. 2026-11-05 13:37 KST의 기존 폐기 이벤트(ID `373079`)에는 여러 유사 제목 원고가 성공으로 기록됐지만 위 두 Version ID는 포함되지 않았다. 따라서 과거 폐기 요청은 비슷한 제목의 다른 원고들을 대상으로 했고, 이 두 정확한 항목에는 적용되지 않은 상태였다.

## 조치 및 결과

- 기존 `/publications/discards` 처리 경로와 트랜잭션 advisory lock을 사용해 위 두 ID만 검토 목록에서 제외했다.
- 두 `manuscript_discards` 상태는 `discarded`로 저장됐다. 목록 조회는 이 상태를 읽고 검토 후보에서 제외한다.
- 물리 삭제는 하지 않았다. 두 항목은 Import provenance와 콘텐츠 버전이므로 보존했고, 삭제 대신 되돌릴 수 있는 기존 폐기 기능을 사용했다.
- 각 항목은 `manual_codex_import`; 연결된 발행 Job 0건, Blogger 게시 기록 0건이다.
- 폐기 감사 이벤트: `publication.manuscripts.discarded`, ID `374263`, 성공 2건/실패 0건.
- 사후 읽기 전용 검증에서 두 대상 모두 폐기 상태, Import 연결 유지, Job 0건, 게시 기록 0건을 확인했다.
- 작업 중 Blogger 쓰기 이벤트: 0건.
- 완료 감사 이벤트: `agent.work.completed`, ID `374266`.

## 검증·변경 범위

- 코드는 변경하지 않았다. 실제 운영 DB에서 지정된 두 콘텐츠 버전의 검토 노출 상태만 기존 관리 경로로 변경했다.
- 자동화된 코드 테스트는 실행하지 않았다. 상태 변경 전후를 PostgreSQL에서 읽기 전용으로 검증했다.
- 원고 본문, Import, 감사 기록, Blogger OAuth, 게시 이력, 예약 작업은 삭제·수정하지 않았다.
- Git 기록 커밋은 이 문서와 후속 `git log`로 확인한다.
