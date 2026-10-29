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
export type PublicationData = { candidates: Candidate[]; jobs: Job[]; simulations: unknown[]; worker: { process_id: number; status: string; last_seen_at: string } | null; queued_mock_jobs: number; queued_confirmed_private_drafts?: number; real_writes_enabled: false; publish_ready_enabled: false; adapter_available: string; mode_policy: { migration_required: boolean; default_mode: string; settings: ModeSetting[]; languages: { code: string; display_name: string; active: boolean }[]; blogs: { id: string; language_code: string; url: string; display_name: string; active: boolean }[]; emergency_stopped: boolean; operations_auto_approved: false; live_auto_enabled: false; real_writes_enabled: false }; auto_candidate_count: number; auto_runtime_status: string };

const stateNames: Record<string, string> = {
  queued: "대기 중", blocked: "차단됨", failed: "실패", published: "게시 완료", succeeded: "모의 성공",
  cancelled: "취소됨", pending: "승인 대기", quality_held: "품질 검토 필요", insufficient_evidence: "근거 자료 부족",
  publish_ready: "게시 준비 완료", awaiting_human_review: "사람 검토 대기", review_started: "검토 중",
};
const languageNames: Record<string, string> = { ko: "한국어", en: "영어", ja: "일본어", "zh-CN": "중국어 간체" };
const languageLabel = (code: string) => languageNames[code] ?? "언어 확인 필요";
const categoryNames: Record<string, string> = { economy: "경제", finance: "금융", stocks: "주식", crypto: "암호화폐", technology: "IT", semiconductors: "반도체", ai: "인공지능", policy: "정치·정책" };
const runtimeNames: Record<string, string> = { disabled: "비활성", stopped: "중지됨", blocked: "실행 차단", ready: "대기 중", unavailable: "사용할 수 없음" };
const runtimeLabel = (status: string) => runtimeNames[status] ?? "상태 확인 필요";

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
  const [activeTab, setActiveTab] = useState<"pending" | "history" | "settings">("pending");
  const pendingCount = data.candidates.filter(candidate => !candidate.editorial_review_approved || !candidate.publication_approval_approved).length;
  const publishedCount = data.jobs.filter(job => job.publication_state === "published" || job.status === "published").length;
  const blockedCount = data.jobs.filter(job => job.publication_state === "blocked" || job.status === "failed").length;
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
    if (selectedMode === "auto" && !window.confirm("자동 게시 설정을 요청합니다. 운영 승인과 실제 Blogger 쓰기 잠금은 유지되므로 게시가 실행되지 않습니다. 이 설정을 저장할까요?")) return;
    setBusy("mode-settings"); setMessage("");
    try {
      const response = await fetch("/api/publications/mode-settings", { method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scope_type: scopeType, scope_key: scopeKey, configured_mode: selectedMode,
          daily_auto_limit: dailyLimit, minimum_interval_minutes: minimumInterval,
          allowed_start_hour: startHour, allowed_end_hour: endHour, timezone: "Asia/Seoul",
          allowed_categories: categories.split(",").map(value => value.trim()).filter(Boolean),
          excluded_topics: excludedTopics.split(",").map(value => value.trim()).filter(Boolean), max_source_age_hours: maxAge, retry_limit: retryLimit }) });
      const result = await response.json();
      setMessage(response.ok ? "설정을 저장했습니다. 자동 게시 실행은 운영 승인과 발행 안전 게이트가 열리기 전까지 차단됩니다." : String(result.detail ?? result.error ?? "설정 저장 실패"));
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
      setMessage(response.ok ? `요청 상태: ${stateNames[String(result.publication_state ?? result.state)] ?? "기록됨"}. 실제 Blogger 게시 기능은 비활성화되어 있습니다.` : "게시 요청을 저장하지 못했습니다. 차단 사유는 운영 진단에서 확인하세요.");
      const refreshed = await fetch("/api/publications", { cache: "no-store" });
      if (refreshed.ok) setData(await refreshed.json());
    } catch { setMessage("로컬 API 서버에 연결할 수 없습니다."); }
    finally { setBusy(""); }
  }
  async function simulate(job: Job) {
    const key = crypto.randomUUID().replaceAll("-", "");
    setBusy(job.id); setMessage("");
    try {
      const response = await fetch(`/api/publications/jobs/${job.id}/simulate`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ idempotency_key: key, scenario: "success" }) });
      const result = await response.json();
      setMessage(response.ok ? `모의 게시 결과: ${stateNames[String(result.outcome)] ?? "처리됨"} · 모의 ID ${result.fake_post_id}. 실제 게시물은 생성되지 않았습니다.` : "모의 게시를 완료하지 못했습니다. 차단 사유는 운영 진단에서 확인하세요.");
      const refreshed = await fetch("/api/publications", { cache: "no-store" });
      if (refreshed.ok) setData(await refreshed.json());
    } catch { setMessage("로컬 API 서버에 연결할 수 없습니다."); }
    finally { setBusy(""); }
  }
  async function schedule(job: Job) {
    const input = document.getElementById(`schedule-${job.id}`) as HTMLInputElement | null;
    if (!input?.value) { setMessage("한국 표준시 기준의 예약 일시를 선택하세요."); return; }
    setBusy(job.id); setMessage("");
    try {
      const response = await fetch(`/api/publications/jobs/${job.id}/schedule`, { method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ idempotency_key: crypto.randomUUID().replaceAll("-", ""), scheduled_at: `${input.value}:00+09:00`, timezone: "Asia/Seoul", mock_scenario: "success" }) });
      const result = await response.json();
      setMessage(response.ok ? `모의 예약을 기록했습니다: ${result.scheduled_at}. 실제 게시 예약은 생성되지 않았습니다.` : "모의 예약을 기록하지 못했습니다.");
      const refreshed = await fetch("/api/publications", { cache: "no-store" });
      if (refreshed.ok) setData(await refreshed.json());
    } catch { setMessage("로컬 API 서버에 연결할 수 없습니다."); }
    finally { setBusy(""); }
  }
  async function cancelSchedule(job: Job) {
    setBusy(job.id); setMessage("");
    try {
      const response = await fetch(`/api/publications/jobs/${job.id}/schedule`, { method: "DELETE", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ idempotency_key: crypto.randomUUID().replaceAll("-", "") }) });
      const result = await response.json();
      setMessage(response.ok ? "모의 예약 취소를 기록했습니다." : "모의 예약 취소를 기록하지 못했습니다.");
      const refreshed = await fetch("/api/publications", { cache: "no-store" });
      if (refreshed.ok) setData(await refreshed.json());
    } catch { setMessage("로컬 API 서버에 연결할 수 없습니다."); }
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
        setMessage(`읽기 전용 확인: ${result.language_code} 블로그 게시물 ${result.posts.length}건을 조회했습니다. 다음 페이지 ${result.next_page_token ? "있음" : "없음"}. 차이는 사람이 확인해야 합니다.`);
      } else setMessage("Blogger 읽기 확인에 실패했습니다. 연결 상태를 확인하세요.");
    } catch { setMessage("로컬 API 서버에 연결할 수 없습니다."); }
    finally { setBusy(""); }
  }
  return <div className="publication-manager">
    <section className="publishing-summary" aria-label="발행 현황">
      <article><span>실제 Blogger 게시</span><strong>차단</strong></article>
      <article><span>자동 게시 실행</span><strong>비활성</strong></article>
      <article><span>승인 대기 후보</span><strong>{pendingCount.toLocaleString("ko-KR")}건</strong></article>
      <article><span>게시 기록</span><strong>{publishedCount.toLocaleString("ko-KR")}건 · 보류 {blockedCount.toLocaleString("ko-KR")}건</strong></article>
    </section>
    <nav className="workspace-tabs publication-tabs" role="tablist" aria-label="발행 관리 보기">
      <button role="tab" aria-selected={activeTab === "pending"} onClick={() => setActiveTab("pending")}>승인 대기 <span>{pendingCount}</span></button>
      <button role="tab" aria-selected={activeTab === "history"} onClick={() => setActiveTab("history")}>게시 이력</button>
      <button role="tab" aria-selected={activeTab === "settings"} onClick={() => setActiveTab("settings")}>게시 설정</button>
    </nav>
    {message && <p role="status">{message}</p>}
    {activeTab === "settings" && <section className="workspace-panel" aria-labelledby="publication-mode-heading">
      <h2 id="publication-mode-heading">게시 모드</h2>
      {data.mode_policy.migration_required ? <p role="status">게시 모드 설정을 사용하려면 DB 스키마 갱신이 필요합니다. 기본 게시 모드는 수동이며 현재 설정은 읽기 전용입니다.</p> : <>
      <p>기본값은 수동 게시입니다. 자동 게시를 선택해도 별도 운영 승인이 없고 실제 Blogger 쓰기가 잠겨 있어 실행되지 않습니다.</p>
        <p>현재 자동 게시 상태: {data.mode_policy.emergency_stopped ? "긴급 중지됨" : runtimeLabel(data.auto_runtime_status)} · 운영 승인: 없음 · 실제 Blogger 쓰기: 차단</p>
        <div className="mode-settings-form">
          <label>적용 범위 <select value={scopeType} onChange={event => chooseScope(event.target.value as "global" | "language" | "blog", "")}>
            <option value="global">전체 기본값</option><option value="language">언어별</option><option value="blog">블로그별</option>
          </select></label>
          {scopeType === "language" && <label>언어 <select value={scopeKey} onChange={event => chooseScope("language", event.target.value)}>
            <option value="">선택</option>{data.mode_policy.languages.map(language => <option key={language.code} value={language.code}>{languageLabel(language.code)}</option>)}
          </select></label>}
          {scopeType === "blog" && <label>블로그 <select value={scopeKey} onChange={event => chooseScope("blog", event.target.value)}>
            <option value="">선택</option>{data.mode_policy.blogs.map(blog => <option key={blog.id} value={blog.id}>{blog.display_name} · {blog.url}</option>)}
          </select></label>}
          <label>게시 모드 <select value={selectedMode} onChange={event => setSelectedMode(event.target.value as "manual" | "auto")}>
          <option value="manual">수동 게시</option><option value="auto" disabled>자동 게시 (Publisher 연결 및 운영 승인 후 사용 가능)</option>
          </select></label>
          {selectedMode === "auto" && <>
            <label>허용 분야 <select multiple value={categories.split(",").map(value => value.trim()).filter(Boolean)} onChange={event => setCategories(Array.from(event.currentTarget.selectedOptions, option => option.value).join(", "))}>{Object.entries(categoryNames).map(([slug, name]) => <option key={slug} value={slug}>{name}</option>)}</select></label>
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
    </section>}
    {activeTab === "pending" && syncResult && <section className="workspace-panel"><h2>Blogger 읽기 전용 확인 결과 ({languageLabel(syncResult.language_code)})</h2><p>이 조회는 내부 게시 상태를 변경하지 않습니다.</p>
      <table><thead><tr><th>Blogger 게시물 ID</th><th>제목</th><th>상태</th><th>내부 원고 연결</th></tr></thead><tbody>
        {syncResult.posts.map((post) => <tr key={post.id}><td>{post.id}</td><td>{post.title}</td><td>{post.status ?? "상태 미확인"}</td><td>{post.internal_record ? post.content_version_id : "연결된 내부 원고 없음"}</td></tr>)}
      </tbody></table>
      {syncResult.next_page_token && <button disabled={!!busy} onClick={() => {
        const candidate = data.candidates.find((item) => item.blog_id === syncResult.blog_uuid);
        if (candidate) void syncReadOnly(candidate, syncResult.next_page_token);
      }}>다음 페이지 읽기</button>}
    </section>}
    {activeTab === "pending" && <section className="workspace-panel publication-section"><div className="section-heading"><div><h2>승인 대기 원고</h2><p>기계 검사 통과와 사람의 발행 승인은 별개입니다. 조건이 부족하면 요청은 차단 상태로 기록됩니다.</p></div></div>
      {data.candidates.length ? <div className="publication-table-scroll"><table><thead><tr><th>원고</th><th>언어</th><th>대상 블로그·모드</th><th>검토·게시 상태</th><th>작업</th></tr></thead><tbody>
        {data.candidates.map((candidate) => <tr key={`${candidate.content_version_id}-${candidate.blog_id}`}>
          <td>{candidate.title}<small>원고 버전 {candidate.content_version_id.slice(0, 8)}</small></td><td>{languageLabel(candidate.language_code)}</td><td>{candidate.url}<small>{candidate.effective_mode === "auto" ? "자동 게시 설정 · 실행 차단" : "수동 게시"}</small></td>
          <td>품질 {candidate.quality_status ? stateNames[candidate.quality_status] ?? "검토 필요" : "검사 전"} · 편집 검토 {candidate.editorial_review_approved ? "완료" : "대기"} · 발행 승인 {candidate.publication_approval_approved ? "완료" : "대기"}<small>{candidate.publish_ready ? "게시 준비됨" : "게시 준비 안 됨"} · 세부 차단 사유는 운영 진단에서 확인</small></td>
          <td>{candidate.evaluation_id ? <a href={`/manuscripts?open_evaluation_id=${encodeURIComponent(candidate.evaluation_id)}&open_content_version_id=${encodeURIComponent(candidate.content_version_id)}`}>다른 언어로 발행</a> : <span>평가 연결 없음</span>}{" "}
            <button disabled={!!busy || candidate.effective_mode?.startsWith("auto")} onClick={() => void request(candidate)}>{busy === candidate.content_version_id ? "기록 중…" : "수동 발행 요청 기록"}</button>{" "}
            <button className="secondary-button" disabled={!!busy} onClick={() => void syncReadOnly(candidate)}>Blogger 게시물 읽기 확인</button></td>
        </tr>)}
      </tbody></table></div> : <p className="empty-state">승인 대기 원고가 없습니다.</p>}
    </section>}
    {activeTab === "history" && <section className="workspace-panel publication-section"><div className="section-heading"><div><h2>발행 요청 및 처리 이력</h2><p>실제 게시와 모의 테스트 결과를 구분해 표시합니다.</p></div></div>{data.jobs.length === 0 ? <p className="empty-state">발행 요청 기록이 없습니다.</p> : <div className="publication-table-scroll"><table><thead><tr><th>요청</th><th>언어·블로그</th><th>상태</th><th>차단 사유</th><th>모의 작업</th></tr></thead><tbody>
      {data.jobs.map((job) => <tr key={job.id}><td>{job.id}<small>{stateNames[job.status] ?? "상태 확인 필요"} · 모의 작업</small></td><td>{languageLabel(job.language_code)} · {job.url}</td>
        <td>{stateNames[job.publication_state] ?? stateNames[job.status] ?? "상태 확인 필요"}</td><td>{job.block_reasons.length ? "게시 조건 미충족 · 상세 사유는 운영 진단에서 확인" : "차단 사유 없음"}</td>
        <td><button disabled={!!busy} onClick={() => void simulate(job)}>{busy === job.id ? "실행 중…" : "모의 게시 시험"}</button>{" "}
          <label>모의 예약 일시 (한국 표준시) <input id={`schedule-${job.id}`} type="datetime-local" /></label>{" "}
          <button className="secondary-button" disabled={!!busy} onClick={() => void schedule(job)}>모의 예약 기록</button>{" "}
          {job.status === "queued" && <button className="secondary-button" disabled={!!busy} onClick={() => void cancelSchedule(job)}>모의 예약 취소</button>}{job.evaluation_id && <a href={`/manuscripts?open_evaluation_id=${encodeURIComponent(job.evaluation_id)}&open_content_version_id=${encodeURIComponent(job.content_version_id)}`}>다른 언어로 발행</a>}</td></tr>)}
    </tbody></table></div>}</section>}
    {activeTab === "settings" && <aside>게시 작업자 상태: {data.worker?.status === "running" ? "실행 중" : data.worker ? "중지됨" : "실행 기록 없음"} · 모의 작업 {data.queued_mock_jobs}건 · 명시 확인된 비공개 초안 대기 {data.queued_confirmed_private_drafts ?? 0}건. 운영 CLI의 `--operations-confirmed-private-drafts` 모드만 비공개 초안 큐를 처리하며 공개 발행은 계속 차단됩니다.</aside>}
  </div>;
}
