# P5-CODEX-143 — Ignore local generated pending artifacts

- 작업 일시: 2026-11-05 KST.
- 시작 HEAD: bd27ea974889f38992c135748be70ea6efc7136d, branch develop.
- 작업 시작 감사: append-only agent.work.started, ID 373098.
- 작업 완료 감사: append-only agent.work.completed, ID 373099.
- 변경 사유: 로컬 Playwright 검사 결과와 격리 pytest 출력 폴더 다수가 Git pending changes에 표시됐다.
- 기존 문제: .playwright-mcp/, 다수 .pytest-* 폴더, Windows 임시 경로가 저장소 미추적 파일로 노출됐다. 개발 기록용 PNG 두 개도 pending 상태였다.
- 변경 목적: 재생성 가능한 로컬 검사 산출물을 Git 상태에서 제외하되, 실제 프로젝트 JSON/YAML/TOML/TXT 소스와 테스트 자료는 계속 추적 가능하게 둔다.
- 변경 전 상태: 해당 로컬 산출물 디렉터리와 개발용 PNG가 미추적 상태였다.
- 변경 후 상태: .gitignore에서 Playwright/pytest 산출물과 확인된 임시 경로 및 두 PNG 패턴을 제외한다. 파일은 삭제하지 않았다.
- 수정 파일: .gitignore, docs/development/P5-CODEX-143.md.
- 테스트 결과: git check-ignore와 git status로 규칙 적용 및 남은 변경을 확인한다. 코드 테스트는 실행하지 않았다(무시 규칙만 변경).
- 운영 영향: 없음. 데이터베이스, 서비스, 예약, OAuth, 게시 이력은 변경하지 않았다.
- 커밋 해시: 후속 Git 기록에서 확인한다.
- 관련 문서: 이 기록.
- 남은 문제: 사용자가 원하는 새 로컬 생성물 경로가 추가되면 해당 경로를 검토해 규칙에 명시한다. 확장자 전체를 무시하지 않아 프로젝트 소스의 실수로 인한 누락을 방지한다.
