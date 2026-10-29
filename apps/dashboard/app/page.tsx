import Link from "next/link";
import { API_BASE } from "../lib/server";

export const dynamic = "force-dynamic";

type Blog = {
  id: string;
  language_code: string;
  language_name: string;
  display_name: string;
  url: string;
  active: boolean;
  blog_id_registered: boolean;
  oauth_status: string;
  read_scope: boolean;
  write_scope: boolean;
  last_access_verification_at: string | null;
  has_connection_error: boolean;
  configured_mode: "manual" | "auto";
  daily_limit: number;
  hourly_limit: number | null;
  minimum_interval_minutes: number;
  live_auto_enabled: false;
  live_writes_enabled: false;
  last_mock_success_at: string | null;
  last_mock_failure_at: string | null;
  last_mock_failure_reason: string | null;
  recent_public_url: null;
  public_url_note: string;
};
type Dashboard = {
  schema_version: number;
  trends: {
    configured: boolean;
    periodic_worker: string;
    last_collected_at: string | null;
    successful_runs: number;
    failed_runs: number;
    observations_last_24h: number;
    regions: { geo: string; observations: number; last_collected_at: string }[];
  };
  trend_pipeline: {
    search_terms_24h: number;
    unique_issue_groups_24h: number;
    article_candidates: number;
    held_issue_groups_24h: number;
    research_packages_24h: number;
    ai_articles_written_24h: number;
    actual_posts_24h: number;
    article_lineage_available: boolean;
    generation_block_reason: string;
    publication_block_reason: string;
    hold_reasons: { reason: string; count: number }[];
  };
  scheduled_import: { available: boolean; scheduled_claims: number; verified_gpt_runs: number; received_total: number; received_last_24h: number; last_received_at: string | null; languages: Record<string, number>; machine_passed: number; quality_held: number; source_review_held: number; duplicate_file_outcomes: number; outcomes: Record<string, number>; worker_poll_seconds: number; worker_status: string; recent: { import_id: string; language_code: string; title: string; state: string; received_at: string; research_package_id: string | null; content_version_id: string | null; inbox_file_name: string | null; inbox_file_sha256: string | null; audit_event_id: number | null; machine_passed: boolean | null; independent_source_verification: boolean | null }[] };
  jobs: Record<string, number>;
  generation: { provider_connected: boolean; provider_status: string; counts: Record<string, number>; queue_waiting: number; reason: string };
  quality: { machine_passed: number; held: number; failed: number; human_review_required: number };
  publishing: { jobs: Record<string, number>; recorded_posts: number; last_recorded_at: string | null; recent_public_url: string | null; url_note: string; queued_mock_jobs: number; live_writes_enabled: false; auto_enabled: false; emergency_stopped: boolean; configured_global_mode: "manual" | "auto"; daily: { date_kst: string; timezone: string; global_limit: number; published: number; reserved: number; remaining: number; remote_posts_synchronized: boolean; remote_sync_note: string; auto_enabled: boolean; languages: Record<string, { published: number; reserved: number; limit: number; remaining: number; hourly_limit: number }>; items: { published_at: string; language_code: string; blog_name: string; blog_url: string; remote_post_id: string; content_version_id: string; job_id: string; title: string; origin: string; job_status: string }[] } };
  blogs: Blog[];
  schedules: { key: string; name: string; status: string; detail: string }[];
  publication_policy: { configured_global_mode: string; live_auto_enabled: false; live_writes_enabled: false; hourly_limit: number | null; hourly_limit_status: string; daily_limit: number; emergency_stopped: boolean };
  recent_public_url: string | null;
  search_console_connected: boolean;
  search_performance: string;
  limitations: string[];
};

type LoadState = { dashboard: Dashboard | null; error: "api" | "auth" | "database" | "unknown" | null };

