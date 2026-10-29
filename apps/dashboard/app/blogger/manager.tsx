"use client";
import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
type Blog = {
  id: string;
  url: string;
  language_code: string;
  display_name: string;
  active: boolean;
  blog_id: string | null;
  oauth_connection_id: string | null;
  connection_verified_at: string | null;
  oauth_status: string | null;
  connection_error: string | null;
  oauth_scopes: string[] | null;
  oauth_expires_at: string | null;
};
type Connection = {
  id: string;
  label: string;
  status: string;
  scopes: string[];
  created_at: string;
  expires_at: string | null;
  has_refresh_token: boolean;
  error_category: string | null;
  blogger_user_id: string | null;
  identity_verified_at: string | null;
  verified_blog_count: number;
  verified_blogs: { language_code: string; url: string; blog_id: string }[] | null;
  access_verified_at: string | null;
};
type Post = {
  id: string;
  title: string;
  status?: string;
  content?: string;
  published?: string;
};
type Limit = {
  language_code: string;
  read_enabled: boolean;
  requests_per_minute: number;
  max_page_size: number;
};
type State = {
  configured: boolean;
  writes_enabled: false;
  common_connection: {
    cost_calls_allowed: boolean;
    cost_block_reason: string | null;
    cost_approval_at: string | null;
    cost_approval_scope: string[];
    approval_required: boolean;
    identity_verified: false;
    write_oauth_start_blocked: boolean;
  };
  draft_creation_allowed: boolean;
  publishing_enabled: false;
  connections: Connection[];
  blogs: Blog[];
  limits: Limit[];
  calls: {
    id: number;
    operation: string;
    status: string;
    error_category: string | null;
    created_at: string;
  }[];
  events: { id: number; event_type: string; created_at: string }[];
  draft_results: {
    mode: string;
    preview_id: string;
    blog_record_id: string;
    blog_id: string;
    language_code: string;
    title: string;
    content: string;
    is_draft: boolean;
    final_status?: string;
    external_post_id?: string | null;
    http_status?: number | null;
    verification?: {
      checked: boolean;
      is_draft: boolean | null;
      title_matches: boolean | null;
      content_matches: boolean | null;
    };
  }[];
};
type CommonVerification = {
  verification_id: string;
  connection_id: string;
  verified_blog_count: number;
  blogger_user_id: string;
  email_verified: false;
  blogs: {
    blog_record_id: string;
    language_code: string;
    url: string;
    blog_id: string;
    previous_connection_id: string | null;
  }[];
  identity_verified: false;
  writes_enabled: false;
};
type DraftPreview = {
  preview_id: string;
  blog_id: string;
  language_code: string;
  title: string;
  content: string;
  is_draft: true;
  external_call_made: false;
};

