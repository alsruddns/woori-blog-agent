# Phase 2 Blogger 읽기 연동

Dashboard 3100 → 동일 출처 BFF → FastAPI 8100 → Google OAuth/읽기 API. PostgreSQL은 기존 5432와 프로젝트 전용 DB를 유지한다. 브라우저에 관리자 bearer나 Google 토큰을 전달하지 않는다. FastAPI CORS는 열지 않으며 브라우저의 외부 출처 요청은 Next Host/Origin 검사에서 차단한다. OAuth 콜백은 state와 HttpOnly 브라우저 바인딩으로 보호하는 별도 GET 경로다.

## OAuth
Google 웹 클라이언트, blogger.readonly, offline access, 동의 화면, PKCE S256을 사용한다. state 원문 대신 SHA-256 해시와 바인딩 해시를 10분간 저장하고 원자적으로 한 번만 소비한다. PKCE verifier·Access/Refresh 토큰은 Fernet으로 암호화한다. 암호화 키는 Git 제외 환경 설정에만 보관한다. 비밀 데이터는 운영 API 조회나 감사 payload에서 제외한다.

토큰 갱신은 연결 행 잠금으로 직렬화한다. 만료 60초 전에 갱신하고 invalid_grant는 취소 상태로 전환한다. 읽기의 401은 강제 갱신 후 한 번 다시 시도한다. 계속 거절되면 재인증을 요구한다. 연결 해제는 Google revoke를 시도하고 실패해도 로컬 토큰을 제거하며 원격 권한 수동 정리를 안내한다. 취소된 pending state는 다시 사용할 수 없다.

Next logging=false와 API 실행의 --no-access-log로 OAuth 코드가 query 로그에 남지 않도록 한다. 콜백은 비밀값 없는 결과 URL로 303 리디렉션하고 쿠키를 지우며 Referrer-Policy:no-referrer를 적용한다. 루프백 HTTP의 쿠키는 Secure=false, HttpOnly, SameSite=Lax, callback 경로 한정이다. 외부 서비스로 배포하려면 별도 인증·HTTPS·Secure 쿠키 설계가 필요하다.

## Blogger 읽기
blogger_service가 DB의 활성 언어·블로그·읽기 제한·OAuth 상태를 확인한다. Google getByUrl ID와 등록 host를 대조하고 AUTHOR view 게시글 조회를 성공시켜 연결을 검증한다. 기존 Blog ID와 다르면 덮어쓰지 않는다. 게시글 목록은 live/draft/scheduled, 페이지 토큰, 언어별 페이지 크기를 지원한다. 상세 본문은 UI에서 텍스트로만 표시하며 외부 HTML을 실행하지 않는다.

GET만 재시도하며 network/429/일부 quota 403/5xx는 최대 3회, 지수 지연·jitter와 Retry-After를 적용하되 최대 5초로 제한한다. 일반 권한 부족·404·잘못된 요청은 재시도하지 않는다. 언어별 분당 할당은 DB advisory lock과 감사된 요청 예약으로 원자적으로 계산한다. 동일 언어의 복수 블로그가 같은 할당을 공유한다.

각 API 시도는 request UUID, 블로그/연결/언어 참조, 작업명, 시도 횟수, 안전한 오류 분류와 HTTP 상태를 저장한다. Google 오류 원문, 요청 헤더, 토큰, 인증 코드, 게시글 원문은 이력에 저장하지 않는다.

## 쓰기와 로컬 콘텐츠
BloggerWriter는 httpx.MockTransport만 수용한다. 일반 전송이나 환경변수로 운영 쓰기를 켤 수 없고 관리 HTTP API도 운영 쓰기 경로를 노출하지 않는다. Mock에서 초안 isDraft=true, publish, publishDate 예약, PATCH 수정, DELETE 삭제 프로토콜을 검증한다. DB 멱등성 원장은 요청 fingerprint·pending/succeeded/uncertain 상태를 유지한다. 같은 키의 결과는 재사용하고 다른 본문이나 모호한 실패의 재시도는 차단한다. 이것이 실운영의 Google 중복 방지 검증을 대신하지는 않는다.

로컬 콘텐츠 관리 POST는 기존 그룹/현지화에 새 불변 버전을 추가하며, 버전 번호는 현지화별 advisory lock으로 직렬화한다. 로컬 저장은 Blogger 초안 생성과 구분한다. 국가별 정책과 source_version 같은 그룹 제약을 유지한다. 카테고리 연결은 추가만 지원하며 과거 콘텐츠를 삭제하지 않는다. AI 생성·SEO 검증·자동 발행은 계속 차단한다.

공식 문서: [OAuth](https://developers.google.com/identity/protocols/oauth2/web-server), [Blogger 읽기/쓰기](https://developers.google.com/blogger/docs/3.0/getting_started), [publish 및 publishDate](https://developers.google.com/blogger/docs/3.0/reference/posts/publish).