async function loadDashboard(): Promise<LoadState> {
  if (!process.env.ADMIN_TOKEN) return { dashboard: null, error: "auth" };
  const dashboardApiBase = process.env.WOORI_TEST_MODE === "1"
    ? "http://127.0.0.1:8100"
    : API_BASE;
  try {
    const response = await fetch(`${dashboardApiBase}/admin/operations/dashboard`, {
      headers: { Authorization: `Bearer ${process.env.ADMIN_TOKEN}` },
      cache: "no-store",
      signal: AbortSignal.timeout(4000),
    });
    if (response.status === 401) return { dashboard: null, error: "auth" };
    if (response.status === 503) return { dashboard: null, error: "database" };
    if (!response.ok) return { dashboard: null, error: "unknown" };
    return { dashboard: (await response.json()) as Dashboard, error: null };
  } catch {
    return { dashboard: null, error: "api" };
  }
}

const dates = new Intl.DateTimeFormat("ko-KR", {
  timeZone: "Asia/Seoul",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});
const dateLabel = (value: string | null) => (value ? `${dates.format(new Date(value))} KST` : "기록 없음");
const statusLabels: Record<string, string> = {
  inactive: "비활성",
  not_configured: "미설정",
  external_status_unknown: "외부 상태 확인 불가",
  pending: "연결 대기",
  connected: "OAuth 연결 기록 있음",
  error: "연결 오류",
  revoked: "권한 취소됨",
  disconnected: "연결 해제됨",
};

function Status({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "neutral" | "good" | "blocked" }) {
  return <span className={`ops-status ops-status-${tone}`}>{children}</span>;
}

function ApiIssue({ kind }: { kind: NonNullable<LoadState["error"]> }) {
  const messages: Record<typeof kind, string> = {
    api: "로컬 API 서버에 연결할 수 없습니다. FastAPI 상태와 주소를 확인하세요.",
    auth: "관리자 인증이 설정되지 않았거나 인증되지 않았습니다. 로컬 인증 설정을 확인하세요.",
    database: "API는 응답했지만 DB 현황을 읽지 못했습니다. 서버 로그에서 안전하게 원인을 확인하세요.",
    unknown: "운영 현황을 불러오지 못했습니다. 잠시 후 다시 확인하거나 운영 진단을 여세요.",
  };
  return <section className="workspace-panel ops-error" role="alert"><h2>운영 현황을 확인할 수 없습니다</h2><p>{messages[kind]}</p><Link href="/operations">운영 진단 열기</Link></section>;
}

