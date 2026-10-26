# Google Blogger OAuth 설정

Google 계정 비밀번호는 앱에 입력하지 않는다. Google 인증 화면에서 직접 로그인하고 승인한다. Phase 2는 blogger.readonly만 요청하며 게시글 쓰기는 Mock에서만 검증한다.

1. Google Cloud Console에서 전용 프로젝트를 선택하고 Blogger API v3를 활성화한다.
2. Google Auth Platform에서 앱 이름·지원 이메일·대상 사용자 유형을 설정한다. 테스트 모드이면 실제 승인할 계정을 테스트 사용자로 추가한다.
3. OAuth 클라이언트 유형은 웹 애플리케이션으로 만들고 승인된 리디렉션 URI를 정확히 `http://127.0.0.1:3100/api/blogger/callback`로 등록한다.
4. 프로젝트 루트의 Git 제외 `.env`에 `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`을 추가한다. 기존 DATABASE_URL/ADMIN_TOKEN은 유지한다. 비밀값을 채팅·스크린샷·Git에 넣지 않는다.
5. `scripts/setup-oauth-key.py`로 토큰 암호화 키를 생성한다. 기존 키는 덮어쓰지 않는다. 키는 DB 백업과 분리해서 안전하게 백업한다. 키를 잃으면 저장된 토큰을 복호화할 수 없어 재인증해야 한다.
6. API와 Next.js를 재시작하고 `http://127.0.0.1:3100/blogger`에서 Google 읽기 권한 연결을 시작한다. 같은 브라우저와 127.0.0.1 호스트로 승인 흐름을 완료한다.
7. 연결 완료 후 각 블로그의 연결/검증 버튼을 누른다. Blog ID는 getByUrl 응답에서만 저장한다. Google 계정이 해당 블로그 접근 권한을 보유해야 한다.

OAuth는 일회용 10분 state, 브라우저 HttpOnly SameSite=Lax 바인딩 쿠키, PKCE S256을 사용한다. 토큰은 Fernet으로 암호화해 PostgreSQL에 저장한다. 갱신·취소·권한 부족은 재연결 상태로 표시한다. 연결 해제는 Google 토큰 취소 요청 후 로컬 토큰을 제거하며 원격 취소 실패는 별도 표시한다.

테스트 모드의 Google 앱은 정책에 따라 갱신 토큰이 조기 만료될 수 있다. 자동화 장기 운영 전 동의 화면·게시 상태·검증 요구사항을 확인한다. 계정 권한이나 Google 보안 화면은 사용자가 직접 처리한다.

공식 참고: [웹 서버 OAuth](https://developers.google.com/identity/protocols/oauth2/web-server), [Blog ID 조회](https://developers.google.com/blogger/docs/3.0/reference/blogs/getByUrl), [읽기·쓰기 API 구분](https://developers.google.com/blogger/docs/3.0/getting_started).