const draftCopy: Record<string, { title: string; content: string }> = {
  ko: {
    title: "Woori Blog Agent 연결 확인 테스트 (비공개 초안)",
    content:
      "이 글은 Woori Blog Agent의 Blogger API 연결을 확인하기 위한 비공개 테스트 초안입니다.\n\n실제 정보 제공을 목적으로 하지 않으며, 사용자 승인 없이 공개 게시되지 않습니다.",
  },
  en: {
    title: "Woori Blog Agent Connection Test (Private Draft)",
    content:
      "This is a private test draft used to verify the Woori Blog Agent Blogger API connection.\n\nIt is not intended to provide factual information and will not be published without separate user approval.",
  },
  "zh-CN": {
    title: "Woori Blog Agent 连接测试（私人草稿）",
    content:
      "这是一篇用于验证 Woori Blog Agent Blogger API 连接的私人测试草稿。\n\n本文不用于提供事实信息，未经用户另行批准不会公开发布。",
  },
  ja: {
    title: "Woori Blog Agent 接続テスト（非公開の下書き）",
    content:
      "これは Woori Blog Agent の Blogger API 接続を確認するための非公開テスト下書きです。\n\n情報提供を目的とするものではなく、ユーザーの別途承認なしに公開されません。",
  },
};
export default function Manager({ initial }: { initial: State }) {
  const router = useRouter();
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const writeConnections = initial.connections.filter(
    (c) =>
      c.status === "connected" &&
      c.scopes?.length === 1 &&
      c.scopes.includes("https://www.googleapis.com/auth/blogger"),
  );
  const [account, setAccount] = useState(writeConnections[0]?.id ?? "");
  const [commonVerification, setCommonVerification] =
    useState<CommonVerification | null>(null);
  const [draftPreview, setDraftPreview] = useState<DraftPreview | null>(null);
  const [selected, setSelected] = useState("");
  const [postStatus, setPostStatus] = useState("live");
  const [items, setItems] = useState<Post[]>([]);
  const [next, setNext] = useState("");
  const [detail, setDetail] = useState<Post | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [info, setInfo] = useState<Record<string, string>>({});
  const [versions, setVersions] = useState<
    {
      id: string;
      group_id: string;
      language: string;
      version: number;
      title: string;
      body: string;
    }[]
  >([]);
  async function call(path: string, method = "GET", body?: unknown) {
    const response = await fetch(`/api/blogger/${path}`, {
      method,
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "요청 실패");
    return data;
  }
  async function action(path: string, body: unknown = {}) {
    setBusy(true);
    setMessage("");
    try {
      const data = await call(path, "POST", body);
      if (data.tested)
        setInfo((i) => ({
          ...i,
          [path.split("/")[1]]:
            `연결 정상 · API 게시글 수 ${data.posts?.totalItems ?? "제공되지 않음"}`,
        }));
      if (data.remote_revoked === false)
        setMessage(
          "로컬 연결은 해제했습니다. Google 권한 페이지에서 원격 권한 취소를 확인하세요.",
        );
      else setMessage("요청을 완료하고 감사 기록을 저장했습니다.");
      router.refresh();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "요청 실패");
    } finally {
      setBusy(false);
    }
  }
  async function start(permission: "read" | "write") {
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch("/api/blogger/oauth/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ permission }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error);
      window.location.assign(data.authorization_url);
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "OAuth 실패");
      setBusy(false);
    }
  }
  async function verifyCommonConnection() {
    if (!account) return;
    setBusy(true);
    setMessage("");
    setCommonVerification(null);
    try {
      const result = await call("common-connection/verify", "POST", {
        connection_id: account,
      });
      setCommonVerification(result as CommonVerification);
      setMessage(
        `Blogger profile ID ${result.blogger_user_id}; ${result.verified_blog_count}개 블로그 접근을 확인했습니다. Google 이메일은 요청하지 않았고 기존 매핑은 변경되지 않았습니다.`,
      );
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "공통 연결 검증 실패");
    } finally {
      setBusy(false);
    }
  }
  async function assignCommonConnection() {
    if (!commonVerification || commonVerification.connection_id !== account) return;
    const approved = window.confirm(
      `선택한 OAuth 연결을 ${commonVerification.verified_blog_count}개 활성 블로그의 공통 읽기·쓰기 연결로 지정합니다. 기존 읽기 매핑은 대체됩니다. 실제 게시·수정·삭제와 자동 발행은 계속 차단됩니다. 진행할까요?`,
    );
    if (!approved) return;
    setBusy(true);
    setMessage("");
    try {
      const result = await call("common-connection/assign", "POST", {
        connection_id: account,
        verification_id: commonVerification.verification_id,
        approval: "I_APPROVE_SHARED_BLOGGER_CONNECTION",
      });
      setCommonVerification(null);
      setMessage(
        `${result.blog_count}개 블로그에 공통 OAuth 연결을 지정했습니다. 실제 게시 권한은 활성화되지 않았습니다.`,
      );
      router.refresh();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "공통 연결 지정 실패");
    } finally {
      setBusy(false);
    }
  }
  async function prepareDraft(blog: Blog) {
    const copy = draftCopy[blog.language_code];
    if (!copy || !account) return;
    setBusy(true);
    setMessage("");
    setDraftPreview(null);
    try {
      const result = await call(`blogs/${blog.id}/drafts/preview`, "POST", {
        connection_id: account,
        title: copy.title,
        content: copy.content,
      });
      setDraftPreview(result as DraftPreview);
      setMessage("미리보기를 저장했습니다. 이 단계에서는 Blogger API를 호출하지 않았습니다.");
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "초안 미리보기 생성 실패");
    } finally {
      setBusy(false);
    }
  }
  async function confirmDraft() {
    if (!draftPreview) return;
    const blog = initial.blogs.find((b) => b.blog_id === draftPreview.blog_id);
    const details = [
      `대상: ${blog?.url ?? draftPreview.blog_id}`,
      `Blog ID: ${draftPreview.blog_id}`,
      `언어: ${draftPreview.language_code}`,
      `제목: ${draftPreview.title}`,
      `본문:\n${draftPreview.content}`,
      "요청: Blogger posts.insert, isDraft=true (비공개 초안)",
      "공개 게시·수정·삭제는 수행하지 않습니다.",
    ].join("\n\n");
    if (!window.confirm(`${details}\n\n이 초안 1건 생성을 승인합니까?`)) return;
    setBusy(true);
    setMessage("");
    try {
      const result = await call(`draft-previews/${draftPreview.preview_id}/confirm`, "POST", {
        confirmation: "I_APPROVE_THIS_PRIVATE_DRAFT",
      });
      setMessage(result.final_status === "queued"
        ? "명시적으로 승인한 비공개 초안을 게시 Worker 큐에 등록했습니다. Worker 처리 전에는 Blogger API 쓰기 호출이 없습니다."
        : `비공개 초안 상태: ${result.external_post_id ?? result.error_category ?? result.final_status}. 공개 게시하지 않았습니다.`);
      setDraftPreview(null);
      router.refresh();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "초안 생성 실패");
      router.refresh();
    } finally {
      setBusy(false);
    }
  }
  async function list(blog: string, page = "") {
    setBusy(true);
    setMessage("");
    try {
      const data = await call(
        `blogs/${blog}/posts?${new URLSearchParams({ status: postStatus, page_token: page })}`,
      );
      setItems(data.items ?? []);
      setNext(data.nextPageToken ?? "");
      setSelected(blog);
      setLoaded(true);
      setDetail(null);
      router.refresh();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "조회 실패");
    } finally {
      setBusy(false);
    }
  }
  async function loadDetail(post: string) {
    setBusy(true);
    try {
      setDetail(await call(`blogs/${selected}/posts/${post}`));
      router.refresh();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "조회 실패");
    } finally {
      setBusy(false);
    }
  }
  async function limits(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    setBusy(true);
    try {
      await call(`limits/${f.get("language_code")}`, "PUT", {
        read_enabled: f.get("read_enabled") === "on",
        requests_per_minute: Number(f.get("requests_per_minute")),
        max_page_size: Number(f.get("max_page_size")),
      });
      setMessage("언어별 실행 제한을 저장했습니다. 발행은 계속 차단됩니다.");
      router.refresh();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "저장 실패");
    } finally {
      setBusy(false);
    }
  }
  async function content(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    setBusy(true);
    try {
      const data = await call("content", "POST", {
        language_code: f.get("language_code"),
        target_country: f.get("target_country"),
        title: f.get("title"),
        body: f.get("body"),
        group_id: f.get("group_id") || null,
        source_version_id: f.get("source_version_id") || null,
      });
      setMessage(
        `로컬 버전 ${data.version} 저장 · 그룹 ${data.group_id}. Blogger 요청은 수행하지 않았습니다.`,
      );
      setVersions((await call("content")).versions);
      router.refresh();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "저장 실패");
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <p role="status" aria-live="polite">
        {message}
      </p>
      <h2>Google OAuth</h2>
      {!initial.configured && (
        <p>
          Google Cloud의 OAuth 클라이언트 설정이 필요합니다.{" "}
          <a
            href="https://github.com/alsruddns/woori-blog-agent/blob/develop/docs/operations/google-oauth.md"
            target="_blank"
            rel="noreferrer"
          >
            설정 가이드
          </a>
        </p>
      )}
      <button disabled={busy || !initial.configured} onClick={() => start("read")}>
        Google 읽기 권한 연결
      </button>
      <button
        disabled={
          busy ||
          !initial.configured ||
          initial.common_connection.write_oauth_start_blocked
        }
        onClick={() => start("write")}
      >
        Blogger 쓰기 권한 연결 (Google 동의 화면)
      </button>
      <p>
        Blogger 전체 권한 scope 하나로 API 읽기와 쓰기 권한 범위를 모두 지원합니다. 연결된 Google 계정의
        신원은 확인·추정하지 않습니다. 사용자가 매 요청을 확인한 비공개 초안 테스트 외의 게시·예약·수정·삭제와 자동 발행은 계속 차단됩니다.
        {initial.common_connection.write_oauth_start_blocked && " 사용 가능한 쓰기 연결 또는 진행 중인 동의가 있어 새 연결 생성은 비활성화했습니다."}
      </p>
      <ul>
        {initial.connections.map((c) => (
          <li key={c.id}>
            {c.label} · {c.status}
            {` · 읽기 ${c.scopes?.some((scope) => scope === "https://www.googleapis.com/auth/blogger.readonly" || scope === "https://www.googleapis.com/auth/blogger") ? "허용" : "없음"}`}
            {` · 쓰기 ${c.scopes?.includes("https://www.googleapis.com/auth/blogger") ? "OAuth 범위 있음" : "없음"}`}
            {` · 연결 ${c.created_at}`}
            {c.blogger_user_id && ` · Blogger profile ID ${c.blogger_user_id} (확인 ${c.identity_verified_at ?? "시각 미상"})`}
            {` · 접근 검증 ${c.verified_blog_count}개 (${c.access_verified_at ?? "미검증"})`}
            {` · 만료 ${c.expires_at ?? "미확인"}`}
            {` · 갱신 토큰 ${c.has_refresh_token ? "암호화 저장됨" : "없음"}`}
            {c.error_category && ` · ${c.error_category}`}{" "}
            {c.status !== "disconnected" && (
              <button
                disabled={busy}
                onClick={() => action(`oauth/${c.id}/disconnect`)}
              >
                Google 연결 해제
              </button>
            )}
          </li>
        ))}
      </ul>
      <label>
        공통으로 지정할 기존 쓰기 OAuth 연결
        <select value={account} onChange={(e) => setAccount(e.target.value)}>
          <option value="">연결 선택</option>
          {writeConnections.map((c) => (
              <option key={c.id} value={c.id}>
                {c.label} · {c.created_at} · {c.blogger_user_id ? `Blogger ${c.blogger_user_id}` : c.id.slice(0, 8)}
              </option>
          ))}
        </select>
      </label>
      <p>
        기존 블로그별 읽기 매핑은 유지됩니다. Blogger 전용 비용 정책: {initial.common_connection.cost_calls_allowed ? "소유자 승인 기록으로 허용" : `차단 (${initial.common_connection.cost_block_reason ?? "확인 필요"})`}.
        비용 검증 및 각 블로그 접근 확인 전에는 검증 버튼을 사용할 수 없습니다.
        {initial.common_connection.cost_approval_at && ` Blogger 전용 승인 기록: ${initial.common_connection.cost_approval_at}.`}
      </p>
      <button
        disabled={busy || !account || !initial.common_connection.cost_calls_allowed}
        onClick={verifyCommonConnection}
      >
        읽기 전용으로 공통 연결 검증
      </button>
      {commonVerification && commonVerification.connection_id === account && (
        <section aria-label="공통 OAuth 연결 검증 결과">
          <p>
            Blogger profile ID {commonVerification.blogger_user_id} · {commonVerification.verified_blog_count}개 블로그 접근 확인. 이메일 동의는 요청하지 않았으며 Google 계정 이메일은 미확인.
          </p>
          <ul>
            {commonVerification.blogs.map((blog) => (
              <li key={blog.blog_record_id}>
                {blog.language_code} · {blog.url} · Blog ID {blog.blog_id}
              </li>
            ))}
          </ul>
          <button disabled={busy} onClick={assignCommonConnection}>
            검증된 연결을 공통 연결로 지정 (명시적 승인)
          </button>
        </section>
      )}
      <p>
        실제 비공개 초안 테스트는 공통 연결의 최근 전체 블로그 접근 검증 후에만 준비할 수 있습니다. 초안 미리보기 저장은 Blogger를 호출하지 않으며, 별도 확인 버튼을 눌러야 해당 블로그에 posts.insert(isDraft=true) 1회가 전송됩니다. 공개 게시와 자동 발행은 비활성입니다.
      </p>
      <h2>등록 블로그</h2>
      <label>
        게시글 조회 상태
        <select
          value={postStatus}
          onChange={(e) => {
            setPostStatus(e.target.value);
            setLoaded(false);
            setNext("");
          }}
        >
          <option value="live">발행됨</option>
          <option value="draft">초안</option>
          <option value="scheduled">예약됨</option>
        </select>
      </label>
      <div className="grid">
        {initial.blogs.map((b) => (
          <article key={b.id}>
            <h3>{b.display_name}</h3>
            <p>
              {b.language_code} · {b.active ? "활성" : "비활성"}
            </p>
            <a href={b.url} target="_blank" rel="noreferrer">
              {b.url}
            </a>
            <p>Blog ID: {b.blog_id ?? "미확인"}</p>
            <p>
              {b.connection_verified_at && b.oauth_status === "connected"
                ? "읽기 연결 검증 완료"
                : "미연결 / 재검증 필요"}
            </p>
            <p>
              매핑된 연결 권한: 읽기 {b.oauth_scopes?.some((scope) => scope === "https://www.googleapis.com/auth/blogger.readonly" || scope === "https://www.googleapis.com/auth/blogger") ? "허용" : "없음"}
              {" · 쓰기 "}
              {b.oauth_scopes?.includes("https://www.googleapis.com/auth/blogger") ? "OAuth 범위 있음 (쓰기 API 미검증·차단)" : "없음"}
              {" · 토큰 만료 "}{b.oauth_expires_at ?? "미확인"}
            </p>
            {b.connection_error && <p role="alert">{b.connection_error}</p>}
            <div className="actions">
              <button
                disabled={busy || !account || !b.active}
                onClick={() =>
                  action(`blogs/${b.id}/connect`, { connection_id: account })
                }
              >
                연결·ID 검증
              </button>
              <button
                disabled={busy || !account || !initial.draft_creation_allowed || !draftCopy[b.language_code]}
                onClick={() => prepareDraft(b)}
              >
                테스트 초안 미리보기
              </button>
              <button
                disabled={
                  busy ||
                  !b.connection_verified_at ||
                  b.oauth_status !== "connected"
                }
                onClick={() => action(`blogs/${b.id}/test`)}
              >
                API 연결 테스트
              </button>
              <button
                disabled={
                  busy ||
                  !b.connection_verified_at ||
                  b.oauth_status !== "connected"
                }
                onClick={() => list(b.id)}
              >
                게시글 조회
              </button>
              <button
                disabled={busy || !b.oauth_connection_id}
                onClick={() => action(`blogs/${b.id}/disconnect`)}
              >
                블로그 연결 해제
              </button>
            </div>
            {info[b.id] && <p>{info[b.id]}</p>}
          </article>
        ))}
      </div>
      {draftPreview && (
        <section aria-label="실제 Blogger 비공개 초안 최종 확인">
          <h2>실제 Blogger 비공개 초안 최종 확인</h2>
          <p>대상 블로그: {initial.blogs.find((b) => b.blog_id === draftPreview.blog_id)?.url}</p>
          <p>Blog ID: {draftPreview.blog_id} · 언어: {draftPreview.language_code}</p>
          <p>제목: {draftPreview.title}</p>
          <pre className="content-text">{draftPreview.content}</pre>
          <p>실제 API 요청: POST posts.insert · isDraft=true. 공개 게시, 수정, 삭제, 자동 발행은 수행되지 않습니다.</p>
          <button disabled={busy || draftPreview.external_call_made} onClick={confirmDraft}>
            이 블로그의 비공개 초안 1건 생성 승인
          </button>
          <button disabled={busy} onClick={() => setDraftPreview(null)}>취소</button>
        </section>
      )}
      <h2>실제 Blogger 초안 테스트 결과</h2>
      {initial.draft_results.length ? (
        <ul>
          {initial.draft_results.map((draft) => (
            <li key={draft.preview_id}>
              {draft.mode === "live_test_draft" ? "실제 Blogger" : "모의"} · {draft.language_code} · Blog ID {draft.blog_id} · Post ID {draft.external_post_id ?? "미생성"} · {draft.final_status ?? "승인 대기"} · HTTP {draft.http_status ?? "미요청"} · 초안 검증 {draft.verification?.checked ? (draft.verification.is_draft ? "비공개 확인" : "상태 불일치") : "미확인"}
            </li>
          ))}
        </ul>
      ) : <p>실제 초안 생성 결과가 없습니다.</p>}
      {loaded && (
        <section>
          <h2>
            조회 결과 ·{" "}
            {initial.blogs.find((b) => b.id === selected)?.display_name}
          </h2>
          {items.length ? (
            <ul>
              {items.map((p) => (
                <li key={p.id}>
                  {p.title} · {p.status ?? postStatus}{" "}
                  <button disabled={busy} onClick={() => loadDetail(p.id)}>
                    상세 조회
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p>해당 상태의 게시글이 없습니다.</p>
          )}
          {next && (
            <button disabled={busy} onClick={() => list(selected, next)}>
              다음 페이지
            </button>
          )}
        </section>
      )}
      {detail && (
        <article>
          <h3>{detail.title}</h3>
          <pre className="content-text">{detail.content}</pre>
        </article>
      )}
      <h2>언어별 실행 제한</h2>
      <ul>
        {initial.limits.map((l) => (
          <li key={l.language_code}>
            {l.language_code}: 읽기 {l.read_enabled ? "허용" : "차단"}, 분당{" "}
            {l.requests_per_minute}회, 페이지당 {l.max_page_size}개 · 실제 발행
            차단
          </li>
        ))}
      </ul>
      <fieldset disabled={busy}>
        <form onSubmit={limits}>
          <label>
            언어
            <select name="language_code">
              {initial.limits.map((l) => (
                <option key={l.language_code}>{l.language_code}</option>
              ))}
            </select>
          </label>
          <label>
            분당 호출 수
            <input
              name="requests_per_minute"
              type="number"
              min={1}
              max={60}
              defaultValue={30}
              required
            />
          </label>
          <label>
            페이지 크기
            <input
              name="max_page_size"
              type="number"
              min={1}
              max={100}
              defaultValue={20}
              required
            />
          </label>
          <label>
            <input type="checkbox" name="read_enabled" defaultChecked />
            읽기 허용
          </label>
          <button>제한 저장</button>
        </form>
      </fieldset>
      <h2>로컬 콘텐츠 버전 관리</h2>
      <p>
        새 그룹 또는 기존 그룹의 새 버전을 저장합니다. Blogger 초안 생성과
        별개인 로컬 저장입니다. 카테고리 명칭·용어집은{" "}
        <a href="/config">언어별 설정</a>에서 관리합니다.
      </p>
      <fieldset disabled={busy}>
        <form onSubmit={content}>
          <label>
            언어
            <select name="language_code">
              {initial.limits.map((l) => (
                <option key={l.language_code}>{l.language_code}</option>
              ))}
            </select>
          </label>
          <label>
            대상 국가
            <input name="target_country" placeholder="공통은 빈 값" />
          </label>
          <label>
            기존 그룹 ID
            <input name="group_id" />
          </label>
          <label>
            출처 버전 ID
            <input name="source_version_id" />
          </label>
          <label>
            제목
            <input name="title" maxLength={300} required />
          </label>
          <label>
            본문
            <textarea name="body" maxLength={50000} required />
          </label>
          <button>로컬 새 버전 저장</button>
        </form>
      </fieldset>
      <button
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          try {
            setVersions((await call("content")).versions);
          } catch (e) {
            setMessage(e instanceof Error ? e.message : "조회 실패");
          } finally {
            setBusy(false);
          }
        }}
      >
        로컬 버전 목록 조회
      </button>
      <ul>
        {versions.map((v) => (
          <li key={v.id}>
            {v.language} · v{v.version} · {v.title}
            <details>
              <summary>내용·그룹 ID</summary>
              <p>
                그룹 {v.group_id} / 버전 {v.id}
              </p>
              <pre className="content-text">{v.body}</pre>
            </details>
          </li>
        ))}
      </ul>
      <h2>최근 API 호출·오류</h2>
      {initial.calls.length ? (
        <ul>
          {initial.calls.map((c) => (
            <li key={c.id}>
              {c.created_at} · {c.operation} · {c.status}{" "}
              {c.error_category ?? ""}
            </li>
          ))}
        </ul>
      ) : (
        <p>아직 API 호출 기록이 없습니다.</p>
      )}
      <h2>최근 인증·Blogger 감사 이력</h2>
      {initial.events.length ? (
        <ul>
          {initial.events.map((e) => (
            <li key={e.id}>
              {e.created_at} · {e.event_type}
            </li>
          ))}
        </ul>
      ) : (
        <p>아직 인증·Blogger 이벤트가 없습니다.</p>
      )}
    </>
  );
}
