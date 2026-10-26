"use client";

import { useState } from "react";

type Candidate = {
  content_version_id: string; title: string; language_code: string; target_country: string;
  blog_id: string; url: string; blogger_blog_id: string | null; machine_passed: boolean;
  human_review_required: boolean; publish_ready: boolean; quality_status: string | null;
};
type Job = { id: string; content_version_id: string; language_code: string; url: string; status: string; publication_state: string; block_reasons: string[]; simulation_count: number };
type SyncPost = { id: string | null; url: string | null; title: string | null; status: string | null; published: string | null; updated: string | null; internal_record: boolean; content_version_id: string | null };
type SyncResult = { language_code: string; blog_uuid: string; posts: SyncPost[]; next_page_token: string; read_only: true; internal_state_changed: false };
export type PublicationData = { candidates: Candidate[]; jobs: Job[]; simulations: unknown[]; worker: { process_id: number; status: string; last_seen_at: string } | null; queued_mock_jobs: number; real_writes_enabled: false; publish_ready_enabled: false; adapter_available: string };

export default function PublicationManager({ initial }: { initial: PublicationData }) {
  const [data, setData] = useState(initial);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState("");
  const [syncResult, setSyncResult] = useState<SyncResult | null>(null);
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
      <table><thead><tr><th>Version</th><th>Language</th><th>Blog</th><th>Machine review</th><th>Action</th></tr></thead><tbody>
        {data.candidates.map((candidate) => <tr key={`${candidate.content_version_id}-${candidate.blog_id}`}>
          <td>{candidate.title}<small>{candidate.content_version_id}</small></td><td>{candidate.language_code}</td><td>{candidate.url}</td>
          <td>{candidate.quality_status ?? "not evaluated"}; human review pending; publish_ready={String(candidate.publish_ready)}</td>
          <td><button disabled={!!busy} onClick={() => void request(candidate)}>{busy === candidate.content_version_id ? "Recording…" : "Record blocked request"}</button>{" "}
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
          {job.status === "queued" && <button disabled={!!busy} onClick={() => void cancelSchedule(job)}>Cancel mock</button>}</td></tr>)}
    </tbody></table></section>
  </>;
}
