# P5-CODEX-148 검토 필요 중복 원고 제외 및 Trends 검색량 컬럼 분리

## 작업 정보

- 작업 시각: 2026-11-05 KST
- 시작 브랜치: `develop`
- 시작 HEAD / origin/develop: `742596f9c0d29ca5747caf3a35295fe6f787d373`
- 시작 감사: append-only `agent.work.started`, ID `376290`
- 운영 schema/settings revision: schema 92 / revision 23

## 원인과 운영 데이터 처리

기존 두 지정 버전(`9b023ae4-b4a2-4d34-9f0b-d33ce96f483f`, `86cae11d-f851-40e1-b8cb-a073e45f1d5a`)은 이미 `manuscript_discards.status=discarded`이고 발행관리 API의 폐기 보관함에 표시됐다. 검토 필요 탭의 동일 제목 항목은 이후 별도 Import `f2db024d-a146-458f-a179-96edf9638262`에서 들어온 새 Version `73c08d7d-7814-4971-988b-1315b63a6047`이었다. 이 레코드는 별도 group을 사용해 이전 폐기 상태를 상속하지 않았으므로 검토 필요에 남아 있었다.

읽기 전용 Dry Run에서 exact version, group, Import, 대상 EN Blogger를 확인했다. 공개 LIVE 기록 0, 해당 버전 발행 Job 0, 기존 폐기 상태 없음. 본문 백업을 `.runtime/p148-target-backup.json`에 보존했고 manifest는 `.runtime/p148-dry-run-manifest.json`에 저장했다. 백업 SHA-256 `34d7367cc1d997f54a552d9e8739c1edd2e04df1419ed2f11fffa9c66522e6ec`, 본문 SHA-256 `853a3cc763acb3f5fa065172f8c2d04c23ffa7aee2c482379293ab28ba87bdaf`.

사용자 요청 범위에 맞춰 새 Version만 기존 `/admin/publications/discards` 관리 경로로 폐기했다. 물리 삭제는 하지 않았다. Import/콘텐츠/감사 이력은 보존했다. API 결과는 성공 1, 실패 0; 재조회에서 해당 버전은 review 0건, discarded 1건이었다. 이전 두 버전도 그대로 discarded다. Blogger 쓰기는 0건.

## UI 변경

발행관리 표의 Google Trends 원본 검색량을 원고 제목 아래에서 분리해 전용 `Google Trends 검색량` 컬럼으로 이동했다. 원본 `10K+` 같은 구간 표기를 그대로 표시하고, 별도 셀에서 정확한 검색 횟수가 아님을 설명한다. Trends 검색어·국가는 제목의 부가 정보로 남겼다. 모바일에서는 같은 셀에 컬럼 레이블이 표시된다. 비-Trends 원고는 `—`로 표시한다.

## 검증

- `services/api/tests/test_publications.py`: 53 passed.
- Dashboard lint: 통과.
- Dashboard typecheck: 통과.
- 전용 Playwright 회귀 테스트 `P5-CODEX-148-trends-volume-column.spec.ts` 추가: Google Trends 검색량 전용 컬럼, 원본 구간 표시, 제목 셀과 분리 여부를 확인한다.
- 운영 API read-only 조회 및 기존 폐기 관리 API mutation 이후 read-back 검증 통과.
- 실제 Blogger POST/PATCH/DELETE: 0.
- 운영 빌드/서비스 반영/재기동 및 Playwright 결과는 완료 후 이 문서의 후속 절에 기록한다.

## 변경 파일

- `apps/dashboard/app/publishing/publication-manager.tsx`
- `apps/dashboard/app/style.css`
- `apps/dashboard/e2e/P5-CODEX-148-trends-volume-column.spec.ts`
- `docs/development/P5-CODEX-148.md`

## 남은 확인

운영 UI 컬럼은 빌드/배포 후 Playwright로 확인한다. 이전 폐기 대상과 이번 새 Import의 원고/Import provenance는 삭제하지 않는다.
