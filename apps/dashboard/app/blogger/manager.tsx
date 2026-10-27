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
  expires_at: string | null;
  error_category: string | null;
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
};
export default function Manager({ initial }: { initial: State }) {
  const router = useRouter();
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [account, setAccount] = useState(
    initial.connections.find((c) => c.status === "connected")?.id ?? "",
  );
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
      <button disabled={busy || !initial.configured} onClick={() => start("write")}>
        Blogger 쓰기 권한 연결 (Google 동의 화면)
      </button>
      <p>
        쓰기 권한 연결은 별도 OAuth 연결을 추가합니다. 연결된 Google 계정의 신원은 확인·추정하지 않습니다.
        게시·수정·삭제와 자동 발행은 계속 차단되며, 쓰기 API 요청은 수행하지 않습니다.
      </p>
      <ul>
        {initial.connections.map((c) => (
          <li key={c.id}>
            {c.label} · {c.status}
            {` · 읽기 ${c.scopes?.some((scope) => scope === "https://www.googleapis.com/auth/blogger.readonly" || scope === "https://www.googleapis.com/auth/blogger") ? "허용" : "없음"}`}
            {` · 쓰기 ${c.scopes?.includes("https://www.googleapis.com/auth/blogger") ? "OAuth 범위 있음" : "없음"}`}
            {` · 만료 ${c.expires_at ?? "미확인"}`}
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
        블로그에 사용할 승인된 연결
        <select value={account} onChange={(e) => setAccount(e.target.value)}>
          <option value="">연결 선택</option>
          {initial.connections
            .filter((c) => c.status === "connected")
            .map((c) => (
              <option key={c.id} value={c.id}>
                {c.label} · {c.id.slice(0, 8)}
              </option>
            ))}
        </select>
      </label>
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
