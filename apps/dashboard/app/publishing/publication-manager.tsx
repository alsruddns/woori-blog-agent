"use client";

import { useState } from "react";

type Candidate = {
  evaluation_id: string | null; content_version_id: string; title: string; language_code: string; target_country: string;
  blog_id: string; url: string; blogger_blog_id: string | null; machine_passed: boolean;
  human_review_required: boolean; publish_ready: boolean; quality_status: string | null;
  editorial_review_approved?: boolean; publication_approval_approved?: boolean;
  effective_mode?: string; auto_eligibility?: { eligible: boolean; reasons: string[]; simulation_only: boolean };
};
type Job = { id: string; evaluation_id: string | null; content_version_id: string; language_code: string; url: string; status: string; publication_state: string; block_reasons: string[]; simulation_count: number };
type ModeSetting = { scope_type: "global" | "language" | "blog"; scope_key: string; configured_mode: "manual" | "auto"; daily_auto_limit: number; minimum_interval_minutes: number; allowed_start_hour: number; allowed_end_hour: number; timezone: string; allowed_categories: string[]; excluded_topics: string[]; max_source_age_hours: number; retry_limit: number; emergency_stopped: boolean; operations_auto_approved: boolean; updated_at?: string };
type SyncPost = { id: string | null; url: string | null; title: string | null; status: string | null; published: string | null; updated: string | null; internal_record: boolean; content_version_id: string | null };
type SyncResult = { language_code: string; blog_uuid: string; posts: SyncPost[]; next_page_token: string; read_only: true; internal_state_changed: false };
export type PublicationData = { candidates: Candidate[]; jobs: Job[]; simulations: unknown[]; worker: { process_id: number; status: string; last_seen_at: string } | null; queued_mock_jobs: number; real_writes_enabled: false; publish_ready_enabled: false; adapter_available: string; mode_policy: { migration_required: boolean; default_mode: string; settings: ModeSetting[]; languages: { code: string; display_name: string; active: boolean }[]; blogs: { id: string; language_code: string; url: string; display_name: string; active: boolean }[]; emergency_stopped: boolean; operations_auto_approved: false; live_auto_enabled: false; real_writes_enabled: false }; auto_candidate_count: number; auto_runtime_status: string };

