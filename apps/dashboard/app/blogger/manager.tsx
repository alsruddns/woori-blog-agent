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
  latest_auth_attempt_at: string | null;
  auth_attempt_count: number;
  active_auth_attempt: boolean;
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
type PublicationPolicy = { id: string; blog_id: string; active: boolean; target_country: string; timezone: string; schedule_cron: string };
type State = {
  configured: boolean;
  google_account_identity_available: boolean;
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
  publication_policies?: PublicationPolicy[];
  limits: Limit[];
  diagnostics: Record<string, { total: number; failures: number; last_event_at: string | null }>;
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
type DiagnosticPage = { items: Record<string, unknown>[]; offset: number; limit: number; total: number };

function LazyDiagnosticSection({
  title,
  summary,
  endpoint,
  filter,
}: {
  title: string;
  summary: { total: number; failures: number; last_event_at: string | null };
  endpoint: string;
  filter?: { label: string; options: { value: string; label: string }[] };
}) {
  const [page, setPage] = useState<DiagnosticPage | null>(null);
  const [offset, setOffset] = useState(0);
  const [filterValue, setFilterValue] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  async function load(nextOffset: number, selectedFilter = filterValue) {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({ offset: String(nextOffset), limit: "20" });
      if (selectedFilter) params.set(filter?.label === "결과" ? "status" : "category", selectedFilter);
      const response = await fetch(`/api/blogger/${endpoint}?${params}`, { cache: "no-store" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error ?? "기록을 불러오지 못했습니다.");
      setPage(data);
      setOffset(nextOffset);
    } catch (e) {
      setError(e instanceof Error ? e.message : "기록을 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }
  const columns = endpoint === "diagnostics/api-calls"
    ? [["created_at", "시각"], ["operation", "API 동작"], ["status", "결과"], ["http_status", "HTTP"], ["blog_name", "대상 블로그"], ["error_category", "오류"]]
    : endpoint === "diagnostics/audit-events"
      ? [["created_at", "시각"], ["event_type", "이벤트"], ["blog_name", "대상 블로그"]]
      : [["created_at", "시각"], ["mode", "유형"], ["language_code", "언어"], ["blog_id", "Blog ID"], ["external_post_id", "Post ID"], ["final_status", "결과"], ["http_status", "HTTP"], ["error_category", "오류"]];
  return (
    <details className="blogger-log-accordion" onToggle={(event) => {
      if (event.currentTarget.open && page === null && !loading) void load(0);
    }}>
      <summary>
        <span><strong>{title}</strong><small>{summary.total}건 · 오류 {summary.failures}건 · 최근 {summary.last_event_at ?? "기록 없음"}</small></span>
      </summary>
      {filter && <label className="blogger-log-filter">{filter.label}<select value={filterValue} onChange={(event) => { setFilterValue(event.target.value); void load(0, event.target.value); }}><option value="">전체</option>{filter.options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>}
      {loading && <p role="status">기록을 불러오는 중…</p>}
      {error && <p className="error-state" role="alert">{error} <button type="button" onClick={() => void load(offset)}>다시 시도</button></p>}
      {page && (page.items.length ? <div className="blogger-log-table-scroll"><table><thead><tr>{columns.map(([, label]) => <th key={label}>{label}</th>)}</tr></thead><tbody>{page.items.map((item, index) => <tr key={String(item.id ?? item.preview_id ?? `${offset}-${index}`)}>{columns.map(([key]) => <td key={key}>{key === "created_at" && item[key] ? new Date(String(item[key])).toLocaleString("ko-KR") : item[key] == null || item[key] === "" ? "—" : String(item[key])}</td>)}</tr>)}</tbody></table></div> : <p className="empty-state">해당 기록이 없습니다.</p>)}
      {page && page.total > page.limit && <div className="blogger-log-pagination"><button type="button" disabled={loading || offset === 0} onClick={() => void load(Math.max(0, offset - page.limit))}>이전</button><span>{offset + 1}–{Math.min(offset + page.items.length, page.total)} / {page.total}</span><button type="button" disabled={loading || offset + page.limit >= page.total} onClick={() => void load(offset + page.limit)}>다음</button></div>}
    </details>
  );
}

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
  const visibleConnections = initial.connections.filter(c =>
    (c.status === "connected" && c.has_refresh_token) || c.active_auth_attempt ||
    initial.blogs.some(blog => blog.oauth_connection_id === c.id));
  const [policyReason, setPolicyReason] = useState("운영 목적을 위해 설정을 변경함");
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
  const [disconnectRequest, setDisconnectRequest] = useState<{ id: string; kind: "oauth" | "blog"; label: string } | null>(null);
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
  async function changePolicy(policy: PublicationPolicy) {
    if (busy || policyReason.trim().length < 10) { setMessage("변경 사유를 10자 이상 입력하세요."); return; }
    const next = !policy.active;
    const blogName = initial.blogs.find(blog => blog.id === policy.blog_id)?.display_name ?? policy.blog_id;
    if (!window.confirm(`${blogName} · ${policy.target_country || "공통"} 발행 정책을 ${next ? "ON" : "OFF"}으로 변경합니다.\n기존 대기 Job은 다시 생성되지 않으며, OAuth·품질·승인 검사는 계속 적용됩니다.`)) return;
    setBusy(true); setMessage("");
    try {
      await call(`publication-policies/${policy.id}/active`, "POST", {
        active: next, actor_label: "Dashboard 관리자", reason: policyReason.trim(),
      });
      setMessage(`발행 정책을 ${next ? "ON" : "OFF"}으로 저장했습니다. 실제 게시 가능 여부는 다른 안전 조건도 확인하세요.`);
      router.refresh();
    } catch (error) { setMessage(error instanceof Error ? error.message : "발행 정책 저장 실패"); }
    finally { setBusy(false); }
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
        이 목록은 Google 계정 수가 아니라 OAuth 연결 레코드입니다. {initial.google_account_identity_available ? "저장된 계정 식별 정보가 있습니다." : "저장된 이메일·Google 계정 ID가 없어 고유 계정 수는 확인할 수 없습니다."} OAuth 범위는 계정 식별 근거가 아닙니다. 실제 게시·수정·삭제는 별도 승인과 운영 정책으로 제어됩니다.
        {initial.common_connection.write_oauth_start_blocked && " 사용 가능한 쓰기 연결 또는 진행 중인 동의가 있어 새 연결 생성은 비활성화했습니다."}
      </p>
      <section className="blogger-connection-summary" aria-label="OAuth 연결 요약">
        <div><span>현재 사용 중인 OAuth</span><strong>{visibleConnections.length}</strong></div>
        <div><span>연결 완료</span><strong>{initial.connections.filter((c) => c.status === "connected").length}</strong></div>
        <div><span>진행 중 인증</span><strong>{initial.connections.filter((c) => c.active_auth_attempt).length}</strong></div>
        <div><span>읽기 전용 scope</span><strong>{initial.connections.filter((c) => c.status === "connected" && c.scopes?.includes("https://www.googleapis.com/auth/blogger.readonly")).length}</strong></div>
        <div><span>전체 Blogger scope</span><strong>{initial.connections.filter((c) => c.status === "connected" && c.scopes?.includes("https://www.googleapis.com/auth/blogger")).length}</strong></div>
        <div><span>등록 Blogger / 매핑 연결</span><strong>{initial.blogs.length} / {new Set(initial.blogs.map((blog) => blog.oauth_connection_id).filter(Boolean)).size}</strong></div>
        <div><span>고유 Google 계정</span><strong>{initial.google_account_identity_available ? "확인 가능" : "확인 불가"}</strong></div>
      </section>
      <ul className="blogger-connection-list">
        {visibleConnections.map((c) => (
          <li className="blogger-connection-card" key={c.id}>
            <div className="blogger-connection-card-body">
              <div className="blogger-connection-card-heading"><div><h3>{c.label}</h3><small>OAuth 연결 레코드 · {c.id.slice(0, 8)}</small></div><span className={`blogger-state-pill ${c.status === "connected" ? "is-connected" : ""}`}>{c.status === "connected" ? "연결됨" : c.status === "pending" ? "인증 미완료" : c.status}</span></div>
              <dl className="blogger-connection-facts">
                <div><dt>권한 범위</dt><dd>읽기 {c.scopes?.some((scope) => scope === "https://www.googleapis.com/auth/blogger.readonly" || scope === "https://www.googleapis.com/auth/blogger") ? "허용" : "없음"} · 쓰기 {c.scopes?.includes("https://www.googleapis.com/auth/blogger") ? "범위 있음" : "없음"}</dd></div>
                <div><dt>레코드 생성</dt><dd>{new Date(c.created_at).toLocaleString("ko-KR")}</dd></div>
                <div><dt>인증 시도 이력</dt><dd>{c.auth_attempt_count}건 · {c.active_auth_attempt ? "진행 중" : c.latest_auth_attempt_at ? `마지막 요청 만료 ${new Date(c.latest_auth_attempt_at).toLocaleString("ko-KR")}` : "기록 없음"}</dd></div>
                <div><dt>갱신·만료</dt><dd>{c.status === "connected" ? `만료 ${c.expires_at ? new Date(c.expires_at).toLocaleString("ko-KR") : "미확인"} · 갱신 정보 ${c.has_refresh_token ? "암호화 저장" : "없음"}` : "연결된 토큰 없음"}</dd></div>
                <div><dt>계정 식별</dt><dd>{c.blogger_user_id ? `Blogger profile ID ${c.blogger_user_id} (Google 계정 이메일과 다름)` : "Google 계정 미확인"}</dd></div>
                <div><dt>블로그 접근 검증</dt><dd>{c.verified_blog_count}개 · {c.access_verified_at ? new Date(c.access_verified_at).toLocaleString("ko-KR") : "검증 기록 없음"}</dd></div>
                <div><dt>매핑된 블로그</dt><dd>{initial.blogs.filter((blog) => blog.oauth_connection_id === c.id).map((blog) => `${blog.display_name} (${blog.language_code})`).join(" · ") || "현재 매핑된 블로그 없음"}</dd></div>
                {c.error_category && <div><dt>최근 오류</dt><dd>{c.error_category}</dd></div>}
              </dl>
            </div>
            <div className="blogger-connection-card-actions">{c.status !== "disconnected" && <button disabled={busy} onClick={() => setDisconnectRequest({ id: c.id, kind: "oauth", label: c.label })}>Google 연결 해제</button>}</div>
          </li>
        ))}
      </ul>
      {!visibleConnections.length && <p>현재 사용 중인 Google OAuth 연결이 없습니다. 이전 인증 기록은 아래 감사 이력에서 확인할 수 있습니다.</p>}
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
      <label>발행 정책 변경 사유 <input value={policyReason} minLength={10} maxLength={2000} onChange={event => setPolicyReason(event.target.value)} /></label>
      <p>발행 정책 ON은 해당 블로그·언어 정책의 사용을 허용합니다. 실제 LIVE 게시에는 OAuth 연결, 원고 품질·출처 검토, 승인 및 발행 제한이 계속 적용됩니다.</p>
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
              {b.language_code} · {b.language_code === "zh-CN" && !b.active ? "운영 중단" : b.active ? "활성" : "비활성"}
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
            <div aria-label={`${b.display_name} 발행 정책`}>
              <strong>발행 정책</strong>
              {(initial.publication_policies ?? []).filter(policy => policy.blog_id === b.id).map(policy =>
                <div key={policy.id}>
                  <span>{policy.target_country || "공통"} · {policy.active ? "ON" : "OFF"} </span>
                  <button type="button" className="secondary-button" disabled={busy || (b.active === false && !policy.active)} onClick={() => void changePolicy(policy)}>
                    {policy.active ? "정책 OFF" : "정책 ON"}
                  </button>
                </div>)}
              {!(initial.publication_policies ?? []).some(policy => policy.blog_id === b.id) && <p>등록된 발행 정책이 없습니다. 언어·정책 설정에서 먼저 등록하세요.</p>}
            </div>
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
                onClick={() => setDisconnectRequest({ id: b.id, kind: "blog", label: `${b.display_name} (${b.language_code})` })}
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
      <section className="blogger-diagnostics" aria-label="진단 및 감사 기록">
        <h2>진단·감사 기록</h2>
        <LazyDiagnosticSection title="최근 API 호출·오류" summary={initial.diagnostics.api_calls} endpoint="diagnostics/api-calls" filter={{ label: "결과", options: [{ value: "succeeded", label: "성공" }, { value: "failed", label: "실패" }, { value: "requested", label: "요청" }] }} />
        <LazyDiagnosticSection title="Blogger 초안 테스트 결과" summary={initial.diagnostics.draft_results} endpoint="diagnostics/draft-results" filter={{ label: "결과", options: [{ value: "succeeded", label: "성공" }, { value: "failed", label: "실패" }, { value: "uncertain", label: "확인 필요" }] }} />
        <LazyDiagnosticSection title="최근 인증·Blogger 감사 이력" summary={initial.diagnostics.audit_events} endpoint="diagnostics/audit-events" filter={{ label: "영역", options: [{ value: "oauth", label: "OAuth" }, { value: "blogger", label: "Blogger" }] }} />
      </section>
      {disconnectRequest && (
        <div className="blogger-confirm-backdrop" role="presentation">
          <section className="blogger-confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="blogger-disconnect-title">
            <h2 id="blogger-disconnect-title">Google 연결 해제 확인</h2>
            <p>대상 연결: <strong>{disconnectRequest.label}</strong></p>
            <p>{disconnectRequest.kind === "oauth" ? `이 인증을 사용하는 블로그: ${initial.blogs.filter((blog) => blog.oauth_connection_id === disconnectRequest.id).map((blog) => blog.display_name).join(" · ") || "현재 연결된 블로그 없음"}` : "해당 Blogger의 현재 OAuth 매핑을 해제합니다."}</p>
            <p>연결 해제 후 이 인증을 사용하는 읽기 작업은 실패할 수 있습니다. 원고, 게시 이력, 자동 발행 설정은 변경되지 않지만 필요한 OAuth 연결이 사라지면 Worker는 정책에 따라 게시를 차단합니다. 실제 연결 해제 전 대상과 영향을 확인하세요.</p>
            <div className="blogger-confirm-actions"><button type="button" className="secondary-button" disabled={busy} onClick={() => setDisconnectRequest(null)}>취소</button><button type="button" disabled={busy} onClick={() => { const path = disconnectRequest.kind === "oauth" ? `oauth/${disconnectRequest.id}/disconnect` : `blogs/${disconnectRequest.id}/disconnect`; setDisconnectRequest(null); void action(path); }}>연결 해제 진행</button></div>
          </section>
        </div>
      )}
    </>
  );
}
