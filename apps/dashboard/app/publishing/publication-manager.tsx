"use client";

import { useState } from "react";

type Candidate = {
  content_version_id: string; title: string; language_code: string; target_country: string;
  blog_id: string; url: string; blogger_blog_id: string | null; machine_passed: boolean;
  human_review_required: boolean; publish_ready: boolean; quality_status: string | null;
};
type Job = { id: string; content_version_id: string; language_code: string; url: string; status: string; publication_state: string; block_reasons: string[]; simulation_count: number };
export type PublicationData = { candidates: Candidate[]; jobs: Job[]; simulations: unknown[]; real_writes_enabled: false; publish_ready_enabled: false; adapter_available: string };

export default function PublicationManager({ initial }: { initial: PublicationData }) {
  const [data, setData] = useState(initial);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState("");
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
  return <>
    {message && <p role="status">{message}</p>}
    <section><h2>Draft candidates</h2><p>Requests are recorded as blocked when any eligibility condition is unmet. A machine pass does not constitute human approval.</p>
      <table><thead><tr><th>Version</th><th>Language</th><th>Blog</th><th>Machine review</th><th>Action</th></tr></thead><tbody>
        {data.candidates.map((candidate) => <tr key={`${candidate.content_version_id}-${candidate.blog_id}`}>
          <td>{candidate.title}<small>{candidate.content_version_id}</small></td><td>{candidate.language_code}</td><td>{candidate.url}</td>
          <td>{candidate.quality_status ?? "not evaluated"}; human review pending; publish_ready={String(candidate.publish_ready)}</td>
          <td><button disabled={!!busy} onClick={() => void request(candidate)}>{busy === candidate.content_version_id ? "Recording…" : "Record blocked request"}</button></td>
        </tr>)}
      </tbody></table>
    </section>
    <section><h2>Publication request ledger</h2><table><thead><tr><th>Request</th><th>Language / blog</th><th>State</th><th>Block reasons</th><th>Offline test</th></tr></thead><tbody>
      {data.jobs.map((job) => <tr key={job.id}><td>{job.id}<small>{job.status} / simulation-only</small></td><td>{job.language_code} · {job.url}</td>
        <td>{job.publication_state}</td><td>{job.block_reasons.join(", ")}</td>
        <td><button disabled={!!busy} onClick={() => void simulate(job)}>{busy === job.id ? "Running…" : "Run offline Fake adapter"}</button></td></tr>)}
    </tbody></table></section>
  </>;
}
