"use client";

import { useEffect, useState } from "react";

type Policy = {
  id: string;
  enabled: boolean;
  allowed_geos: string[];
  daily_limit: number;
  created_at: string;
};
type Blog = {
  id: string;
  display_name: string;
  language_code: string;
  active: boolean;
  mapped_geos: string[];
  policy: Policy | null;
};
type State = { policies: Blog[]; supported_geographies: string[] };
type Draft = { enabled: boolean; geos: string[]; daily_limit: number; reason: string; confirmation: string };

export default function TrendsPublicationSettings() {
  const [state, setState] = useState<State | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [actor, setActor] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState("");

  async function load() {
    const response = await fetch("/api/publications/trends-auto-policy", { cache: "no-store" });
    if (!response.ok) throw new Error(`Trends 발행 정책 조회 실패 (HTTP ${response.status})`);
    const data = await response.json() as State;
    setState(data);
    setDrafts(Object.fromEntries(data.policies.map(blog => [blog.id, {
      enabled: blog.policy?.enabled ?? false,
      geos: blog.policy?.allowed_geos ?? [],
      daily_limit: blog.policy?.daily_limit ?? 3,
      reason: "",
      confirmation: "",
    }])));
  }

  useEffect(() => {
    void Promise.resolve().then(() => load()).catch(error => setMessage(String(error)));
  }, []);

  function patch(blogId: string, value: Partial<Draft>) {
    setDrafts(current => ({ ...current, [blogId]: { ...current[blogId], ...value } }));
  }

  async function save(blog: Blog) {
    const draft = drafts[blog.id];
    if (!draft || busy) return;
    setBusy(blog.id);
    setMessage("");
    try {
      const confirmation = draft.enabled ? "ENABLE TRENDS AUTO PUBLICATION" : "STOP TRENDS AUTO PUBLICATION";
      if (draft.confirmation !== confirmation) throw new Error(`확인 문구를 정확히 입력하세요: ${confirmation}`);
      const response = await fetch("/api/publications/trends-auto-policy", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          blog_id: blog.id, enabled: draft.enabled,
          allowed_geos: draft.geos, daily_limit: draft.daily_limit,
          actor_label: actor, reason: draft.reason,
          confirmation, idempotency_key: crypto.randomUUID(),
        }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail ?? result.error ?? `HTTP ${response.status}`);
      await load();
      setMessage(`${blog.display_name}: 설정 변경 감사 기록을 추가했습니다.`);
    } catch (error) {
      setMessage(String(error));
    } finally {
      setBusy(null);
    }
  }

  return <section className="workspace-panel" aria-labelledby="trends-auto-policy-heading">
    <h2 id="trends-auto-policy-heading">Google Trends 자동 발행 정책</h2>
    <p>예약 Auto와 별도인 Trends 전용 정책입니다. 이 설정만으로 공개 쓰기가 허용되지는 않습니다. 검증된 주장·출처·권리, Blogger 매핑, 긴급 정지, 별도 운영 공개 승인과 Worker 상태를 매번 확인합니다.</p>
    <label>설정 변경자<input value={actor} minLength={2} maxLength={120} onChange={event => setActor(event.target.value)} /></label>
    {!state && !message && <p role="status">정책을 불러오는 중입니다.</p>}
    {state?.policies.map(blog => {
      const draft = drafts[blog.id];
      if (!draft) return null;
      const confirmation = draft.enabled ? "ENABLE TRENDS AUTO PUBLICATION" : "STOP TRENDS AUTO PUBLICATION";
      return <fieldset className="trend-blog-geo" key={blog.id}>
        <legend>{blog.display_name} · {blog.language_code}</legend>
        <p>상태: {blog.policy?.enabled ? "활성" : "비활성"} · 연결된 수집 지역: {blog.mapped_geos.length ? blog.mapped_geos.join(", ") : "없음"}</p>
        <label><input type="checkbox" checked={draft.enabled} onChange={event => patch(blog.id, { enabled: event.target.checked, confirmation: "" })} /> Trends 자동 발행 허용</label>
        <div className="trend-geo-options">{blog.mapped_geos.map(geo => <label key={geo}>
          <input type="checkbox" checked={draft.geos.includes(geo)} onChange={event => patch(blog.id, {
            geos: event.target.checked ? [...draft.geos, geo] : draft.geos.filter(value => value !== geo), confirmation: "",
          })} />{geo}
        </label>)}</div>
        <label>일일 발행 상한<input type="number" min={1} max={10} value={draft.daily_limit} onChange={event => patch(blog.id, { daily_limit: Number(event.target.value), confirmation: "" })} /></label>
        <label>변경 사유<input minLength={10} maxLength={2000} value={draft.reason} onChange={event => patch(blog.id, { reason: event.target.value, confirmation: "" })} /></label>
        <label>명시적 확인 문구<input value={draft.confirmation} placeholder={confirmation} onChange={event => patch(blog.id, { confirmation: event.target.value })} /></label>
        <button type="button" className="button button-secondary" disabled={busy !== null || !blog.active || actor.trim().length < 2 || draft.reason.trim().length < 10 || draft.confirmation !== confirmation || (draft.enabled && (!draft.geos.length || !blog.mapped_geos.length))} onClick={() => void save(blog)}>
          {busy === blog.id ? "저장 중…" : "정책 변경 기록"}
        </button>
        {blog.policy && <small>마지막 변경: {new Intl.DateTimeFormat("ko-KR", { dateStyle: "short", timeStyle: "short", timeZone: "Asia/Seoul" }).format(new Date(blog.policy.created_at))} · 상한 {blog.policy.daily_limit}건</small>}
      </fieldset>;
    })}
    {message && <p role="status">{message}</p>}
  </section>;
}