export default function PublicationManager({ initial }: { initial: PublicationData }) {
  const globalMode = initial.mode_policy.settings.find(item => item.scope_type === "global" && item.scope_key === "");
  const [data, setData] = useState(initial);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState("");
  const [syncResult, setSyncResult] = useState<SyncResult | null>(null);
  const [scopeType, setScopeType] = useState<"global" | "language" | "blog">("global");
  const [scopeKey, setScopeKey] = useState("");
  const [selectedMode, setSelectedMode] = useState<"manual" | "auto">(globalMode?.configured_mode ?? "manual");
  const [categories, setCategories] = useState(globalMode?.allowed_categories.join(", ") ?? "");
  const [dailyLimit, setDailyLimit] = useState(globalMode?.daily_auto_limit ?? 1);
  const [minimumInterval, setMinimumInterval] = useState(globalMode?.minimum_interval_minutes ?? 1440);
  const [maxAge, setMaxAge] = useState(globalMode?.max_source_age_hours ?? 24);
  const [retryLimit, setRetryLimit] = useState(globalMode?.retry_limit ?? 0);
  const [startHour, setStartHour] = useState(globalMode?.allowed_start_hour ?? 9);
  const [endHour, setEndHour] = useState(globalMode?.allowed_end_hour ?? 17);
  const [excludedTopics, setExcludedTopics] = useState(globalMode?.excluded_topics.join(", ") ?? "");
  function chooseScope(type: "global" | "language" | "blog", key = "") {
    setScopeType(type); setScopeKey(key);
    const saved = data.mode_policy.settings.find(item => item.scope_type === type && item.scope_key === key);
    setSelectedMode(saved?.configured_mode ?? "manual");
    setCategories(saved?.allowed_categories.join(", ") ?? "");
    setDailyLimit(saved?.daily_auto_limit ?? 1);
    setMinimumInterval(saved?.minimum_interval_minutes ?? 1440);
    setMaxAge(saved?.max_source_age_hours ?? 24);
    setRetryLimit(saved?.retry_limit ?? 0);
    setStartHour(saved?.allowed_start_hour ?? 9);
    setEndHour(saved?.allowed_end_hour ?? 17);
    setExcludedTopics(saved?.excluded_topics.join(", ") ?? "");
  }
  async function saveMode() {
    if (selectedMode === "auto" && !window.confirm("Auto 모드를 요청합니다. 현재 운영 승인과 실제 Blogger 쓰기 잠금은 유지되어 자동 게시가 실행되지 않습니다. 이 설정을 저장할까요?")) return;
    setBusy("mode-settings"); setMessage("");
    try {
      const response = await fetch("/api/publications/mode-settings", { method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scope_type: scopeType, scope_key: scopeKey, configured_mode: selectedMode,
          daily_auto_limit: dailyLimit, minimum_interval_minutes: minimumInterval,
          allowed_start_hour: startHour, allowed_end_hour: endHour, timezone: "Asia/Seoul",
          allowed_categories: categories.split(",").map(value => value.trim()).filter(Boolean),
          excluded_topics: excludedTopics.split(",").map(value => value.trim()).filter(Boolean), max_source_age_hours: maxAge, retry_limit: retryLimit }) });
      const result = await response.json();
      setMessage(response.ok ? `설정을 저장했습니다. 실제 Auto 실행은 운영 승인과 발행 안전 게이트가 열리기 전까지 차단됩니다.` : String(result.detail ?? result.error ?? "설정 저장 실패"));
      const refreshed = await fetch("/api/publications", { cache: "no-store" });
      if (refreshed.ok) setData(await refreshed.json());
    } catch { setMessage("로컬 API에 연결할 수 없습니다."); }
    finally { setBusy(""); }
  }
  async function stopAuto() {
    setBusy("emergency-stop"); setMessage("");
    try {
      const response = await fetch("/api/publications/emergency-stop", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled: true }) });
      const result = await response.json();
      setMessage(response.ok ? "긴급 중지를 기록했습니다. 이 화면에서는 중지를 해제할 수 없습니다." : String(result.detail ?? result.error ?? "긴급 중지 실패"));
      const refreshed = await fetch("/api/publications", { cache: "no-store" });
      if (refreshed.ok) setData(await refreshed.json());
    } catch { setMessage("로컬 API에 연결할 수 없습니다."); }
    finally { setBusy(""); }
  }
  async function request(candidate: Candidate) {
    const key = crypto.randomUUID().replaceAll("-", "");
    setBusy(candidate.content_version_id); setMessage("");
    try {
      const response = await fetch("/api/publications/requests", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content_version_id: candidate.content_version_id, blog_id: candidate.blog_id, idempotency_key: key }) });
      const result = await response.json();
      setMessage(response.ok ? `Request result: ${result.publication_state ?? result.state}; live publishing remains disabled.` : JSON.stringify(result.detail ?? result));
      const refreshed = await fetch("/api/publications", { cache: "no-store" });
      if (refreshed.ok) setData(await refreshed.json());
    } catch { setMessage("Local API unavailable."); }
    finally { setBusy(""); }
  }
  async function simulate(job: Job) {
    const key = crypto.randomUUID().replaceAll("-", "");
    setBusy(job.id); setMessage("");
    try {
      const response = await fetch(`/api/publications/jobs/${job.id}/simulate`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ idempotency_key: key, scenario: "success" }) });
      const result = await response.json();
      setMessage(response.ok ? `Fake adapter result: ${result.outcome}; fake id ${result.fake_post_id}. No real post was created.` : JSON.stringify(result.detail ?? result));
      const refreshed = await fetch("/api/publications", { cache: "no-store" });
      if (refreshed.ok) setData(await refreshed.json());
    } catch { setMessage("Local API unavailable."); }
    finally { setBusy(""); }
  }
  async function schedule(job: Job) {
    const input = document.getElementById(`schedule-${job.id}`) as HTMLInputElement | null;
    if (!input?.value) { setMessage("Choose a future time in Korea Standard Time."); return; }
    setBusy(job.id); setMessage("");
    try {
      const response = await fetch(`/api/publications/jobs/${job.id}/schedule`, { method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ idempotency_key: crypto.randomUUID().replaceAll("-", ""), scheduled_at: `${input.value}:00+09:00`, timezone: "Asia/Seoul", mock_scenario: "success" }) });
      const result = await response.json();
      setMessage(response.ok ? `Offline simulation queued for ${result.scheduled_at}. Domain state remains ${result.publication_state}; this is not a live publication.` : JSON.stringify(result.detail ?? result));
      const refreshed = await fetch("/api/publications", { cache: "no-store" });
      if (refreshed.ok) setData(await refreshed.json());
    } catch { setMessage("Local API unavailable."); }
    finally { setBusy(""); }
  }
  async function cancelSchedule(job: Job) {
    setBusy(job.id); setMessage("");
    try {
      const response = await fetch(`/api/publications/jobs/${job.id}/schedule`, { method: "DELETE", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ idempotency_key: crypto.randomUUID().replaceAll("-", "") }) });
      const result = await response.json();
      setMessage(response.ok ? `Offline schedule cancelled; state ${result.publication_state}.` : JSON.stringify(result.detail ?? result));
      const refreshed = await fetch("/api/publications", { cache: "no-store" });
      if (refreshed.ok) setData(await refreshed.json());
    } catch { setMessage("Local API unavailable."); }
    finally { setBusy(""); }
  }
  async function syncReadOnly(candidate: Candidate, pageToken = "") {
    setBusy(candidate.blog_id); setMessage("");
    try {
      const query = pageToken ? `?page_token=${encodeURIComponent(pageToken)}` : "";
      const response = await fetch(`/api/publications/blogs/${candidate.blog_id}/sync-readonly${query}`, { method: "POST" });
      const result = await response.json();
      if (response.ok) {
        setSyncResult(result as SyncResult);
        setMessage(`Read-only sync: ${result.posts.length} posts checked for ${result.language_code}; next page ${result.next_page_token ? "available" : "none"}. Discrepancies require manual review.`);
      } else setMessage(JSON.stringify(result.detail ?? result));
    } catch { setMessage("Local API unavailable."); }
    finally { setBusy(""); }
  }
  return <>
    {message && <p role="status">{message}</p>}
    <section aria-labelledby="publication-mode-heading">
      <h2 id="publication-mode-heading">게시 모드</h2>
      {data.mode_policy.migration_required ? <p role="status">게시 모드 설정을 사용하려면 Migration 042가 필요합니다. 기본 게시 모드는 Manual이며 현재 설정은 읽기 전용입니다.</p> : <>
        <p>기본값은 Manual입니다. Auto를 선택해도 현재 별도 운영 승인이 없고 실제 Blogger 쓰기가 잠겨 있어 실행되지 않습니다.</p>
        <p>현재 Auto 상태: {data.mode_policy.emergency_stopped ? "긴급 중지됨" : data.auto_runtime_status}; 운영 승인: 없음; 실제 Blogger 쓰기: 차단</p>
        <div className="mode-settings-form">
          <label>적용 범위 <select value={scopeType} onChange={event => chooseScope(event.target.value as "global" | "language" | "blog", "")}>
            <option value="global">전체 기본값</option><option value="language">언어별</option><option value="blog">블로그별</option>
          </select></label>
          {scopeType === "language" && <label>언어 <select value={scopeKey} onChange={event => chooseScope("language", event.target.value)}>
            <option value="">선택</option>{data.mode_policy.languages.map(language => <option key={language.code} value={language.code}>{language.display_name} ({language.code})</option>)}
          </select></label>}
          {scopeType === "blog" && <label>블로그 <select value={scopeKey} onChange={event => chooseScope("blog", event.target.value)}>
            <option value="">선택</option>{data.mode_policy.blogs.map(blog => <option key={blog.id} value={blog.id}>{blog.display_name} · {blog.url}</option>)}
          </select></label>}
          <label>게시 모드 <select value={selectedMode} onChange={event => setSelectedMode(event.target.value as "manual" | "auto")}>
            <option value="manual">Manual</option><option value="auto">Auto 요청 (현재 실행 차단)</option>
          </select></label>
          {selectedMode === "auto" && <>
            <label>허용 카테고리 (쉼표 구분) <input value={categories} onChange={event => setCategories(event.target.value)} placeholder="예: finance" /></label>
            <label>하루 최대 게시 후보 <input type="number" min={0} max={3} value={dailyLimit} onChange={event => setDailyLimit(Number(event.target.value))} /></label>
            <label>최소 게시 간격 (분) <input type="number" min={60} max={10080} value={minimumInterval} onChange={event => setMinimumInterval(Number(event.target.value))} /></label>
            <label>자료 최신성 제한 (시간) <input type="number" min={1} max={720} value={maxAge} onChange={event => setMaxAge(Number(event.target.value))} /></label>
            <label>최대 재시도 <input type="number" min={0} max={2} value={retryLimit} onChange={event => setRetryLimit(Number(event.target.value))} /></label>
            <label>게시 시작 시간 (KST) <input type="number" min={0} max={23} value={startHour} onChange={event => setStartHour(Number(event.target.value))} /></label>
            <label>게시 종료 시간 (KST) <input type="number" min={0} max={23} value={endHour} onChange={event => setEndHour(Number(event.target.value))} /></label>
            <label>제외 주제 (쉼표 구분) <input value={excludedTopics} onChange={event => setExcludedTopics(event.target.value)} /></label>
          </>}
          <button disabled={!!busy || (scopeType !== "global" && !scopeKey)} onClick={() => void saveMode()}>{busy === "mode-settings" ? "저장 중…" : "설정 저장"}</button>
          <button disabled={!!busy || data.mode_policy.emergency_stopped} onClick={() => void stopAuto()}>{busy === "emergency-stop" ? "중지 중…" : "긴급 자동 게시 중지"}</button>
        </div>
        <p>자동 실행 승인은 이 설정과 별도로 관리됩니다. 설정 변경은 감사 이력에 추가됩니다. 예약 작업은 현재 Fake 어댑터 테스트로만 동작합니다.</p>
      </>}
    </section>
    <aside>Mock Worker: {data.worker?.status ?? "not started"}; queued mock jobs: {data.queued_mock_jobs}. Starting the evaluation worker is a separate local command.</aside>
    {syncResult && <section><h2>Read-only Blogger page result ({syncResult.language_code})</h2><p>Internal publication state was not changed. Mock IDs are not included.</p>
      <table><thead><tr><th>Remote post ID</th><th>Title</th><th>Status</th><th>Internal match</th></tr></thead><tbody>
        {syncResult.posts.map((post) => <tr key={post.id}><td>{post.id}</td><td>{post.title}</td><td>{post.status}</td><td>{post.internal_record ? post.content_version_id : "No internal record"}</td></tr>)}
      </tbody></table>
      {syncResult.next_page_token && <button disabled={!!busy} onClick={() => {
        const candidate = data.candidates.find((item) => item.blog_id === syncResult.blog_uuid);
        if (candidate) void syncReadOnly(candidate, syncResult.next_page_token);
      }}>Read next page</button>}
    </section>}
    <section><h2>Draft candidates</h2><p>Requests are recorded as blocked when any eligibility condition is unmet. A machine pass does not constitute human approval.</p>
      <table><thead><tr><th>Version</th><th>Language</th><th>Blog / mode</th><th>Machine review</th><th>Action</th></tr></thead><tbody>
        {data.candidates.map((candidate) => <tr key={`${candidate.content_version_id}-${candidate.blog_id}`}>
          <td>{candidate.title}<small>{candidate.content_version_id}</small></td><td>{candidate.language_code}</td><td>{candidate.url}<small>{candidate.effective_mode ?? "Manual"}</small></td>
          <td>{candidate.quality_status ?? "검사 전"}; 편집 검토 {candidate.editorial_review_approved ? "완료" : "대기"}; 게시 승인 {candidate.publication_approval_approved ? "완료" : "대기"}; 발행 준비={candidate.publish_ready ? "예" : "아니요"}<small>{candidate.auto_eligibility?.reasons.join(", ")}</small></td>
          <td>{candidate.evaluation_id ? <a href={`/manuscripts?open_evaluation_id=${encodeURIComponent(candidate.evaluation_id)}&open_content_version_id=${encodeURIComponent(candidate.content_version_id)}`}>다른 언어로 발행</a> : <span>평가 연결 없음</span>}{" "}
            <button disabled={!!busy || candidate.effective_mode?.startsWith("auto")} onClick={() => void request(candidate)}>{busy === candidate.content_version_id ? "Recording…" : "Manual 요청 기록"}</button>{" "}
            <button disabled={!!busy} onClick={() => void syncReadOnly(candidate)}>Read-only Blogger sync</button></td>
        </tr>)}
      </tbody></table>
    </section>
    <section><h2>Publication request ledger</h2><table><thead><tr><th>Request</th><th>Language / blog</th><th>State</th><th>Block reasons</th><th>Offline test</th></tr></thead><tbody>
      {data.jobs.map((job) => <tr key={job.id}><td>{job.id}<small>{job.status} / simulation-only</small></td><td>{job.language_code} · {job.url}</td>
        <td>{job.publication_state}</td><td>{job.block_reasons.join(", ")}</td>
        <td><button disabled={!!busy} onClick={() => void simulate(job)}>{busy === job.id ? "Running…" : "Run offline Fake adapter"}</button>{" "}
          <label>Mock schedule (KST) <input id={`schedule-${job.id}`} type="datetime-local" /></label>{" "}
          <button disabled={!!busy} onClick={() => void schedule(job)}>Queue mock</button>{" "}
          {job.status === "queued" && <button disabled={!!busy} onClick={() => void cancelSchedule(job)}>Cancel mock</button>}{job.evaluation_id && <a href={`/manuscripts?open_evaluation_id=${encodeURIComponent(job.evaluation_id)}&open_content_version_id=${encodeURIComponent(job.content_version_id)}`}>다른 언어로 발행</a>}</td></tr>)}
    </tbody></table></section>
  </>;
}
