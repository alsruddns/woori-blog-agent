"use client";
import { useEffect, useState, type FormEvent } from "react";

type Profile = { id: string; language_code: string; target_country: string; active: boolean };
type Keyword = { id: string; keyword: string; status: string; language_code: string; target_country: string; priority: number; search_volume: number | null; cpc: number | null; collection_source: string; rationale: string; expires_at: string };
type Source = { id: string; keyword_id: string; source_name: string; url: string; evidence: string; rights: string; reliability_reason: string; access_policy: string; approved: boolean | null; review_reason: string | null; valid_until: string };
type Job = { id: string; status: string; attempts: number; paused: boolean; error_type: string | null; error_at: string | null };
type Version = { id: string; group_id: string; language: string; localization_id: string; version: number; title: string; body: string; source_version_id: string | null; state: string; provider: string; model: string; result_metadata: { summary: string; keywords: string[]; quality: Record<string, unknown> } };
type Setting = { profile_id: string; provider: string; model: string; enabled: boolean; language_verified: boolean; verification_reason: string; prompt_id: string; daily_limit: number; threads: number; timeout_seconds: number };
export type State = {
 profiles: Profile[]; categories: { id: string; slug: string }[]; keywords: Keyword[]; sources: Source[];
 jobs: Job[]; versions: Version[]; settings: Setting[]; prompts: { id: string; name: string; version: number; instructions: string }[];
 controls: { paused: boolean; max_concurrency: number; cpu_percent: number; ram_percent: number };
 schedules: { id: string; category_id: string; profile_id: string; active: boolean; schedule_cron: string; timezone: string; quantity: number; next_run_at: string }[];
 attempts: Record<string, unknown>[]; events: Record<string, unknown>[]; dispatches: Record<string, unknown>[];
};
const fields = (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); return new FormData(event.currentTarget); };
const text = (form: FormData, key: string) => String(form.get(key) ?? "");
const checked = (form: FormData, key: string) => form.get(key) === "on";
const date = (form: FormData, key: string) => new Date(text(form, key)).toISOString();
function Input({ name, label, type = "text", value, required = true }: { name: string; label: string; type?: string; value?: string | number; required?: boolean }) {
 return <label>{label} <input name={name} type={type} defaultValue={value} required={required}/></label>;
}
export default function Research({ initial }: { initial: State }) {
 const [data, setData] = useState(initial), [message, setMessage] = useState(""), [busy, setBusy] = useState(false);
 const [first, setFirst] = useState(""), [second, setSecond] = useState("");
 async function refresh() {
  const r = await fetch("/api/research/state", { cache: "no-store" });
  if (!r.ok) throw new Error("?? ?? ??");
  setData(await r.json() as State);
 }
 useEffect(() => { const timer = setInterval(() => { refresh().catch(() => setMessage("?? ?? ??. API ??? ?????.")); }, 5000); return () => clearInterval(timer); }, []);
 async function act(path: string, body: object, method = "POST") {
  setBusy(true);
  try {
   const response = await fetch(`/api/research/${path}`, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
   const result = await response.json() as { error?: string; detail?: unknown };
   if (!response.ok) throw new Error(result.error ?? JSON.stringify(result.detail ?? "?? ??"));
   setMessage("??????. ?? ??? Worker? ?????."); await refresh();
  } catch (error) { setMessage(error instanceof Error ? error.message : "?? ??"); } finally { setBusy(false); }
 }
 const profiles = (name = "profile_id") => <select name={name} required>{data.profiles.filter(p => p.active).map(p => <option key={p.id} value={p.id}>{p.language_code} / {p.target_country || "?? ???"}</option>)}</select>;
 const categories = <select name="category_id" required>{data.categories.map(c => <option key={c.id} value={c.id}>{c.slug}</option>)}</select>;
 const keywords = <select name="keyword_id" required>{data.keywords.map(k => <option key={k.id} value={k.id}>{k.keyword} ({k.language_code})</option>)}</select>;
 const a = data.versions.find(v => v.id === first), b = data.versions.find(v => v.id === second);
 return <>
 <p role="status">{message}</p><button disabled={busy} onClick={() => refresh().catch(() => setMessage("?? ??"))}>?? ??</button>
 <section><h2>??? ?? ?????</h2><p>????????CPC? ??? ???? ???? ??? ??????. ????? ??? ?????.</p>
 <form onSubmit={e => { const f = fields(e); void act("keywords", { profile_id: text(f,"profile_id"), category_id: text(f,"category_id"), keyword: text(f,"keyword"), search_intent: text(f,"search_intent"), collection_source: text(f,"collection_source"), rationale: text(f,"rationale"), priority: Number(text(f,"priority")), expires_at: date(f,"expires_at") }); }}>
 {profiles()}{categories}<Input name="keyword" label="???"/><Input name="search_intent" label="?? ??"/><Input name="collection_source" label="?? ??"/><Input name="rationale" label="?? ??"/><Input name="priority" label="???? 1?100" type="number" value={50}/><Input name="expires_at" label="?? ??" type="datetime-local"/><button disabled={busy}>?? ??</button></form>
 {data.keywords.map(k => <article key={k.id}><h3>{k.keyword} ? {k.language_code}/{k.target_country} ? {k.status}</h3><p>{k.collection_source} ? {k.rationale} ? ???? {k.priority} ? ??? {k.search_volume ?? "???"} ? CPC {k.cpc ?? "???"} ? ?? ?? {k.expires_at}</p>
 <button disabled={busy} onClick={() => act(`keywords/${k.id}`, { status: "selected" }, "PUT")}>??</button><button disabled={busy} onClick={() => act(`keywords/${k.id}`, { status: "excluded" }, "PUT")}>??</button>
 <button disabled={busy || k.status !== "selected"} onClick={() => act("jobs", { keyword_id: k.id, idempotency_key: crypto.randomUUID() })}>?? ??? ?? ?? ??</button></article>)}
 </section>
 <section><h2>?? ????? ??</h2><p>?? ????? ????. ??? ?? ??? ?? ??? ?? ???? ?? ??? ?????. ??? ?? ???? ?? ?? ???? ?? ?? ??? ????.</p>
 <form onSubmit={e => { const f = fields(e); void act("sources", { keyword_id: text(f,"keyword_id"), url: text(f,"url"), source_name: text(f,"source_name"), published_at: text(f,"published_at") ? date(f,"published_at") : null, evidence: text(f,"evidence"), reliability_reason: text(f,"reliability_reason"), rights: text(f,"rights"), access_policy: text(f,"access_policy"), valid_until: date(f,"valid_until"), is_primary: checked(f,"is_primary") }); }}>
 {keywords}<Input name="url" label="?? HTTPS URL (?? ??)" type="url"/><Input name="source_name" label="???"/><Input name="published_at" label="??? (??? ??)" type="datetime-local" required={false}/><label>?? (?? 1,000?)<textarea name="evidence" maxLength={1000} minLength={10} required/></label><Input name="reliability_reason" label="??? ?? ??"/><Input name="rights" label="?????? ?? ??"/><Input name="access_policy" label="robots???????? ??"/><Input name="valid_until" label="?? ?? ??" type="datetime-local"/><label><input type="checkbox" name="is_primary"/>?? 1? ??</label><button disabled={busy || !data.keywords.length}>?? ??</button></form>
 {data.sources.map(s => <article key={s.id}><h3><a href={s.url} target="_blank" rel="noreferrer">{s.source_name}</a> ? {s.approved === null ? "???" : s.approved ? "?? ??" : "?? ??"}</h3><p>{s.evidence}</p><p>{s.reliability_reason} ? {s.rights} ? {s.access_policy} ? ?? ?? {s.valid_until}</p><p>{s.review_reason}</p><form onSubmit={e => { const f = fields(e); void act(`sources/${s.id}/reviews`, { approved: text(f,"approved") === "true", reason: text(f,"reason"), reviewer: text(f,"reviewer") }); }}><select name="approved"><option value="false">?????? ?? ??</option><option value="true">???????? ??</option></select><Input name="reason" label="?? ?? (10? ??)"/><Input name="reviewer" label="???"/><button disabled={busy}>? ?? ?? ??</button></form></article>)}
 </section>
 <section><h2>?? ?????????</h2>{data.jobs.map(j => <article key={j.id}><p>{j.id} ? {j.status} ? ?? {j.attempts} ? {j.paused ? "?? ??" : "?? ??"} ? {j.error_type} {j.error_at}</p><button disabled={busy || j.status === "succeeded"} onClick={() => act(`jobs/${j.id}/action`, { action: j.paused ? "resume" : "pause" })}>{j.paused ? "??" : "?? ??"}</button><button disabled={busy || j.status !== "failed" || j.attempts >= 3} onClick={() => act(`jobs/${j.id}/action`, { action: "retry" })}>???</button></article>)}<details><summary>?????? ?? ?? ??</summary><pre>{JSON.stringify({ attempts: data.attempts, dispatches: data.dispatches }, null, 2)}</pre></details></section>
 <section><h2>?????? ????? ?? ??</h2><p>??? ?? ?? ????? Google ??? ??? ???? ????. Mock? ?? ?? ?? ??? ????.</p>
 {[{value:first,set:setFirst},{value:second,set:setSecond}].map((item,i) => <label key={i}>?? {i+1}<select value={item.value} onChange={e => item.set(e.target.value)}><option value="">?? ??</option>{data.versions.map(v => <option key={v.id} value={v.id}>{v.language} v{v.version} {v.title}</option>)}</select></label>)}
 {a && b && <p>{a.localization_id === b.localization_id ? "?? ???? ?? ??" : "?? ?? ??? ??"} ? ?? ? {b.body.split("\n").filter(line => !a.body.split("\n").includes(line)).length} ? ?? ? {a.body.split("\n").filter(line => !b.body.split("\n").includes(line)).length}</p>}
 <div style={{ display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(280px,1fr))",gap:20 }}>{[a,b].map((v,i) => v && <article key={i}><h3>{v.title}</h3><p>{v.language} v{v.version} ? {v.state} ? {v.model} ? ?? {v.group_id} ? ?? ?? {v.source_version_id ?? "??"}</p><pre style={{whiteSpace:"pre-wrap"}}>{v.body}</pre><p>{v.result_metadata.summary}</p><pre>{JSON.stringify(v.result_metadata.quality,null,2)}</pre></article>)}</div></section>
 <section><h2>??? AI????? ??</h2><p>Mock? ??? ?????. Local? ??? CPU ??? ???? ??? ?? ??? ??? ?????. ? ???? ??? ?????.</p>
 {data.settings.map(s => <form key={s.profile_id} onSubmit={e => { const f = fields(e); void act(`settings/${s.profile_id}`, { provider:text(f,"provider"), model:text(f,"model"), enabled:checked(f,"enabled"), language_verified:checked(f,"language_verified"), verification_reason:text(f,"verification_reason"), prompt_id:text(f,"prompt_id"), daily_limit:Number(text(f,"daily_limit")), threads:Number(text(f,"threads")), timeout_seconds:Number(text(f,"timeout_seconds")) }, "PUT"); }}><h3>{data.profiles.find(p => p.id === s.profile_id)?.language_code} / {data.profiles.find(p => p.id === s.profile_id)?.target_country || "?? ???"}</h3><select name="provider" defaultValue={s.provider}><option value="mock">Mock ???</option><option value="local">Local Ollama CPU</option></select><Input name="model" label="??? ???" value={s.model}/><select name="prompt_id" defaultValue={s.prompt_id}>{data.prompts.map(p => <option key={p.id} value={p.id}>{p.name} v{p.version}</option>)}</select><Input name="daily_limit" label="?? ?? ? (1?50)" type="number" value={s.daily_limit}/><Input name="threads" label="CPU ??? (1?4)" type="number" value={s.threads}/><Input name="timeout_seconds" label="???? ? (5?60)" type="number" value={s.timeout_seconds}/><label><input name="enabled" type="checkbox" defaultChecked={s.enabled}/>?? ??</label><label><input name="language_verified" type="checkbox" defaultChecked={s.language_verified}/>?? ????? ?? ?? ??</label><Input name="verification_reason" label="????? ?? ??" value={s.verification_reason} required={false}/><button disabled={busy}>?? ??</button></form>)}
 <form onSubmit={e => { const f = fields(e); void act("prompts", { name:text(f,"name"),instructions:text(f,"instructions") }); }}><Input name="name" label="???? ?? (?? ??????????)"/><label>? ?? ???<textarea name="instructions" minLength={30} required/></label><button disabled={busy}>???? ? ?? ??</button></form><details><summary>?? ???? ??</summary>{data.prompts.map(p => <article key={p.id}><h3>{p.name} v{p.version}</h3><p>{p.instructions}</p></article>)}</details></section>
 <section><h2>?? ??????</h2><p>CPU/RAM? ?? ? ?? ?????. ?? ? OS ?? ?? ??? ????. Local? GPU 0????? 2048??? 1024??? ?? 4GiB ??? ?????.</p><form onSubmit={e => { const f=fields(e); void act("controls",{paused:checked(f,"paused"),max_concurrency:Number(text(f,"max_concurrency")),cpu_percent:Number(text(f,"cpu_percent")),ram_percent:Number(text(f,"ram_percent"))},"PUT"); }}><label><input type="checkbox" name="paused" defaultChecked={data.controls.paused}/>?? ?? ??</label><Input name="max_concurrency" label="?? ?? (1?2)" type="number" value={data.controls.max_concurrency}/><Input name="cpu_percent" label="CPU ?? ?? %" type="number" value={data.controls.cpu_percent}/><Input name="ram_percent" label="RAM ?? ?? %" type="number" value={data.controls.ram_percent}/><button disabled={busy}>?? ?? ??</button></form>
 <p>???? ??? ??? ??? ?????. ?? ??? ?? ??? ???? ?????. ?? ?? ???????? ?? ???? ?? ???? ?????.</p><form onSubmit={e => { const f=fields(e); void act("schedules",{category_id:text(f,"category_id"),profile_id:text(f,"profile_id"),active:checked(f,"active"),schedule_cron:text(f,"schedule_cron"),timezone:text(f,"timezone"),quantity:Number(text(f,"quantity"))}); }}>{categories}{profiles()}<Input name="schedule_cron" label="Cron (?? 5? ??)" value="0 9 * * *"/><Input name="timezone" label="???" value="Asia/Seoul"/><Input name="quantity" label="?? ?? ? (1?10)" type="number" value={1}/><label><input name="active" type="checkbox"/>??? ???</label><button disabled={busy}>??? ??</button></form><pre>{JSON.stringify(data.schedules,null,2)}</pre></section>
 <details><summary>?? ?? ?? ??</summary><pre>{JSON.stringify(data.events,null,2)}</pre></details>
 </>;
}