export default async function Page() {
  const { dashboard, error } = await loadDashboard();
  return (
    <main className="workspace-main ops-home">
      <div className="page-heading">
        <div><p className="eyebrow">WOORI CONTENT STUDIO</p><h1>콘텐츠 운영 현황</h1><p>수집, 원고 검토, 게시 준비와 자동화 상태를 확인합니다.</p></div>
        <Status tone="blocked">실제 자동 게시 꺼짐</Status>
      </div>
      {error ? <ApiIssue kind={error} /> : dashboard ? <>
        <section className="ops-stat-grid" aria-label="콘텐츠 파이프라인 현황">
          <article className="ops-stat-card"><p className="eyebrow">트렌드 수집</p><strong>{dashboard.trends.observations_last_24h.toLocaleString("ko-KR")}</strong><p>최근 24시간 관측 · 마지막 성공 {dateLabel(dashboard.trends.last_collected_at)}</p><Status tone={dashboard.trends.periodic_worker === "inactive" ? "blocked" : "neutral"}>{dashboard.trends.periodic_worker === "inactive" ? "주기 실행 비활성" : "상태 확인 필요"}</Status></article>
          <article className="ops-stat-card"><p className="eyebrow">원고 생성</p><strong>{dashboard.generation.queue_waiting.toLocaleString("ko-KR")}</strong><p>대기 작업 · 생성 Provider 연결 안 됨</p><Status tone="blocked">자동 생성 차단</Status></article>
          <article className="ops-stat-card"><p className="eyebrow">품질 검토</p><strong>{dashboard.quality.human_review_required.toLocaleString("ko-KR")}</strong><p>기계 검사 후 사람 검토 대기</p><p className="ops-inline-counts">보류 {dashboard.quality.held} · 실패 {dashboard.quality.failed}</p></article>
          <article className="ops-stat-card"><p className="eyebrow">게시 대기</p><strong>{dashboard.publishing.queued_mock_jobs.toLocaleString("ko-KR")}</strong><p>모의 작업 대기 · 실제 Blogger 기록 {dashboard.publishing.recorded_posts}</p><Status tone="blocked">실제 쓰기 잠금</Status></article>
        </section>

        <section className="workspace-panel">
          <div className="section-heading"><div><p className="eyebrow">Google Trends → 원고 → Blogger</p><h2>주제 선별 및 게시 단계별 실적</h2></div><Link href="/sources">수집 주제와 근거 보기</Link></div>
          <div className="ops-inline-counts"><span>검색어 관측 {dashboard.trend_pipeline.search_terms_24h}</span> · <span>고유 이슈 그룹 {dashboard.trend_pipeline.unique_issue_groups_24h}</span> · <span>기사 후보 {dashboard.trend_pipeline.article_candidates}</span> · <span>보류 이슈 {dashboard.trend_pipeline.held_issue_groups_24h}</span> · <span>Research Package {dashboard.trend_pipeline.research_packages_24h}</span> · <span>AI 원고 {dashboard.trend_pipeline.ai_articles_written_24h}</span> · <span>실제 게시 {dashboard.trend_pipeline.actual_posts_24h}</span></div>
          <p>Google Trends RSS 순위는 제공되지 않으면 NULL로 유지되며 검색량 순위로 해석하지 않습니다. 동일 검색어 그룹은 동일 사건으로 확정되지 않습니다. Trends 연계 원고 이력: {dashboard.trend_pipeline.article_lineage_available ? "연결됨" : "미연결"}. 현재 생성 차단: {dashboard.trend_pipeline.generation_block_reason}; 게시 차단: {dashboard.trend_pipeline.publication_block_reason}.</p>
          {dashboard.trend_pipeline.hold_reasons.length ? <ul>{dashboard.trend_pipeline.hold_reasons.map(item => <li key={item.reason}>{item.reason}: {item.count}</li>)}</ul> : <p>최근 24시간 후보 보류 사유 집계 없음</p>}
        </section>

        <section className="workspace-panel" aria-labelledby="daily-publishing-title">
          <div className="section-heading"><div><p className="eyebrow">KST 일일 발행 현황</p><h2 id="daily-publishing-title">{dashboard.publishing.daily.date_kst} · 실제 기록 {dashboard.publishing.daily.published}/{dashboard.publishing.daily.global_limit}</h2></div><Link href="/publishing">발행 작업 보기</Link></div>
          <p>남은 전역 여유 {dashboard.publishing.daily.remaining}건 · 대기 점유 {dashboard.publishing.daily.reserved}건 · Auto {dashboard.publishing.daily.auto_enabled ? "ON" : "OFF"}. 원격 Blogger 수동 게시 동기화: {dashboard.publishing.daily.remote_posts_synchronized ? "확인됨" : "미확인"} — {dashboard.publishing.daily.remote_sync_note}</p>
          <div className="ops-inline-counts">{["en", "ko", "ja", "zh-CN"].map((language) => { const item = dashboard.publishing.daily.languages[language]; return <span key={language}>{language}: {item?.published ?? 0}/{item?.limit ?? 0} (잔여 {item?.remaining ?? 0}, 시간당 상한 {item?.hourly_limit ?? 0})</span>; })}</div>
          {dashboard.publishing.daily.items.length ? <div className="ops-published-table-wrap"><table><thead><tr><th>게시 시각 (KST)</th><th>언어 / 블로그</th><th>원고</th><th>유형 / 상태</th><th>Blogger postId</th><th>원고 상세</th></tr></thead><tbody>{dashboard.publishing.daily.items.map((item) => <tr key={`${item.remote_post_id}:${item.blog_url}`}><td>{dateLabel(item.published_at)}</td><td>{item.language_code}<br /><a href={item.blog_url} target="_blank" rel="noreferrer">{item.blog_name}</a></td><td>{item.title}</td><td>{item.origin === "simulation" ? "모의" : "에이전트"}<br />{item.job_status}</td><td>{item.remote_post_id}</td><td><Link href={`/manuscripts?open_content_version_id=${encodeURIComponent(item.content_version_id)}`}>원고 보기</Link></td></tr>)}</tbody></table></div> : <p className="empty-state">오늘 KST 기준 저장된 실제 게시 기록이 없습니다. 실제 공개와 모의 실행은 별도로 집계됩니다.</p>}
          <p className="ops-note">50건은 Google 보장 한도가 아닌 내부 운영 상한입니다. 게시 기록은 내부 게시 원장 기준이며 원격 수동 게시 내역은 확인되지 않았으므로 남은 수량은 잠정치입니다.</p>
        </section>

        <section className="workspace-panel">
          <div className="section-heading"><div><p className="eyebrow">운영 자동화</p><h2>예약 작업 상태</h2></div><Link href="/operations/research#automation">자동화 상세 보기 →</Link></div>
          <div className="ops-schedule-grid">
            {dashboard.schedules.map((task) => <article key={task.key} className="ops-schedule-card"><div><h3>{task.name}</h3><Status tone={task.status === "inactive" || task.status === "not_configured" ? "blocked" : "neutral"}>{statusLabels[task.status] ?? "상태 확인 필요"}</Status></div><p>{task.detail}</p></article>)}
          </div>
          <p className="ops-note">설정된 일정은 Worker가 실제로 실행 중이라는 증거가 아닙니다. 이 PC가 꺼져 있거나 Worker가 중지되면 로컬 예약 작업도 실행되지 않습니다.</p>
        </section>

        <section className="workspace-panel" aria-labelledby="scheduled-import-title">
          <div className="section-heading"><div><p className="eyebrow">로컬 파일 수신</p><h2 id="scheduled-import-title">예약 원고 Import</h2></div><Link href="/imports">가져온 원고 검토</Link></div>
          <p>수신 {dashboard.scheduled_import.received_total}건 · 최근 24시간 {dashboard.scheduled_import.received_last_24h}건 · 마지막 수신 {dateLabel(dashboard.scheduled_import.last_received_at)} · Import 감시 Worker {dashboard.scheduled_import.worker_status} (주기 {dashboard.scheduled_import.worker_poll_seconds}초)</p>
          <p>언어별 수신: {Object.entries(dashboard.scheduled_import.languages).map(([language, count]) => `${language} ${count}`).join(" · ") || "기록 없음"}. 기계 통과 {dashboard.scheduled_import.machine_passed} · 품질 보류 {dashboard.scheduled_import.quality_held} · 독립 출처 검토 대기 {dashboard.scheduled_import.source_review_held} · 중복 차단 {dashboard.scheduled_import.duplicate_file_outcomes}.</p>
          <div className="ops-inline-counts">{Object.entries(dashboard.scheduled_import.outcomes).map(([status, count]) => <span key={status}>{status}: {count}</span>)}</div>
          <p className="ops-note">예약 작업에서 주장한 수신 {dashboard.scheduled_import.scheduled_claims}건 · 확인된 GPT 예약 실행 {dashboard.scheduled_import.verified_gpt_runs}건. 파일의 task/실행 식별은 자기 보고이므로 예약 실행 자체를 증명하지 않습니다. 원고는 모두 사람 검토 대기이며 자동 게시되지 않습니다.</p>
          {dashboard.scheduled_import.recent.length ? <div className="ops-published-table-wrap"><table><thead><tr><th>수신 시각 (KST)</th><th>언어</th><th>원고</th><th>검토 상태</th><th>Research Package</th><th>원본 파일 / 해시</th><th>감사</th></tr></thead><tbody>{dashboard.scheduled_import.recent.map((item) => <tr key={item.import_id}><td>{dateLabel(item.received_at)}</td><td>{item.language_code}</td><td><Link href={`/imports?open_import_id=${encodeURIComponent(item.import_id)}`}>{item.title}</Link></td><td>{item.state}<br />품질 {item.machine_passed === null ? "미검사" : item.machine_passed ? "기계 통과" : "보류"}<br />독립 출처 {item.independent_source_verification ? "확인" : "미확인"}</td><td>{item.research_package_id ?? "연결 없음"}</td><td>{item.inbox_file_name ?? "수동/외부 수신"}{item.inbox_file_sha256 ? <><br /><small>SHA-256 {item.inbox_file_sha256}</small></> : null}</td><td>{item.audit_event_id ?? "origin 기록 없음"}<br /><small>버전 {item.content_version_id ?? "연결 없음"}</small></td></tr>)}</tbody></table></div> : <p className="empty-state">예약 형식으로 Import된 원고가 없습니다.</p>}
          <p className="ops-note">원본 JSON은 로컬 `.local/gpt-scheduled-import/processed/`에 보관합니다. Dashboard에는 원문 JSON이나 기사 본문을 노출하지 않습니다.</p>
        </section>

        <section className="workspace-panel">
          <div className="section-heading"><div><p className="eyebrow">언어별 Blogger</p><h2>블로그 운영 상태</h2></div><Link href="/publishing">발행 관리 →</Link></div>
          {dashboard.blogs.length ? <div className="ops-blog-grid">{dashboard.blogs.map((blog) => <article key={blog.id} className="ops-blog-card">
            <div className="ops-blog-title"><div><p className="eyebrow">{blog.language_name} · {blog.language_code}</p><h3>{blog.display_name}</h3></div><Status tone={blog.active ? "good" : "neutral"}>{blog.active ? "등록됨" : "비활성"}</Status></div>
            <a href={blog.url} target="_blank" rel="noreferrer">{blog.url}</a>
            <dl className="ops-blog-facts">
              <div><dt>OAuth</dt><dd>{statusLabels[blog.oauth_status] ?? "상태 확인 필요"}</dd></div>
              <div><dt>권한</dt><dd>읽기 {blog.read_scope ? "확인된 scope" : "미확인"} · 쓰기 {blog.write_scope ? "scope 기록 있음" : "미확인"}</dd></div>
              <div><dt>최근 권한 확인</dt><dd>{dateLabel(blog.last_access_verification_at)}</dd></div>
              <div><dt>게시 모드</dt><dd>{blog.configured_mode === "auto" ? "자동 설정 요청" : "수동"} · 실제 게시 차단</dd></div>
              <div><dt>제한</dt><dd>시간당 {blog.hourly_limit ?? "미설정"} · 일일 {blog.daily_limit} · 최소 간격 {blog.minimum_interval_minutes}분</dd></div>
              <div><dt>최근 모의 성공</dt><dd>{dateLabel(blog.last_mock_success_at)}</dd></div>
              <div><dt>최근 모의 실패</dt><dd>{blog.last_mock_failure_at ? `${dateLabel(blog.last_mock_failure_at)} · ${blog.last_mock_failure_reason ?? "사유 미기록"}` : "기록 없음"}</dd></div>
            </dl>
            <p className="ops-note">{blog.public_url_note}</p>
          </article>)}</div> : <p className="empty-state">등록된 Blogger 블로그가 없습니다.</p>}
        </section>

        <section className="ops-bottom-grid">
          <article className="workspace-panel"><p className="eyebrow">게시 안전</p><h2>Auto 상태: 비활성</h2><p>설정 화면의 Auto 값만으로는 게시되지 않습니다. 운영 승인, 실제 쓰기 Publisher, 검증·복구 게이트가 연결되어야 합니다.</p><p>전체 긴급 중지: {dashboard.publishing.emergency_stopped ? "작동 중" : "해제 상태"} · 실제 쓰기 잠금은 계속 적용됩니다.</p><Link href="/publishing">게시 설정과 중지 기능 보기 →</Link></article>
          <article className="workspace-panel"><p className="eyebrow">검색·게시 결과</p><h2>실측 데이터만 표시</h2><p>최근 공개 URL: {dashboard.recent_public_url ? <a href={dashboard.recent_public_url} target="_blank" rel="noreferrer">게시물 열기</a> : "저장된 공개 URL 없음"}</p><p>{dashboard.search_performance}</p><Link href="/operations">운영 진단 보기 →</Link></article>
        </section>
      </> : null}
    </main>
  );
}
